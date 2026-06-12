from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "array_inspector.py"
SPEC = importlib.util.spec_from_file_location("array_inspector", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
INSPECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSPECTOR)


class ArrayInspectorTest(unittest.TestCase):
    def test_manual_shape_matches_scalar_vector_and_matrix(self) -> None:
        self.assertEqual(INSPECTOR.infer_shape(7), ())
        self.assertEqual(INSPECTOR.infer_shape([7, 8, 9]), (3,))
        self.assertEqual(
            INSPECTOR.infer_shape([[1, 2, 3], [4, 5, 6]]),
            (2, 3),
        )

    def test_ragged_sequence_is_rejected_before_numpy(self) -> None:
        with self.assertRaisesRegex(INSPECTOR.ArrayContractError, "ragged"):
            INSPECTOR.infer_shape([[1, 2], [3]])

    def test_non_numeric_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(INSPECTOR.ArrayContractError, "real number"):
            INSPECTOR.inspect_values([1, "2", 3])

    def test_report_exposes_core_ndarray_attributes(self) -> None:
        report = INSPECTOR.inspect_values([[12, 15, 9], [10, 11, 14]])

        self.assertEqual(report["array_type"], "ndarray")
        self.assertEqual(report["ndim"], 2)
        self.assertEqual(report["shape"], [2, 3])
        self.assertEqual(report["size"], 6)
        self.assertIn(report["dtype_kind"], {"i", "u"})
        self.assertTrue(all(report["invariants"].values()))

    def test_requested_dtype_is_applied(self) -> None:
        report = INSPECTOR.inspect_values([1, 2, 3], "float32")

        self.assertEqual(report["dtype"], "float32")
        self.assertEqual(report["values"], [1.0, 2.0, 3.0])

    def test_markdown_is_a_standalone_cheatsheet(self) -> None:
        markdown = INSPECTOR.render_markdown(INSPECTOR.inspect_values([1, 2, 3]))

        self.assertIn("## Creation recipes", markdown)
        self.assertIn("np.linspace(0, 1, num=5)", markdown)
        self.assertIn("## Python list and ndarray", markdown)
        self.assertIn("`shape`: `(3,)`", markdown)

    def test_cli_prints_json_report(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--values",
                "[[1, 2], [3, 4]]",
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["shape"], [2, 2])
        self.assertEqual(report["size"], 4)

    def test_cli_returns_usage_error_for_ragged_input(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--values",
                "[[1, 2], [3]]",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("ragged nested sequence", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
