from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "select_contract.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("select_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SELECT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECT)


class SelectContractTest(unittest.TestCase):
    def test_rub_projection_matches_control_rows(self) -> None:
        report = SELECT.run_select(DATA)
        self.assertEqual([row["order_id"] for row in report["rows"]], ["O1005", "O1001"])
        self.assertEqual([row["amount_with_fee"] for row in report["rows"]], [1575.0, 1260.0])

    def test_result_contract_is_explicit(self) -> None:
        report = SELECT.run_select(DATA)
        self.assertEqual(report["contract"]["grain"], ["order_id"])
        self.assertEqual(report["contract"]["columns"], SELECT.RESULT_COLUMNS)
        self.assertTrue(report["valid"])

    def test_paid_filter_excludes_refund(self) -> None:
        report = SELECT.run_select(DATA, currency="RUB", min_amount=Decimal("0"))
        self.assertNotIn("O1002", [row["order_id"] for row in report["rows"]])

    def test_currency_parameter_is_case_insensitive(self) -> None:
        report = SELECT.run_select(DATA, currency="eur", min_amount=Decimal("100"))
        self.assertEqual([row["order_id"] for row in report["rows"]], ["O1009", "O1012"])

    def test_missing_amount_does_not_pass_filter(self) -> None:
        report = SELECT.run_select(DATA, currency="USD", min_amount=Decimal("0"))
        self.assertNotIn("O1004", [row["order_id"] for row in report["rows"]])

    def test_parameters_are_not_sql_source(self) -> None:
        report = SELECT.run_select(DATA, currency="RUB' OR TRUE --")
        self.assertEqual(report["row_count"], 0)

    def test_negative_boundary_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative"):
            SELECT.run_select(DATA, min_amount=Decimal("-1"))

    def test_cli_prints_json(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--orders", DATA, "--currency", "RUB"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["row_count"], 2)


if __name__ == "__main__":
    unittest.main()
