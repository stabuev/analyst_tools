from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dtype_audit.py"
MAIN = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("dtype_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class DtypeAuditTest(unittest.TestCase):
    def test_manual_bounds_match_signed_and_unsigned_types(self) -> None:
        self.assertEqual(AUDIT.manual_integer_bounds(8, signed=True), (-128, 127))
        self.assertEqual(AUDIT.manual_integer_bounds(8, signed=False), (0, 255))

    def test_smallest_integer_dtype_uses_sign_and_expected_range(self) -> None:
        self.assertEqual(AUDIT.smallest_integer_dtype(0, 255), "uint8")
        self.assertEqual(AUDIT.smallest_integer_dtype(0, 20_000), "uint16")
        self.assertEqual(AUDIT.smallest_integer_dtype(-1, 127), "int8")
        self.assertEqual(AUDIT.smallest_integer_dtype(-500, 20_000), "int16")

    def test_planned_shape_connects_size_dtype_and_memory(self) -> None:
        report = AUDIT.audit_values(
            [0, 12, 200],
            target_dtype="uint16",
            expected_min=0,
            expected_max=20_000,
            planned_shape=(500, 365, 24),
        )
        planned_size = 500 * 365 * 24
        self.assertEqual(report["status"], "approved")
        self.assertEqual(report["planning"]["size"], planned_size)
        self.assertEqual(
            report["planning"]["source_dtype_projected_nbytes"],
            planned_size * np.asarray([0, 12, 200]).itemsize,
        )
        self.assertEqual(report["target"]["projected_nbytes"], planned_size * 2)

    def test_observed_only_recommendation_is_marked_as_warning(self) -> None:
        report = AUDIT.audit_values([0, 12, 200])
        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["recommendation"]["basis"], "observed_values")
        self.assertEqual(report["recommendation"]["smallest_integer_dtype"], "uint8")
        self.assertFalse(report["recommendation"]["production_ready"])

    def test_expected_range_can_reject_dtype_that_fits_the_sample(self) -> None:
        report = AUDIT.audit_values(
            [0, 12, 200],
            target_dtype="uint8",
            expected_min=0,
            expected_max=20_000,
        )
        self.assertEqual(report["status"], "rejected")
        self.assertIn("expected_range_fits_target", report["failed_checks"])
        self.assertNotIn("observed_range_fits_target", report["failed_checks"])

    def test_observed_out_of_range_value_is_rejected_before_cast(self) -> None:
        report = AUDIT.audit_values(
            [0, 256],
            target_dtype="uint8",
            expected_min=0,
            expected_max=255,
        )
        self.assertEqual(report["status"], "rejected")
        self.assertIn("observed_range_fits_target", report["failed_checks"])

    def test_negative_contract_rejects_unsigned_target(self) -> None:
        report = AUDIT.audit_values(
            [0, 10],
            target_dtype="uint16",
            expected_min=-1,
            expected_max=20_000,
        )
        self.assertEqual(report["status"], "rejected")
        self.assertIn("expected_range_fits_target", report["failed_checks"])

    def test_missing_values_require_an_explicit_policy(self) -> None:
        rejected = AUDIT.audit_values(
            [1, None, 3],
            target_dtype="float64",
            expected_min=0,
            expected_max=10,
        )
        self.assertEqual(rejected["status"], "rejected")
        self.assertIn("missing_policy", rejected["failed_checks"])

        approved = AUDIT.audit_values(
            [1, None, 3],
            target_dtype="float64",
            expected_min=0,
            expected_max=10,
            allow_missing=True,
        )
        self.assertEqual(approved["status"], "approved")

    def test_integer_target_cannot_represent_nan_even_when_missing_is_allowed(self) -> None:
        report = AUDIT.audit_values(
            [1, None, 3],
            target_dtype="int16",
            expected_min=0,
            expected_max=10,
            allow_missing=True,
        )
        self.assertEqual(report["status"], "rejected")
        self.assertIn("target_supports_missing_policy", report["failed_checks"])

    def test_fractional_values_are_not_silently_approved_for_integer_target(self) -> None:
        report = AUDIT.audit_values(
            [1.5, 2.0],
            target_dtype="int16",
            expected_min=0,
            expected_max=10,
        )
        self.assertEqual(report["status"], "rejected")
        self.assertIn(
            "integer_target_preserves_fractional_values",
            report["failed_checks"],
        )

    def test_float_narrowing_is_checked_against_error_budget(self) -> None:
        rejected = AUDIT.audit_values(
            [10_000_000.1],
            target_dtype="float32",
            expected_min=0,
            expected_max=20_000_000,
            max_abs_error=0.01,
        )
        self.assertEqual(rejected["status"], "rejected")
        self.assertIn("round_trip_error_within_budget", rejected["failed_checks"])

        approved = AUDIT.audit_values(
            [10_000_000.1],
            target_dtype="float32",
            expected_min=0,
            expected_max=20_000_000,
            max_abs_error=0.2,
        )
        self.assertEqual(approved["status"], "approved")

    def test_value_contract_can_pass_when_numpy_type_level_cast_is_not_safe(self) -> None:
        report = AUDIT.audit_values(
            [0, 12, 200],
            target_dtype="uint16",
            expected_min=0,
            expected_max=20_000,
        )
        self.assertEqual(report["status"], "approved")
        self.assertFalse(report["target"]["numpy_type_level_safe_cast"])

    def test_existing_unsigned_arithmetic_can_overflow(self) -> None:
        left = np.array([250], dtype=np.uint8)
        right = np.array([10], dtype=np.uint8)
        self.assertEqual((left + right).item(), 4)

    def test_invalid_contract_inputs_are_rejected(self) -> None:
        cases = (
            lambda: AUDIT.audit_values([1, 2], expected_min=0),
            lambda: AUDIT.audit_values(["1", "2"]),
            lambda: AUDIT.audit_values([[1, 2], [3]]),
            lambda: AUDIT.audit_values([1, 2], planned_shape=(2, -1)),
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(AUDIT.DtypeAuditError):
                case()

    def test_cli_prints_approved_json_report(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--values",
                "[0, 12, 200]",
                "--target-dtype",
                "uint16",
                "--expected-min",
                "0",
                "--expected-max",
                "20000",
                "--planned-shape",
                "[500, 365, 24]",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "approved")
        self.assertEqual(report["recommendation"]["smallest_integer_dtype"], "uint16")

    def test_cli_rejected_contract_returns_report_without_traceback(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--values",
                "[0, 12, 200]",
                "--target-dtype",
                "uint8",
                "--expected-min",
                "0",
                "--expected-max",
                "20000",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "rejected")

    def test_cli_invalid_json_has_clear_error_without_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--values", "[1,"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("valid JSON", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_example_runs_as_a_standalone_program(self) -> None:
        result = subprocess.run(
            [sys.executable, MAIN],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "approved")


if __name__ == "__main__":
    unittest.main()
