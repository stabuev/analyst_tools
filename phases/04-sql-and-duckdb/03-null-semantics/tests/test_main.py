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
SPEC = importlib.util.spec_from_file_location("null_lesson", CODE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {CODE}")
LESSON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LESSON)


class NullSemanticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        LESSON.prepare_orders(self.connection, DATA)
        self.contract = LESSON.load_contract()

    def tearDown(self) -> None:
        self.connection.close()

    def execute(self):
        return LESSON.execute_audit(self.connection)

    def test_sql_result_matches_complete_manual_table(self) -> None:
        report = LESSON.run_example(DATA)
        self.assertTrue(report["matches_manual"])
        self.assertEqual(
            report["state_order_ids"],
            {
                "above_threshold": [
                    "O1001",
                    "O1002",
                    "O1005",
                    "O1007",
                    "O1009",
                    "O1012",
                ],
                "at_or_below_threshold": [
                    "O1003",
                    "O1006",
                    "O1010",
                    "O1011",
                ],
                "missing": ["O1004", "O1008"],
            },
        )

    def test_columns_types_grain_and_order_match_contract(self) -> None:
        columns, types, rows = self.execute()
        LESSON.validate_result(columns, types, rows, self.contract)
        self.assertEqual(
            columns,
            [
                "order_id",
                "amount",
                "amount_above_threshold",
                "amount_not_above_threshold",
                "amount_is_missing",
                "amount_state",
            ],
        )
        self.assertEqual(
            types,
            [
                "VARCHAR",
                "DECIMAL(18,2)",
                "BOOLEAN",
                "BOOLEAN",
                "BOOLEAN",
                "VARCHAR",
            ],
        )

    def test_and_truth_table_has_all_nine_combinations(self) -> None:
        expected = {
            (True, True): True,
            (True, False): False,
            (True, None): None,
            (False, True): False,
            (False, False): False,
            (False, None): False,
            (None, True): None,
            (None, False): False,
            (None, None): None,
        }
        for operands, expected_result in expected.items():
            with self.subTest(operands=operands):
                actual = self.connection.execute(
                    "SELECT CAST(? AS BOOLEAN) AND CAST(? AS BOOLEAN)",
                    list(operands),
                ).fetchone()[0]
                self.assertEqual(actual, expected_result)

    def test_or_truth_table_has_all_nine_combinations(self) -> None:
        expected = {
            (True, True): True,
            (True, False): True,
            (True, None): True,
            (False, True): True,
            (False, False): False,
            (False, None): None,
            (None, True): True,
            (None, False): None,
            (None, None): None,
        }
        for operands, expected_result in expected.items():
            with self.subTest(operands=operands):
                actual = self.connection.execute(
                    "SELECT CAST(? AS BOOLEAN) OR CAST(? AS BOOLEAN)",
                    list(operands),
                ).fetchone()[0]
                self.assertEqual(actual, expected_result)

    def test_not_unknown_stays_unknown(self) -> None:
        self.assertIsNone(
            self.connection.execute("SELECT NOT NULL::BOOLEAN").fetchone()[0]
        )

    def test_null_equality_is_unknown_but_is_null_is_true(self) -> None:
        equality, missing_check = self.connection.execute(
            "SELECT NULL = NULL, NULL IS NULL"
        ).fetchone()
        self.assertIsNone(equality)
        self.assertTrue(missing_check)

    def test_where_keeps_true_but_drops_false_and_unknown(self) -> None:
        self.connection.execute(
            """
            CREATE TEMP TABLE logic_values(label VARCHAR, decision BOOLEAN);
            INSERT INTO logic_values VALUES
                ('true', TRUE),
                ('false', FALSE),
                ('unknown', NULL);
            """
        )
        rows = self.connection.execute(
            "SELECT label FROM logic_values WHERE decision"
        ).fetchall()
        self.assertEqual(rows, [("true",)])

    def test_direct_and_negated_filters_leave_missing_rows_uncovered(self) -> None:
        above = {
            row[0]
            for row in self.connection.execute(
                "SELECT order_id FROM orders WHERE amount > 100"
            ).fetchall()
        }
        not_above = {
            row[0]
            for row in self.connection.execute(
                "SELECT order_id FROM orders WHERE NOT (amount > 100)"
            ).fetchall()
        }
        missing = {
            row[0]
            for row in self.connection.execute(
                "SELECT order_id FROM orders WHERE amount IS NULL"
            ).fetchall()
        }
        self.assertEqual(missing, {"O1004", "O1008"})
        self.assertTrue(above.isdisjoint(not_above))
        self.assertTrue((above | not_above).isdisjoint(missing))
        self.assertEqual(len(above | not_above | missing), 12)

    def test_missing_amount_keeps_unknown_and_explicit_missing_state(self) -> None:
        columns, _, rows = self.execute()
        result = LESSON.rows_as_dicts(columns, rows)
        missing_rows = [
            row for row in result if row["amount_state"] == "missing"
        ]
        self.assertEqual(
            [row["order_id"] for row in missing_rows],
            ["O1004", "O1008"],
        )
        for row in missing_rows:
            self.assertIsNone(row["amount_above_threshold"])
            self.assertIsNone(row["amount_not_above_threshold"])
            self.assertTrue(row["amount_is_missing"])

    def test_threshold_boundary_is_not_above_for_strict_comparison(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O1100', 'U001', '2026-04-10T00:00:00Z', 'paid', 'RUB', 100.00)
            """
        )
        columns, types, rows = self.execute()
        LESSON.validate_result(columns, types, rows, self.contract)
        result = {
            row["order_id"]: row
            for row in LESSON.rows_as_dicts(columns, rows)
        }
        self.assertEqual(
            (
                result["O1100"]["amount_above_threshold"],
                result["O1100"]["amount_not_above_threshold"],
                result["O1100"]["amount_state"],
            ),
            (False, True, "at_or_below_threshold"),
        )

    def test_case_does_not_misclassify_new_missing_amount_as_regular(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O1999', 'U001', '2026-04-10T00:00:00Z', 'paid', 'RUB', NULL)
            """
        )
        columns, types, rows = self.execute()
        LESSON.validate_result(columns, types, rows, self.contract)
        result = {
            row["order_id"]: row
            for row in LESSON.rows_as_dicts(columns, rows)
        }
        self.assertEqual(result["O1999"]["amount_state"], "missing")

    def test_coalesce_resolves_unknown_only_when_policy_requests_it(self) -> None:
        raw, resolved = self.connection.execute(
            """
            SELECT
                amount > 100,
                coalesce(amount > 100, FALSE)
            FROM orders
            WHERE order_id = 'O1004'
            """
        ).fetchone()
        self.assertIsNone(raw)
        self.assertFalse(resolved)

    def test_amount_remains_decimal_not_float(self) -> None:
        columns, types, rows = self.execute()
        amount_position = columns.index("amount")
        self.assertEqual(types[amount_position], "DECIMAL(18,2)")
        known_amounts = [
            row[amount_position]
            for row in rows
            if row[amount_position] is not None
        ]
        self.assertTrue(all(isinstance(amount, Decimal) for amount in known_amounts))

    def test_explicit_projection_survives_source_schema_growth(self) -> None:
        self.connection.execute("ALTER TABLE orders ADD COLUMN internal_note VARCHAR")
        self.connection.execute("UPDATE orders SET internal_note = 'not for consumers'")
        columns, types, rows = self.execute()
        LESSON.validate_result(columns, types, rows, self.contract)
        self.assertNotIn("internal_note", columns)

    def test_duplicate_source_key_breaks_grain_contract(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders
            SELECT *
            FROM orders
            WHERE order_id = 'O1001'
            """
        )
        with self.assertRaisesRegex(ValueError, "input grain violation"):
            LESSON.validate_input(self.connection, self.contract)

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
        self.assertEqual(payload["state_order_ids"]["missing"], ["O1004", "O1008"])


if __name__ == "__main__":
    unittest.main()
