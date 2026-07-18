from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
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
        self.assertTrue(report["passed"])
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["mismatch_count"], 0)
        self.assertEqual(report["comparison"]["reference"], "expected")

    def test_absolute_tolerance_controls_values_near_zero(self) -> None:
        strict = CHECKS.tolerance_report([1e-9], [0.0], rtol=1e-5, atol=0.0)
        practical = CHECKS.tolerance_report([1e-9], [0.0], rtol=1e-5, atol=1e-8)
        self.assertFalse(strict["passed"])
        self.assertTrue(practical["passed"])

    def test_relative_tolerance_can_weaken_a_money_contract(self) -> None:
        relative = CHECKS.tolerance_report(
            [1_000_000_000.50],
            [1_000_000_000.00],
            rtol=1e-9,
            atol=0.01,
        )
        cents_only = CHECKS.tolerance_report(
            [1_000_000_000.50],
            [1_000_000_000.00],
            rtol=0.0,
            atol=0.01,
        )
        self.assertTrue(relative["passed"])
        self.assertFalse(cents_only["passed"])

    def test_shape_mismatch_is_rejected_before_broadcasting(self) -> None:
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, "shape mismatch"):
            CHECKS.tolerance_report([1, 2], [[1, 2]], rtol=0, atol=0)

    def test_dtype_match_can_be_value_metadata_or_required_contract(self) -> None:
        optional = CHECKS.tolerance_report(
            np.array([1, 2], dtype=np.int64),
            np.array([1.0, 2.0], dtype=np.float64),
            rtol=0,
            atol=0,
        )
        required = CHECKS.tolerance_report(
            np.array([1, 2], dtype=np.int64),
            np.array([1.0, 2.0], dtype=np.float64),
            rtol=0,
            atol=0,
            require_same_dtype=True,
        )
        self.assertTrue(optional["passed"])
        self.assertFalse(optional["dtype_matches"])
        self.assertFalse(required["passed"])
        self.assertFalse(required["dtype_contract_passed"])

    def test_large_integers_are_compared_without_float_precision_loss(self) -> None:
        actual = np.array([2**53], dtype=np.int64)
        expected = np.array([2**53 + 1], dtype=np.int64)

        report = CHECKS.tolerance_report(
            actual,
            expected,
            rtol=0.0,
            atol=0.0,
        )

        self.assertFalse(report["passed"])
        self.assertEqual(report["mismatch_count"], 1)
        self.assertEqual(report["mismatch_examples"][0]["absolute_error"], 1.0)

    def test_tolerances_must_be_finite_non_negative_numbers(self) -> None:
        invalid_values = [-1.0, np.nan, np.inf, True, "0.1"]
        for invalid in invalid_values:
            with (
                self.subTest(invalid=invalid),
                self.assertRaisesRegex(
                    CHECKS.NumericalQualityError,
                    "rtol",
                ),
            ):
                CHECKS.tolerance_report([1.0], [1.0], rtol=invalid, atol=0.0)

    def test_comparison_rejects_empty_boolean_and_non_numeric_values(self) -> None:
        invalid_cases = [
            (([], []), "must not be empty"),
            (([True], [True]), "real numeric"),
            ((["1"], ["1"]), "real numeric"),
            (([1.0 + 1.0j], [1.0 + 1.0j]), "real numeric"),
        ]
        for arguments, message in invalid_cases:
            with (
                self.subTest(arguments=arguments),
                self.assertRaisesRegex(
                    CHECKS.NumericalQualityError,
                    message,
                ),
            ):
                CHECKS.tolerance_report(*arguments, rtol=0.0, atol=0.0)

    def test_matching_infinities_fail_the_finite_result_policy(self) -> None:
        report = CHECKS.tolerance_report([np.inf], [np.inf], rtol=0.0, atol=0.0)
        self.assertFalse(report["passed"])
        self.assertEqual(report["mismatch_count"], 1)
        self.assertEqual(
            report["mismatch_examples"][0]["reason"],
            "infinity_not_allowed",
        )
        self.assertEqual(report["non_finite"]["actual_infinity_count"], 1)

    def test_matching_nan_requires_explicit_policy(self) -> None:
        strict = CHECKS.tolerance_report(
            [np.nan, 1.0],
            [np.nan, 1.0],
            rtol=0.0,
            atol=0.0,
        )
        explicit = CHECKS.tolerance_report(
            [np.nan, 1.0],
            [np.nan, 1.0],
            rtol=0.0,
            atol=0.0,
            equal_nan=True,
        )
        self.assertFalse(strict["passed"])
        self.assertTrue(explicit["passed"])
        self.assertEqual(explicit["non_finite"]["actual_nan_count"], 1)

    def test_mismatch_report_contains_bounded_diagnostics(self) -> None:
        report = CHECKS.tolerance_report(
            [1.0, 2.0, 3.0],
            [1.0, 4.0, 6.0],
            rtol=0.0,
            atol=0.0,
            max_mismatches=1,
        )
        self.assertEqual(report["mismatch_count"], 2)
        self.assertEqual(len(report["mismatch_examples"]), 1)
        self.assertTrue(report["mismatch_examples_truncated"])
        first = report["mismatch_examples"][0]
        self.assertEqual(first["index"], [1])
        self.assertEqual(first["actual"], 2.0)
        self.assertEqual(first["expected"], 4.0)
        self.assertEqual(first["absolute_error"], 2.0)
        self.assertEqual(first["allowed_error"], 0.0)

    def test_scalar_comparison_has_an_empty_coordinate_index(self) -> None:
        report = CHECKS.tolerance_report(1.0, 2.0, rtol=0.0, atol=0.0)
        self.assertEqual(report["shape"], [])
        self.assertEqual(report["mismatch_examples"][0]["index"], [])

    def test_assertion_reports_the_first_failed_index(self) -> None:
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, r"index \[1\]"):
            CHECKS.assert_numerically_close(
                [1.0, 2.0],
                [1.0, 3.0],
                rtol=0.0,
                atol=0.0,
            )

    def test_safe_divide_requires_an_invalid_position_policy(self) -> None:
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, "invalid positions"):
            CHECKS.safe_divide([1.0, 2.0], [1.0, 0.0])
        result = CHECKS.safe_divide(
            [1.0, 2.0, np.nan],
            [1.0, 0.0, 2.0],
            fill_value=np.nan,
        )
        np.testing.assert_allclose(result[:1], [1.0])
        self.assertTrue(np.isnan(result[1:]).all())

    def test_safe_divide_rejects_infinite_fill_and_floating_overflow(self) -> None:
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, "not infinity"):
            CHECKS.safe_divide([1.0], [0.0], fill_value=np.inf)
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, "division failed"):
            CHECKS.safe_divide(
                [np.finfo(np.float64).max],
                [np.finfo(np.float64).tiny],
            )

    def test_checked_integer_add_detects_overflow_after_broadcasting(self) -> None:
        np.testing.assert_array_equal(
            CHECKS.checked_integer_add([100, 10], 20, dtype="int8"),
            [120, 30],
        )
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, "outside int8"):
            CHECKS.checked_integer_add([120], [20], dtype="int8")

    def test_checked_integer_add_rejects_non_integer_contracts(self) -> None:
        invalid_cases = [
            (([True], [1], "int8"), "integer values"),
            (([1.5], [1], "int8"), "integer values"),
            (([1], [1], "float64"), "requires an integer dtype"),
        ]
        for (left, right, dtype), message in invalid_cases:
            with (
                self.subTest(dtype=dtype),
                self.assertRaisesRegex(
                    CHECKS.NumericalQualityError,
                    message,
                ),
            ):
                CHECKS.checked_integer_add(left, right, dtype=dtype)

    def test_floating_range_report_orders_subnormal_normal_and_max(self) -> None:
        report = CHECKS.floating_range_report("float32")
        self.assertEqual(report["bits"], 32)
        self.assertGreater(report["eps_near_one"], 0.0)
        self.assertLess(
            report["smallest_positive_subnormal"],
            report["smallest_positive_normal"],
        )
        self.assertLess(
            report["smallest_positive_normal"],
            report["max_finite"],
        )

    def test_float64_accumulator_reduces_error_over_float32_storage(self) -> None:
        report = CHECKS.summation_report([1e8, 1.0, -1e8])
        self.assertEqual(report["storage_dtype"], "float32")
        self.assertEqual(report["accumulator_dtype"], "float64")
        self.assertGreater(report["storage_accumulator_absolute_error"], 0.0)
        self.assertLessEqual(
            report["chosen_accumulator_absolute_error"],
            report["storage_accumulator_absolute_error"],
        )
        self.assertIn("cannot be restored", report["reference_boundary"])

    def test_summation_rejects_narrow_accumulator_and_non_finite_storage(self) -> None:
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, "at least as wide"):
            CHECKS.summation_report(
                [1.0],
                storage_dtype="float64",
                accumulator_dtype="float32",
            )
        with self.assertRaisesRegex(CHECKS.NumericalQualityError, "remain finite"):
            CHECKS.summation_report([1e100], storage_dtype="float32")

    def test_cli_pass_returns_zero_and_a_focused_report(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--actual",
                "[0.30000000000000004]",
                "--expected",
                "[0.3]",
                "--rtol",
                "1e-9",
                "--atol",
                "1e-12",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["decision"], {"status": "passed", "exit_code": 0})
        self.assertTrue(report["comparison"]["passed"])
        self.assertNotIn("division_demo", report)
        self.assertNotIn("summation_demo", report)

    def test_cli_mismatch_returns_one_with_diagnostics(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--actual",
                "[1.0, 2.0]",
                "--expected",
                "[1.0, 3.0]",
                "--rtol",
                "0",
                "--atol",
                "0",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["decision"], {"status": "failed", "exit_code": 1})
        self.assertEqual(report["comparison"]["mismatch_count"], 1)
        self.assertEqual(
            report["comparison"]["mismatch_examples"][0]["index"],
            [1],
        )

    def test_cli_can_write_a_failed_gate_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "quality.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--actual",
                    "[1.0]",
                    "--expected",
                    "[2.0]",
                    "--rtol",
                    "0",
                    "--atol",
                    "0",
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, "")
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["decision"]["status"], "failed")

    def test_cli_invalid_shape_returns_two_without_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--actual", "[1, 2]", "--expected", "[1]"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("shape mismatch", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
