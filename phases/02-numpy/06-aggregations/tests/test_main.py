from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "axis_aggregates.py"
SPEC = importlib.util.spec_from_file_location("axis_aggregates", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AGGREGATES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGGREGATES)


class AxisAggregatesTest(unittest.TestCase):
    def test_manual_sum_explains_both_matrix_axes(self) -> None:
        values = [[1, 2, 3], [4, 5, 6]]
        self.assertEqual(AGGREGATES.manual_sum_2d(values, axis=0), [5, 7, 9])
        self.assertEqual(AGGREGATES.manual_sum_2d(values, axis=1), [6, 15])

    def test_axis_zero_aggregates_columns(self) -> None:
        report = AGGREGATES.aggregate([[1, 2, 3], [4, 5, 6]], axis=0)
        self.assertEqual(report["aggregates"]["sum"]["value"], [5.0, 7.0, 9.0])
        self.assertEqual(report["aggregates"]["sum"]["shape"], [3])
        self.assertEqual(report["aggregates"]["count"]["value"], [2, 2, 2])

    def test_axis_one_aggregates_rows(self) -> None:
        report = AGGREGATES.aggregate([[1, 2, 3], [4, 5, 6]], axis=1)
        self.assertEqual(report["aggregates"]["mean"]["value"], [2.0, 5.0])
        self.assertEqual(report["aggregates"]["mean"]["shape"], [2])

    def test_keepdims_preserves_reduced_axis(self) -> None:
        report = AGGREGATES.aggregate(
            [[1, 2, 3], [4, 5, 6]],
            axis=1,
            keepdims=True,
        )
        self.assertEqual(report["aggregates"]["mean"]["shape"], [2, 1])

    def test_negative_axis_matches_numpy(self) -> None:
        report = AGGREGATES.aggregate([[1, 2], [3, 4]], axis=-1)
        np.testing.assert_allclose(report["aggregates"]["std"]["value"], [0.5, 0.5])
        self.assertEqual(report["axis"], 1)

    def test_invalid_ddof_is_rejected(self) -> None:
        with self.assertRaisesRegex(AGGREGATES.AggregationError, "ddof"):
            AGGREGATES.aggregate([[1, 2], [3, 4]], axis=1, ddof=2)

    def test_cli_returns_shapes_and_values(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--values",
                "[[1, 2, 3], [4, 5, 6]]",
                "--axis",
                "0",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["aggregates"]["max"]["value"], [4.0, 5.0, 6.0])

    def test_cli_rejects_invalid_axis_without_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--values", "[[1, 2]]", "--axis", "2"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
