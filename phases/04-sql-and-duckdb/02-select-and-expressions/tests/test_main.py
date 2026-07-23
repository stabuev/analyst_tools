from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code" / "main.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("select_lesson", CODE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {CODE}")
LESSON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LESSON)


class SelectContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        LESSON.prepare_orders(self.connection, DATA)
        self.contract = LESSON.load_contract()

    def tearDown(self) -> None:
        self.connection.close()

    def execute(self):
        return LESSON.execute_select(self.connection)

    def test_sql_result_matches_complete_manual_table(self) -> None:
        report = LESSON.run_example(DATA)
        self.assertTrue(report["matches_manual"])
        self.assertEqual(
            [row["order_id"] for row in report["sql_result"]],
            ["O1005", "O1001"],
        )
        self.assertEqual(
            [row["amount_with_fee"] for row in report["sql_result"]],
            ["1575.00", "1260.00"],
        )

    def test_columns_and_types_match_contract(self) -> None:
        columns, types, rows = self.execute()
        LESSON.validate_result(columns, types, rows, self.contract)
        self.assertEqual(
            columns,
            [
                "order_id",
                "user_id",
                "currency",
                "amount",
                "amount_with_fee",
                "amount_band",
            ],
        )
        self.assertEqual(
            types,
            [
                "VARCHAR",
                "VARCHAR",
                "VARCHAR",
                "DECIMAL(18,2)",
                "DECIMAL(18,2)",
                "VARCHAR",
            ],
        )

    def test_case_uses_exact_boundary(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O1299', 'U001', '2026-04-10T00:00:00Z', 'paid', 'RUB', 1299.99),
                ('O1300', 'U001', '2026-04-11T00:00:00Z', 'paid', 'RUB', 1300.00)
            """
        )
        columns, types, rows = self.execute()
        LESSON.validate_result(columns, types, rows, self.contract)
        result = LESSON.rows_as_dicts(columns, rows)
        bands = {row["order_id"]: row["amount_band"] for row in result}
        self.assertEqual(bands["O1299"], "regular")
        self.assertEqual(bands["O1300"], "large")

    def test_order_uses_order_id_as_tie_breaker(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O1000', 'U001', '2026-04-10T00:00:00Z', 'paid', 'RUB', 1500.00)
            """
        )
        columns, types, rows = self.execute()
        LESSON.validate_result(columns, types, rows, self.contract)
        result = LESSON.rows_as_dicts(columns, rows)
        self.assertEqual(
            [row["order_id"] for row in result],
            ["O1000", "O1005", "O1001"],
        )

    def test_explicit_projection_survives_source_schema_growth(self) -> None:
        self.connection.execute("ALTER TABLE orders ADD COLUMN internal_note VARCHAR")
        self.connection.execute("UPDATE orders SET internal_note = 'not for consumers'")
        columns, types, rows = self.execute()
        LESSON.validate_result(columns, types, rows, self.contract)
        self.assertNotIn("internal_note", columns)

    def test_duplicate_source_key_breaks_output_grain_contract(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders
            SELECT *
            FROM orders
            WHERE order_id = 'O1001'
            """
        )
        columns, types, rows = self.execute()
        with self.assertRaisesRegex(ValueError, "output grain violation"):
            LESSON.validate_result(columns, types, rows, self.contract)

    def test_missing_amount_in_selected_population_breaks_input_contract(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O1999', 'U001', '2026-04-10T00:00:00Z', 'paid', 'RUB', NULL)
            """
        )
        with self.assertRaisesRegex(ValueError, "require amount"):
            LESSON.validate_input(self.connection, self.contract)

    def test_decimal_expression_does_not_round_through_float(self) -> None:
        columns, _, rows = self.execute()
        amount_with_fee_position = columns.index("amount_with_fee")
        self.assertEqual(
            [row[amount_with_fee_position] for row in rows],
            [Decimal("1575.00"), Decimal("1260.00")],
        )

    def test_reference_runner_prints_verified_json(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=False,
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["matches_manual"])
        self.assertEqual(payload["contract"]["grain"], ["order_id"])


if __name__ == "__main__":
    unittest.main()
