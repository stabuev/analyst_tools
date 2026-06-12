from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "numerical_checks.py"
SPEC = importlib.util.spec_from_file_location("numerical_checks", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CHECKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKS)


class NumericalChecksTest(unittest.TestCase):
    def test_tolerance_report_accepts_float_rounding(self) -> None:
        report = CHECKS.tolerance_report(
            [0.1 + 0.2],
            [0.3],
            rtol=1e-9,
            atol=1e-12,
        )
        self.assertTrue(report["all_close"])
        self.assertEqual(report["mismatch_count"], 0)

    def test_absolute_tolerance_controls_values_near_zero(self) -> None:
        strict = CHECKS.tolerance_report([1e-9], [0.0], rtol=1e-5, atol=0.0)
        practical = CHECKS.tolerance_report([1e-9], [0.0], rtol=1e-5, atol=1e-8)
        self.assertFalse(strict["all_close"])
        self.assertTrue(practical["all_close"])

    def test_shape_mismatch_is_rejected_before_broadcasting(self) -> None:
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, "shape mismatch"):
            CHECKS.tolerance_report([1, 2], [[1, 2]], rtol=0, atol=0)

    def test_safe_divide_requires_invalid_policy(self) -> None:
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, "invalid positions"):
            CHECKS.safe_divide([1, 2], [1, 0])
        result = CHECKS.safe_divide([1, 2], [1, 0], fill_value=np.nan)
        self.assertEqual(result[0], 1)
        self.assertTrue(np.isnan(result[1]))

    def test_checked_integer_add_detects_overflow(self) -> None:
        np.testing.assert_array_equal(
            CHECKS.checked_integer_add([100], [20], dtype="int8"),
            [120],
        )
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, "outside int8"):
            CHECKS.checked_integer_add([120], [20], dtype="int8")

    def test_float64_accumulator_reduces_cancellation_error(self) -> None:
        report = CHECKS.summation_report([1e8, 1.0, -1e8])
        self.assertGreater(report["float32_absolute_error"], 0)
        self.assertLessEqual(
            report["float64_absolute_error"],
            report["float32_absolute_error"],
        )

    def test_cli_returns_integrated_quality_report(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--actual",
                "[0.30000000000000004]",
                "--expected",
                "[0.3]",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["comparison"]["all_close"])
        self.assertEqual(report["division_demo"], [5.0, None, 6.0])
        self.assertIn("float64_accumulator_sum", report["summation_demo"])

    def test_cli_shape_error_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--actual", "[1, 2]", "--expected", "[1]"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
