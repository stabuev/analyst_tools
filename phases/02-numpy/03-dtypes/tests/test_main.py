from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dtype_audit.py"
SPEC = importlib.util.spec_from_file_location("dtype_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class DtypeAuditTest(unittest.TestCase):
    def test_manual_bounds_match_common_integer_types(self) -> None:
        self.assertEqual(AUDIT.manual_integer_bounds(8, signed=True), (-128, 127))
        self.assertEqual(AUDIT.manual_integer_bounds(8, signed=False), (0, 255))

    def test_smallest_integer_dtype_respects_sign_and_range(self) -> None:
        self.assertEqual(AUDIT.smallest_integer_dtype(0, 255), "uint8")
        self.assertEqual(AUDIT.smallest_integer_dtype(-1, 127), "int8")
        self.assertEqual(AUDIT.smallest_integer_dtype(-129, 128), "int16")

    def test_audit_reports_memory_and_limits(self) -> None:
        report = AUDIT.audit_values([[0, 12], [200, 255]], dtype="uint8")
        self.assertEqual(report["shape"], [2, 2])
        self.assertEqual(report["itemsize_bytes"], 1)
        self.assertEqual(report["nbytes"], 4)
        self.assertEqual(report["limits"]["max"], 255)
        self.assertTrue(report["limits"]["manual_bounds_match"])

    def test_missing_values_require_floating_representation(self) -> None:
        report = AUDIT.audit_values([1, None, 3])
        self.assertEqual(report["missing_count"], 1)
        self.assertEqual(report["dtype"], "float64")
        self.assertFalse(report["integer_recommendation_usable"])

    def test_out_of_range_requested_dtype_is_rejected(self) -> None:
        with self.assertRaises(AUDIT.DtypeAuditError):
            AUDIT.audit_values([0, 256], dtype="uint8")

    def test_non_numeric_dtype_is_rejected(self) -> None:
        with self.assertRaisesRegex(AUDIT.DtypeAuditError, "numeric"):
            AUDIT.audit_values(["1", "2"])

    def test_cli_prints_json_report(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--values", "[0, 12, 255]", "--dtype", "uint8"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["smallest_integer_dtype"], "uint8")

    def test_cli_failure_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--values", "[0, 256]", "--dtype", "uint8"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
