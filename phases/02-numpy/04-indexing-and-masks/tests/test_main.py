from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "numeric_filters.py"
SPEC = importlib.util.spec_from_file_location("numeric_filters", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
FILTERS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FILTERS)


class NumericFiltersTest(unittest.TestCase):
    def test_range_mask_respects_boundaries_and_nan(self) -> None:
        values = np.array([5.0, 10.0, 15.0, 20.0, np.nan])
        np.testing.assert_array_equal(
            FILTERS.range_mask(values, lower=10, upper=20),
            [False, True, True, True, False],
        )
        np.testing.assert_array_equal(
            FILTERS.range_mask(
                values,
                lower=10,
                upper=20,
                inclusive="neither",
            ),
            [False, False, True, False, False],
        )

    def test_filtered_result_is_independent_copy(self) -> None:
        source = np.array([5, 12, 18, 27])
        selected = FILTERS.filter_observations(source, lower=10, upper=20)
        selected[0] = 999
        np.testing.assert_array_equal(source, [5, 12, 18, 27])

    def test_basic_slice_and_advanced_indexing_memory(self) -> None:
        report = FILTERS.memory_report([1, 2, 3, 4])
        self.assertTrue(report["basic_slice_shares_memory"])
        self.assertFalse(report["advanced_shares_memory"])

    def test_replace_where_copies_by_default(self) -> None:
        source = np.array([1.0, 2.0, 3.0])
        result = FILTERS.replace_where(source, source > 1, 0.0)
        np.testing.assert_array_equal(source, [1.0, 2.0, 3.0])
        np.testing.assert_array_equal(result, [1.0, 0.0, 0.0])

    def test_replace_where_can_be_explicitly_in_place(self) -> None:
        source = np.array([1.0, 2.0, 3.0])
        result = FILTERS.replace_where(source, source > 1, 0.0, in_place=True)
        self.assertIs(result, source)
        np.testing.assert_array_equal(source, [1.0, 0.0, 0.0])

    def test_mask_shape_must_match(self) -> None:
        with self.assertRaisesRegex(FILTERS.NumericFilterError, "mask shape"):
            FILTERS.replace_where(np.array([1, 2, 3]), np.array([True]), 0)

    def test_cli_reports_selection(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--values",
                "[5, 12, 18, 27]",
                "--lower",
                "10",
                "--upper",
                "20",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["selected"], [12, 18])
        self.assertFalse(report["shares_memory"])

    def test_cli_rejects_reversed_bounds(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--values",
                "[1, 2, 3]",
                "--lower",
                "5",
                "--upper",
                "2",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
