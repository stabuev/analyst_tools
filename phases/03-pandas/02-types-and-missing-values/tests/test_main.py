from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dtype_audit.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("dtype_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class DtypeAuditTest(unittest.TestCase):
    def test_string_target_uses_pandas_string_dtype(self) -> None:
        result = AUDIT.convert_series(pd.Series(["a", None]), "string")
        self.assertEqual(str(result.dtype), "string")
        self.assertTrue(pd.isna(result.iloc[1]))

    def test_nullable_integer_preserves_missing_value(self) -> None:
        result = AUDIT.convert_series(pd.Series(["1", None]), "Int64")
        self.assertEqual(str(result.dtype), "Int64")
        self.assertTrue(pd.isna(result.iloc[1]))

    def test_fractional_value_is_not_silently_truncated(self) -> None:
        with self.assertRaisesRegex(AUDIT.DtypeContractError, "truncate"):
            AUDIT.convert_series(pd.Series(["1.5"]), "Int64")

    def test_invalid_number_is_rejected(self) -> None:
        with self.assertRaisesRegex(AUDIT.DtypeContractError, "cannot parse"):
            AUDIT.convert_series(pd.Series(["oops"]), "Float64")

    def test_nullable_boolean_has_explicit_semantics(self) -> None:
        result = AUDIT.convert_series(pd.Series(["true", "NO", None]), "boolean")
        self.assertEqual(result.tolist()[:2], [True, False])
        self.assertTrue(pd.isna(result.iloc[2]))

    def test_mixed_offsets_are_normalized_to_utc(self) -> None:
        result = AUDIT.convert_series(
            pd.Series(["2026-01-01T10:00:00+03:00", "2026-01-01T07:00:00Z"]),
            "datetime_utc",
        )
        self.assertEqual(result.iloc[0], result.iloc[1])
        self.assertEqual(str(result.dtype), "datetime64[us, UTC]")

    def test_audit_reports_before_and_after_dtypes(self) -> None:
        frame = pd.DataFrame({"amount": ["1.5", None]}, dtype="string")
        converted, report = AUDIT.audit_and_convert(frame, {"amount": "Float64"})
        self.assertEqual(str(converted["amount"].dtype), "Float64")
        self.assertEqual(report["columns"]["amount"]["source_dtype"], "string")

    def test_cli_returns_structured_report(self) -> None:
        schema = json.dumps({"order_id": "string", "amount": "Float64"})
        result = subprocess.run(
            [sys.executable, ARTIFACT, DATA, "--schema", schema],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["rows"], 7)


if __name__ == "__main__":
    unittest.main()
