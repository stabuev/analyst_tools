from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "csv_audit.py"
DATA_ROOT = ROOT.parent / "data"
TINY = DATA_ROOT / "tiny"
CONTRACT = DATA_ROOT / "contract.json"
VALID = TINY / "orders_semicolon_cp1251.csv"
BROKEN = TINY / "orders_broken_cp1251.csv"
SPEC = importlib.util.spec_from_file_location("csv_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


class CsvAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = AUDITOR.audit_csv(VALID, CONTRACT)

    def audit_source(
        self,
        source: str,
        contract: dict[str, object],
    ) -> dict[str, object]:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            input_path = root / "orders.csv"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            input_path.write_text(source, encoding=str(contract["encoding"]))
            return AUDITOR.audit_csv(input_path, contract_path)

    def test_explicit_cp1251_semicolon_contract_passes(self) -> None:
        self.assertTrue(self.report["summary"]["valid"])
        self.assertEqual(self.report["encoding"]["declared"], "cp1251")
        self.assertEqual(self.report["dialect"]["delimiter"], ";")
        self.assertEqual(self.report["structure"]["data_rows"], 5)

    def test_quoted_delimiter_stays_inside_comment(self) -> None:
        preview = self.report["pandas"]["preview"]
        self.assertEqual(preview[1]["comment"], "скидка; май")
        self.assertEqual(len(preview[1]), 6)

    def test_decimal_comma_and_thousands_are_parsed_by_policy(self) -> None:
        parsed = AUDITOR.parse_decimal(
            "1 200,50",
            decimal_mark=",",
            thousands=" ",
        )
        self.assertEqual(parsed, Decimal("1200.50"))
        self.assertTrue(self.report["columns"]["amount"]["valid"])

    def test_decimal_policy_rejects_bad_grouping_and_non_finite_values(self) -> None:
        for value in ("12 00,50", "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                AUDITOR.parse_decimal(
                    value,
                    decimal_mark=",",
                    thousands=" ",
                )

    def test_invalid_decimal_token_makes_the_audit_fail(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        source = VALID.read_text(encoding=contract["encoding"])
        report = self.audit_source(
            source.replace("1 200,50", "12 00,50", 1),
            contract,
        )
        self.assertEqual(report["columns"]["amount"]["invalid_count"], 1)
        self.assertFalse(report["summary"]["valid"])

    def test_timestamp_policy_requires_an_explicit_offset(self) -> None:
        parsed = AUDITOR.parse_timestamp(
            "2026-05-01T10:15:00+03:00",
            require_timezone=True,
        )
        self.assertIsNotNone(parsed.utcoffset())
        with self.assertRaisesRegex(ValueError, "explicit UTC offset"):
            AUDITOR.parse_timestamp(
                "2026-05-01T10:15:00",
                require_timezone=True,
            )

    def test_naive_timestamp_makes_the_audit_fail(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        source = VALID.read_text(encoding=contract["encoding"])
        report = self.audit_source(
            source.replace(
                "2026-05-01T10:00:00+03:00",
                "2026-05-01T10:00:00",
                1,
            ),
            contract,
        )
        self.assertEqual(report["columns"]["ordered_at"]["invalid_count"], 1)
        self.assertFalse(report["summary"]["valid"])

    def test_null_tokens_are_not_inferred_beyond_contract(self) -> None:
        comment = self.report["columns"]["comment"]
        self.assertEqual(comment["null_count"], 2)
        self.assertTrue(comment["valid"])
        self.assertEqual(self.report["pandas"]["preview"][2]["comment"], "NULL")

    def test_global_null_policy_still_respects_column_nullability(self) -> None:
        contract = AUDITOR.load_contract(CONTRACT)
        columns = AUDITOR.inspect_columns(
            [(2, {"order_id": "NULL"})],
            contract,
        )
        self.assertFalse(columns["order_id"]["valid"])
        self.assertEqual(columns["order_id"]["invalid_count"], 1)

    def test_broken_row_width_is_visible(self) -> None:
        report = AUDITOR.audit_csv(BROKEN, CONTRACT)
        self.assertFalse(report["summary"]["valid"])
        malformed = report["structure"]["malformed_rows"]
        self.assertEqual(malformed[0]["line"], 3)
        self.assertEqual(malformed[0]["expected_fields"], 6)
        self.assertEqual(malformed[0]["actual_fields"], 7)

    def test_wrong_encoding_fails_without_replacement_characters(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["encoding"] = "utf-8"
        with TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            report = AUDITOR.audit_csv(VALID, path)
        self.assertFalse(report["encoding"]["valid"])
        self.assertIn("cannot decode byte", report["encoding"]["error"])
        self.assertFalse(report["summary"]["valid"])

    def test_missing_schema_column_is_reported(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["columns"]["source_system"] = {"type": "string", "nullable": False}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            report = AUDITOR.audit_csv(VALID, path)
        self.assertEqual(report["structure"]["missing_columns"], ["source_system"])
        self.assertFalse(report["structure"]["valid"])

    def test_row_count_policy_can_be_omitted_for_a_recurring_source(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract.pop("row_count")
        source = VALID.read_text(encoding=contract["encoding"])
        extra_row = source.splitlines()[1].replace("O2001", "O2999")
        report = self.audit_source(
            f"{source.rstrip()}\n{extra_row}\n",
            contract,
        )
        self.assertEqual(report["structure"]["data_rows"], 6)
        self.assertIsNone(report["structure"]["row_count_policy"])
        self.assertTrue(report["summary"]["valid"])

    def test_minimum_row_count_accepts_a_larger_delivery(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        contract["row_count"] = {"mode": "min", "value": 4}
        report = self.audit_source(
            VALID.read_text(encoding=contract["encoding"]),
            contract,
        )
        self.assertTrue(report["structure"]["row_count_matches"])
        self.assertTrue(report["summary"]["valid"])

    def test_exact_row_count_is_a_declared_delivery_rule(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        source = VALID.read_text(encoding=contract["encoding"])
        extra_row = source.splitlines()[1].replace("O2001", "O2999")
        report = self.audit_source(
            f"{source.rstrip()}\n{extra_row}\n",
            contract,
        )
        self.assertFalse(report["structure"]["row_count_matches"])
        self.assertFalse(report["summary"]["valid"])

    def test_cli_returns_json_for_valid_file(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                VALID,
                "--contract",
                CONTRACT,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["summary"]["valid"])

    def test_cli_is_quality_gate_for_broken_file(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                BROKEN,
                "--contract",
                CONTRACT,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(json.loads(result.stdout)["summary"]["valid"])


if __name__ == "__main__":
    unittest.main()
