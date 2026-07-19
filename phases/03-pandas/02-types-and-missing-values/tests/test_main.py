from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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
    def test_schema_requires_dtype_and_nullable_policy(self) -> None:
        with self.assertRaisesRegex(AUDIT.DtypeContractError, "dtype and nullable"):
            AUDIT.validate_schema({"amount": "Float64"})

        with self.assertRaisesRegex(AUDIT.DtypeContractError, "true or false"):
            AUDIT.validate_schema(
                {"amount": {"dtype": "Float64", "nullable": "yes"}}
            )

    def test_string_contract_preserves_identifier_and_missing_value(self) -> None:
        converted, report = AUDIT.convert_series(
            pd.Series(["0007", None]),
            target="string",
            nullable=True,
        )

        self.assertEqual(str(converted.dtype), "string")
        values = converted.tolist()
        self.assertEqual(values[0], "0007")
        self.assertTrue(pd.isna(values[1]))
        self.assertTrue(report["valid"])

    def test_nullable_integer_preserves_missing_value(self) -> None:
        converted, report = AUDIT.convert_series(
            pd.Series(["1", ""]),
            target="Int64",
            nullable=True,
        )

        self.assertEqual(str(converted.dtype), "Int64")
        values = converted.tolist()
        self.assertEqual(values[0], 1)
        self.assertTrue(pd.isna(values[1]))
        self.assertEqual(report["missing_rows"], 1)
        self.assertTrue(report["valid"])

    def test_fractional_value_is_reported_instead_of_truncated(self) -> None:
        converted, report = AUDIT.convert_series(
            pd.Series(["1.5"]),
            target="Int64",
            nullable=False,
        )

        self.assertTrue(pd.isna(converted.tolist()[0]))
        self.assertEqual(report["invalid_rows"], 1)
        self.assertEqual(report["invalid_examples"], [{"row": "0", "value": "1.5"}])
        self.assertFalse(report["valid"])

    def test_integer_boundaries_and_exact_decimal_spelling_are_preserved(self) -> None:
        converted, report = AUDIT.convert_series(
            pd.Series(
                [
                    str(-(2**63)),
                    str(2**63 - 1),
                    "9007199254740993.0",
                ]
            ),
            target="Int64",
            nullable=False,
        )

        self.assertEqual(
            converted.tolist(),
            [-(2**63), 2**63 - 1, 9007199254740993],
        )
        self.assertTrue(report["valid"])

    def test_integer_overflow_is_reported_instead_of_wrapped(self) -> None:
        source = pd.Series(
            [str(-(2**63) - 1), str(2**63), str(2**64 - 1), "1e100"]
        )
        converted, report = AUDIT.convert_series(
            source,
            target="Int64",
            nullable=False,
        )

        self.assertTrue(all(pd.isna(value) for value in converted.tolist()))
        self.assertEqual(report["invalid_rows"], 4)
        self.assertEqual(
            report["invalid_examples"],
            [
                {"row": "0", "value": str(-(2**63) - 1)},
                {"row": "1", "value": str(2**63)},
                {"row": "2", "value": str(2**64 - 1)},
                {"row": "3", "value": "1e100"},
            ],
        )
        self.assertFalse(report["valid"])

    def test_invalid_number_is_distinct_from_allowed_missing_value(self) -> None:
        converted, report = AUDIT.convert_series(
            pd.Series(["12.5", "", "oops"], index=[10, 11, 12]),
            target="Float64",
            nullable=True,
        )

        values = converted.tolist()
        self.assertEqual(values[0], 12.5)
        self.assertTrue(pd.isna(values[1]))
        self.assertTrue(pd.isna(values[2]))
        self.assertEqual(report["missing_rows"], 1)
        self.assertEqual(report["missing_examples"], [{"row": "11", "value": ""}])
        self.assertEqual(report["invalid_rows"], 1)
        self.assertEqual(
            report["invalid_examples"],
            [{"row": "12", "value": "oops"}],
        )
        self.assertFalse(report["valid"])

    def test_non_finite_float_is_invalid(self) -> None:
        converted, report = AUDIT.convert_series(
            pd.Series(["12.5", "inf", "-inf", "1e309"]),
            target="Float64",
            nullable=False,
        )

        values = converted.tolist()
        self.assertEqual(values[0], 12.5)
        self.assertTrue(all(pd.isna(value) for value in values[1:]))
        self.assertEqual(report["invalid_rows"], 3)
        self.assertEqual(
            report["invalid_examples"],
            [
                {"row": "1", "value": "inf"},
                {"row": "2", "value": "-inf"},
                {"row": "3", "value": "1e309"},
            ],
        )
        self.assertFalse(report["valid"])

    def test_missing_value_violates_non_nullable_contract(self) -> None:
        _, report = AUDIT.convert_series(
            pd.Series(["O1001", "  "]),
            target="string",
            nullable=False,
        )

        self.assertEqual(report["missing_rows"], 1)
        self.assertEqual(report["missing_examples"], [{"row": "1", "value": "  "}])
        self.assertEqual(report["violations"], ["missing_not_allowed"])
        self.assertFalse(report["valid"])

    def test_evidence_lists_are_limited_to_five_rows(self) -> None:
        _, missing_report = AUDIT.convert_series(
            pd.Series([""] * 6),
            target="string",
            nullable=False,
        )
        _, invalid_report = AUDIT.convert_series(
            pd.Series(["not-a-number"] * 6),
            target="Float64",
            nullable=True,
        )

        self.assertEqual(len(missing_report["missing_examples"]), 5)
        self.assertEqual(len(invalid_report["invalid_examples"]), 5)

    def test_boolean_contract_accepts_only_declared_tokens(self) -> None:
        converted, report = AUDIT.convert_series(
            pd.Series(["true", "NO", "", "perhaps"]),
            target="boolean",
            nullable=True,
        )

        self.assertEqual(converted.tolist()[:2], [True, False])
        values = converted.tolist()
        self.assertTrue(pd.isna(values[2]))
        self.assertTrue(pd.isna(values[3]))
        self.assertEqual(report["missing_rows"], 1)
        self.assertEqual(report["invalid_rows"], 1)
        self.assertFalse(report["valid"])

    def test_audit_converts_valid_columns_to_declared_dtypes(self) -> None:
        frame = pd.DataFrame(
            {"order_id": ["O1", "O2"], "amount": ["10.5", ""]},
            dtype="string",
        )
        schema = {
            "order_id": {"dtype": "string", "nullable": False},
            "amount": {"dtype": "Float64", "nullable": True},
        }

        converted, report = AUDIT.audit_and_convert(frame, schema)

        self.assertTrue(report["valid"])
        self.assertEqual(str(converted["order_id"].dtype), "string")
        self.assertEqual(str(converted["amount"].dtype), "Float64")

    def test_missing_schema_column_is_a_data_violation(self) -> None:
        frame = pd.DataFrame({"order_id": ["O1"]})
        schema = {
            "amount": {"dtype": "Float64", "nullable": True},
        }

        _, report = AUDIT.audit_and_convert(frame, schema)

        self.assertFalse(report["valid"])
        self.assertEqual(report["missing_columns"], ["amount"])

    def test_cli_returns_zero_and_structured_report_for_valid_data(self) -> None:
        schema = json.dumps(
            {
                "order_id": {"dtype": "string", "nullable": False},
                "amount": {"dtype": "Float64", "nullable": True},
            }
        )
        result = subprocess.run(
            [sys.executable, ARTIFACT, DATA, "--schema", schema],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["valid"])
        self.assertEqual(report["rows"], 7)
        self.assertEqual(report["columns"]["amount"]["missing_rows"], 1)

    def test_cli_returns_one_and_keeps_evidence_for_data_violation(self) -> None:
        schema = json.dumps(
            {
                "order_id": {"dtype": "string", "nullable": False},
                "amount": {"dtype": "Float64", "nullable": True},
            }
        )
        with TemporaryDirectory() as directory:
            input_path = Path(directory) / "broken.csv"
            input_path.write_text(
                "order_id,amount\n,10\nO2,oops\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, ARTIFACT, input_path, "--schema", schema],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["valid"])
        self.assertEqual(
            report["columns"]["order_id"]["violations"],
            ["missing_not_allowed"],
        )
        self.assertEqual(
            report["columns"]["order_id"]["missing_examples"],
            [{"row": "0", "value": ""}],
        )
        self.assertEqual(
            report["columns"]["amount"]["invalid_examples"],
            [{"row": "1", "value": "oops"}],
        )

    def test_cli_returns_two_for_invalid_schema(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, DATA, "--schema", '{"amount":"Float64"}'],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("dtype and nullable", result.stderr)


if __name__ == "__main__":
    unittest.main()
