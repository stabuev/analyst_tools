from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "db_reader.py"
DATA = ROOT.parent / "data"
DATABASE = DATA / "tiny" / "analytics.sqlite"
CONTRACT = DATA / "db_contract.json"
SPEC = importlib.util.spec_from_file_location("db_reader", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)


class DatabaseReaderTest(unittest.TestCase):
    def test_parameterized_slice_returns_expected_rows(self) -> None:
        result = READER.read_orders(
            DATABASE,
            CONTRACT,
            min_amount=900,
            status="paid",
        )
        self.assertTrue(result["summary"]["valid"])
        self.assertEqual(
            [row["order_id"] for row in result["result"]["rows"]],
            ["O2501", "O2502", "O2505"],
        )

    def test_result_contract_and_grain_are_checked(self) -> None:
        result = READER.read_orders(DATABASE, CONTRACT)
        self.assertEqual(result["result"]["grain"], ["order_id"])
        self.assertTrue(result["checks"]["columns_match"])
        self.assertTrue(result["checks"]["grain_unique"])

    def test_values_are_not_interpolated_into_sql(self) -> None:
        result = READER.read_orders(DATABASE, CONTRACT, status="paid")
        self.assertFalse(result["query"]["literal_values_embedded"])
        self.assertIn("status", result["query"]["bind_names"])
        self.assertNotIn("'paid'", result["query"]["sql"])

    def test_injection_string_is_treated_as_a_value(self) -> None:
        malicious = "paid' OR 1=1 --"
        result = READER.read_orders(DATABASE, CONTRACT, status=malicious)
        self.assertEqual(result["result"]["rows"], [])
        with sqlite3.connect(DATABASE) as connection:
            count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        self.assertEqual(count, 5)

    def test_limit_is_bound_and_respected(self) -> None:
        result = READER.read_orders(DATABASE, CONTRACT, limit=2)
        self.assertEqual(result["summary"]["row_count"], 2)
        self.assertIn("row_limit", result["query"]["bind_names"])

    def test_schema_inspection_is_included(self) -> None:
        result = READER.read_orders(DATABASE, CONTRACT)
        names = [column["name"] for column in result["schema"]["orders"]]
        self.assertEqual(names, ["order_id", "user_id", "ordered_at", "amount", "status"])

    def test_missing_database_is_configuration_error(self) -> None:
        with self.assertRaisesRegex(READER.DatabaseReadError, "does not exist"):
            READER.read_orders(DATA / "tiny" / "missing.sqlite", CONTRACT)

    def test_cli_outputs_valid_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--database",
                DATABASE,
                "--contract",
                CONTRACT,
                "--status",
                "paid",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["summary"]["valid"])


if __name__ == "__main__":
    unittest.main()
