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
QUERY = ROOT / "outputs" / "currency_aggregate_audit.sql"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("aggregation_lesson", CODE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {CODE}")
LESSON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LESSON)


class CurrencyAggregateAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        LESSON.prepare_orders(self.connection, DATA)
        self.contract = LESSON.load_contract()

    def tearDown(self) -> None:
        self.connection.close()

    def execute(self):
        columns, types, rows = LESSON.execute_audit(self.connection)
        LESSON.validate_result(
            self.connection,
            columns,
            types,
            rows,
            self.contract,
        )
        return columns, types, rows

    def rows_by_currency(self):
        columns, _, rows = self.execute()
        result = {
            row[columns.index("currency")]: row
            for row in rows
        }
        return columns, result

    def test_sql_matches_complete_manual_table_per_currency(self) -> None:
        columns, _, rows = self.execute()
        self.assertEqual(
            LESSON.rows_as_dicts(columns, rows),
            self.contract["expected_on_tiny"],
        )

    def test_columns_types_grain_and_order_match_contract(self) -> None:
        columns, types, rows = self.execute()
        self.assertEqual(
            columns,
            [item["name"] for item in self.contract["output"]["columns"]],
        )
        self.assertEqual(
            types,
            [item["type"] for item in self.contract["output"]["columns"]],
        )
        self.assertEqual([row[0] for row in rows], ["EUR", "KZT", "RUB", "USD"])

    def test_grouped_denominators_reconcile_to_source(self) -> None:
        report = LESSON.run_example(DATA)
        checks = report["checks"]
        self.assertEqual(checks["source_order_rows"], 12)
        self.assertEqual(checks["grouped_order_rows"], 12)
        self.assertEqual(checks["source_known_amount_rows"], 10)
        self.assertEqual(checks["grouped_known_amount_rows"], 10)
        self.assertEqual(checks["source_paid_order_rows"], 9)
        self.assertEqual(checks["grouped_paid_order_rows"], 9)
        self.assertEqual(checks["source_paid_known_amount_rows"], 9)
        self.assertEqual(checks["grouped_paid_known_amount_rows"], 9)

    def test_count_star_and_count_amount_keep_different_denominators(self) -> None:
        columns, rows = self.rows_by_currency()
        usd = rows["USD"]
        self.assertEqual(usd[columns.index("order_rows")], 4)
        self.assertEqual(usd[columns.index("known_amount_rows")], 3)

    def test_average_uses_known_paid_amount_denominator(self) -> None:
        columns, rows = self.rows_by_currency()
        eur = rows["EUR"]
        revenue = eur[columns.index("known_paid_revenue")]
        denominator = eur[columns.index("paid_known_amount_rows")]
        average = eur[columns.index("average_known_paid_amount")]
        self.assertEqual(revenue, Decimal("1625.00"))
        self.assertEqual(denominator, 3)
        self.assertAlmostEqual(average, float(revenue) / denominator)

    def test_partial_paid_amount_keeps_known_sum_and_exposes_missing_row(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O1999', 'U001', NULL, 'paid', 'RUB', NULL)
            """
        )
        columns, rows = self.rows_by_currency()
        rub = rows["RUB"]
        self.assertEqual(rub[columns.index("paid_order_rows")], 3)
        self.assertEqual(rub[columns.index("paid_known_amount_rows")], 2)
        self.assertEqual(rub[columns.index("paid_missing_amount_rows")], 1)
        self.assertFalse(rub[columns.index("paid_amount_complete")])
        self.assertEqual(
            rub[columns.index("known_paid_revenue")],
            Decimal("2700.00"),
        )
        self.assertEqual(
            rub[columns.index("average_known_paid_amount")],
            1350.0,
        )

    def test_all_unknown_paid_amount_keeps_sum_and_average_null(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O2000', 'U001', NULL, 'paid', 'CAD', NULL)
            """
        )
        columns, rows = self.rows_by_currency()
        cad = rows["CAD"]
        self.assertEqual(cad[columns.index("order_rows")], 1)
        self.assertEqual(cad[columns.index("paid_order_rows")], 1)
        self.assertEqual(cad[columns.index("paid_known_amount_rows")], 0)
        self.assertEqual(cad[columns.index("paid_missing_amount_rows")], 1)
        self.assertFalse(cad[columns.index("paid_amount_complete")])
        self.assertIsNone(cad[columns.index("known_paid_revenue")])
        self.assertIsNone(cad[columns.index("average_known_paid_amount")])

    def test_null_currency_is_preserved_as_auditable_group(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O2001', 'U001', NULL, 'paid', NULL, 100.00)
            """
        )
        columns, _, rows = self.execute()
        self.assertIsNone(rows[-1][columns.index("currency")])
        null_row = rows[-1]
        self.assertEqual(null_row[columns.index("order_rows")], 1)
        self.assertEqual(
            null_row[columns.index("known_paid_revenue")],
            Decimal("100.00"),
        )

    def test_filter_keeps_full_group_where_changes_population(self) -> None:
        columns, rows = self.rows_by_currency()
        rub = rows["RUB"]
        self.assertEqual(rub[columns.index("order_rows")], 3)
        self.assertEqual(rub[columns.index("paid_order_rows")], 2)

        paid_only_rows = self.connection.execute(
            """
            SELECT count(*)
            FROM orders
            WHERE status = 'paid' AND currency = 'RUB'
            """
        ).fetchone()[0]
        self.assertEqual(paid_only_rows, 2)

    def test_having_filters_built_groups_not_source_rows(self) -> None:
        rows = self.connection.execute(
            """
            SELECT currency
            FROM orders
            GROUP BY currency
            HAVING count(*) FILTER (WHERE status = 'paid') >= 3
            ORDER BY currency
            """
        ).fetchall()
        self.assertEqual(rows, [("EUR",), ("USD",)])

    def test_unknown_filter_condition_does_not_enter_paid_aggregate(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O2002', 'U001', NULL, NULL, 'USD', 100.00)
            """
        )
        columns, rows = self.rows_by_currency()
        usd = rows["USD"]
        self.assertEqual(usd[columns.index("order_rows")], 5)
        self.assertEqual(usd[columns.index("paid_order_rows")], 3)

    def test_money_stays_decimal_instead_of_python_float(self) -> None:
        columns, types, rows = self.execute()
        position = columns.index("known_paid_revenue")
        self.assertEqual(types[position], "DECIMAL(38,2)")
        known_values = [row[position] for row in rows if row[position] is not None]
        self.assertTrue(all(isinstance(value, Decimal) for value in known_values))

    def test_contract_forbids_cross_currency_money_total(self) -> None:
        self.assertFalse(
            self.contract["policies"]["money"]["cross_currency_sum_allowed"]
        )
        self.assertNotIn("5005", json.dumps(self.contract))
        report = LESSON.run_example(DATA)
        self.assertFalse(
            report["checks"]["cross_currency_money_total_published"]
        )
        self.assertNotIn("paid_revenue_total", report["checks"])

    def test_sql_artifact_uses_typed_relation_without_future_mechanisms(self) -> None:
        query = QUERY.read_text(encoding="utf-8").lower()
        self.assertNotIn("read_csv", query)
        self.assertNotIn("with ", query)
        self.assertIn("from orders", query)
        self.assertIn("group by currency", query)

    def test_duplicate_input_order_id_breaks_grain_contract(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O1001', 'U001', NULL, 'paid', 'RUB', 10.00)
            """
        )
        with self.assertRaisesRegex(ValueError, "input grain violation"):
            LESSON.validate_input(self.connection, self.contract)

    def test_wrong_amount_type_breaks_input_contract(self) -> None:
        connection = duckdb.connect()
        try:
            connection.execute(
                """
                CREATE TABLE orders (
                    order_id VARCHAR,
                    status VARCHAR,
                    currency VARCHAR,
                    amount DOUBLE
                );
                INSERT INTO orders VALUES ('O1', 'paid', 'RUB', 100.0);
                """
            )
            with self.assertRaisesRegex(ValueError, "input type mismatch"):
                LESSON.validate_input(connection, self.contract)
        finally:
            connection.close()

    def test_reference_runner_prints_checked_json_without_cli_arguments(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["checks"]["matches_manual_table"])
        self.assertEqual(report["output_grain"], ["currency"])


if __name__ == "__main__":
    unittest.main()
