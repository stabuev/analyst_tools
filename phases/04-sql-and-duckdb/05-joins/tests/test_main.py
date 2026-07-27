from __future__ import annotations

import importlib.util
import json
import unittest
from decimal import Decimal
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code" / "main.py"
MART_QUERY = ROOT / "outputs" / "safe_order_mart.sql"
ITEM_TOTALS_QUERY = ROOT / "outputs" / "item_totals.sql"
ARTIFACT = ROOT / "outputs" / "artifact.json"
LESSON = ROOT / "lesson.json"
QUIZ = ROOT / "quiz.json"
SPEC = importlib.util.spec_from_file_location("join_lesson", CODE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {CODE}")
JOIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(JOIN)


class SafeJoinTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        JOIN.prepare_relations(self.connection)
        JOIN.validate_input(self.connection)
        JOIN.prepare_item_totals(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def safe_mart(self):
        columns, types, rows = JOIN.execute_safe_mart(self.connection)
        JOIN.validate_safe_mart(self.connection, columns, types, rows)
        return columns, types, rows

    def rows_by_order(self):
        columns, _, rows = self.safe_mart()
        return columns, {row[columns.index("order_id")]: row for row in rows}

    def test_item_preaggregation_returns_one_row_per_order(self) -> None:
        rows = self.connection.execute(
            """
            SELECT
                order_id,
                item_rows,
                known_item_amount_rows,
                item_total,
                item_amount_complete
            FROM item_totals
            ORDER BY order_id
            """
        ).fetchall()
        self.assertEqual(len(rows), 12)
        self.assertEqual(
            rows[0],
            ("O1001", 2, 2, Decimal("1200.00"), True),
        )
        self.assertEqual(
            rows[4],
            ("O1005", 2, 2, Decimal("1500.00"), True),
        )

    def test_safe_mart_preserves_order_grain_schema_and_types(self) -> None:
        columns, types, rows = self.safe_mart()
        self.assertEqual(columns, JOIN.EXPECTED_COLUMNS)
        self.assertEqual(types, JOIN.EXPECTED_TYPES)
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({row[0] for row in rows}), 12)

    def test_missing_amount_is_not_silently_called_a_match(self) -> None:
        columns, rows = self.rows_by_order()
        state = columns.index("amount_reconciliation_state")
        self.assertEqual(rows["O1004"][state], "order_amount_missing")
        self.assertEqual(rows["O1008"][state], "order_amount_missing")
        matching = sum(row[state] == "matches" for row in rows.values())
        self.assertEqual(matching, 10)

    def test_partial_item_total_is_not_silently_called_a_match(self) -> None:
        self.connection.execute(
            """
            INSERT INTO order_items VALUES
                ('O1001', 'P99', 'service', 1, NULL)
            """
        )
        JOIN.prepare_item_totals(self.connection)
        columns, rows = self.rows_by_order()
        known_rows = columns.index("known_item_amount_rows")
        complete = columns.index("item_amount_complete")
        state = columns.index("amount_reconciliation_state")
        self.assertEqual(rows["O1001"][known_rows], 2)
        self.assertFalse(rows["O1001"][complete])
        self.assertEqual(rows["O1001"][state], "item_total_incomplete")

    def test_orphan_user_is_preserved_and_labeled(self) -> None:
        columns, rows = self.rows_by_order()
        state = columns.index("user_match_state")
        self.assertEqual(rows["O1010"][state], "orphan_reference")
        self.assertEqual(
            sum(row[state] == "orphan_reference" for row in rows.values()),
            1,
        )

    def test_fanout_is_reconciled_inside_each_currency(self) -> None:
        audit = {
            row["currency"]: row
            for row in JOIN.fanout_by_currency(self.connection)
        }
        self.assertEqual(
            audit["RUB"],
            {
                "currency": "RUB",
                "source_paid_amount": Decimal("2700.00"),
                "joined_paid_amount": Decimal("5400.00"),
                "fanout_extra": Decimal("2700.00"),
            },
        )
        for currency in ("EUR", "KZT", "USD"):
            self.assertEqual(audit[currency]["fanout_extra"], Decimal("0.00"))

    def test_money_stays_decimal_and_no_cross_currency_total_is_published(self) -> None:
        report = JOIN.run_example()
        self.assertNotIn("paid_revenue_total", report)
        self.assertNotIn("5005", json.dumps(report))
        self.assertNotIn("7705", json.dumps(report))
        columns, _, rows = self.safe_mart()
        amount_position = columns.index("amount")
        known = [row[amount_position] for row in rows if row[amount_position] is not None]
        self.assertTrue(all(isinstance(value, Decimal) for value in known))

    def test_direct_join_expands_rows_safe_mart_does_not(self) -> None:
        direct_rows = self.connection.execute(
            """
            SELECT count(*)
            FROM orders AS o
            INNER JOIN order_items AS i
                ON o.order_id = i.order_id
            """
        ).fetchone()[0]
        _, _, safe_rows = self.safe_mart()
        self.assertEqual(direct_rows, 14)
        self.assertEqual(len(safe_rows), 12)

    def test_left_join_can_multiply_rows_when_right_key_is_duplicated(self) -> None:
        self.connection.execute(
            """
            INSERT INTO users VALUES
                ('U001', '2026-01-01T00:00:00Z', 'RU', 'duplicate')
            """
        )
        with self.assertRaisesRegex(ValueError, "users grain violation"):
            JOIN.validate_input(self.connection)

        _, _, rows = JOIN.execute_safe_mart(self.connection)
        order_ids = [row[0] for row in rows]
        self.assertEqual(len(rows), 14)
        self.assertEqual(order_ids.count("O1001"), 2)
        self.assertEqual(order_ids.count("O1005"), 2)

    def test_duplicate_composite_item_key_fails_before_aggregation(self) -> None:
        self.connection.execute(
            """
            INSERT INTO order_items VALUES
                ('O1001', 'P01', 'subscription', 1, 1000.00)
            """
        )
        with self.assertRaisesRegex(ValueError, "order_items grain violation"):
            JOIN.validate_input(self.connection)

    def test_left_join_preserves_order_without_items_and_labels_it(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O1999', 'U001', NULL, 'paid', 'RUB', 100.00)
            """
        )
        columns, rows = self.rows_by_order()
        item_state = columns.index("item_match_state")
        amount_state = columns.index("amount_reconciliation_state")
        self.assertEqual(rows["O1999"][item_state], "no_items")
        self.assertEqual(rows["O1999"][amount_state], "item_total_missing")

    def test_anti_join_finds_coverage_gaps_in_both_directions(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders VALUES
                ('O1999', 'U001', NULL, 'paid', 'RUB', 100.00)
            """
        )
        self.connection.execute(
            """
            INSERT INTO order_items VALUES
                ('O2999', 'P99', 'service', 1, 10.00)
            """
        )
        counts = JOIN.coverage_counts(self.connection)
        self.assertEqual(counts["orders_without_items"], 1)
        self.assertEqual(counts["item_rows_without_order"], 1)

    def test_inner_join_would_hide_order_with_orphan_user(self) -> None:
        inner_rows = self.connection.execute(
            """
            SELECT count(*)
            FROM orders AS o
            INNER JOIN users AS u
                ON o.user_id = u.user_id
            """
        ).fetchone()[0]
        left_rows = self.connection.execute(
            """
            SELECT count(*)
            FROM orders AS o
            LEFT JOIN users AS u
                ON o.user_id = u.user_id
            """
        ).fetchone()[0]
        self.assertEqual(inner_rows, 11)
        self.assertEqual(left_rows, 12)

    def test_null_keys_do_not_match_under_ordinary_equality(self) -> None:
        self.connection.execute(
            "CREATE TEMP TABLE left_keys(key VARCHAR, left_value VARCHAR)"
        )
        self.connection.execute(
            "CREATE TEMP TABLE right_keys(key VARCHAR, right_value VARCHAR)"
        )
        self.connection.execute("INSERT INTO left_keys VALUES (NULL, 'left-null')")
        self.connection.execute("INSERT INTO right_keys VALUES (NULL, 'right-null')")
        row = self.connection.execute(
            """
            SELECT l.left_value, r.right_value
            FROM left_keys AS l
            LEFT JOIN right_keys AS r
                ON l.key = r.key
            """
        ).fetchone()
        self.assertEqual(row, ("left-null", None))

    def test_composite_join_requires_every_key_part(self) -> None:
        self.connection.execute(
            """
            CREATE TEMP TABLE order_lines AS
            SELECT * FROM (
                VALUES
                    ('O1', 'P1'),
                    ('O1', 'P2')
            ) AS t(order_id, product_id)
            """
        )
        self.connection.execute(
            """
            CREATE TEMP TABLE prices AS
            SELECT * FROM (
                VALUES
                    ('O1', 'P1', 10),
                    ('O1', 'P2', 20)
            ) AS t(order_id, product_id, price)
            """
        )
        incomplete_rows = self.connection.execute(
            """
            SELECT count(*)
            FROM order_lines AS l
            JOIN prices AS p
                ON l.order_id = p.order_id
            """
        ).fetchone()[0]
        complete_rows = self.connection.execute(
            """
            SELECT count(*)
            FROM order_lines AS l
            JOIN prices AS p
                ON l.order_id = p.order_id
               AND l.product_id = p.product_id
            """
        ).fetchone()[0]
        self.assertEqual(incomplete_rows, 4)
        self.assertEqual(complete_rows, 2)

    def test_distinct_amount_is_not_a_fanout_fix(self) -> None:
        self.connection.execute(
            """
            CREATE TEMP TABLE equal_amount_orders(order_id VARCHAR, amount INTEGER)
            """
        )
        self.connection.execute(
            "INSERT INTO equal_amount_orders VALUES ('O1', 100), ('O2', 100)"
        )
        correct, distinct_sum = self.connection.execute(
            """
            SELECT sum(amount), sum(DISTINCT amount)
            FROM equal_amount_orders
            """
        ).fetchone()
        self.assertEqual(correct, 200)
        self.assertEqual(distinct_sum, 100)

    def test_sql_artifacts_contain_only_current_sql_mechanisms(self) -> None:
        queries = (
            ITEM_TOTALS_QUERY.read_text(encoding="utf-8").lower(),
            MART_QUERY.read_text(encoding="utf-8").lower(),
        )
        for query in queries:
            self.assertNotIn("read_csv", query)
            self.assertNotIn("with ", query)
            self.assertNotIn("select *", query)
        self.assertIn("group by order_id", queries[0])
        self.assertIn("left join item_totals", queries[1])
        self.assertIn("left join users", queries[1])

    def test_artifact_is_sql_not_cli(self) -> None:
        artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        lesson = json.loads(LESSON.read_text(encoding="utf-8"))
        self.assertEqual(artifact["type"], "sql")
        self.assertEqual(artifact["path"], "outputs/safe_order_mart.sql")
        self.assertEqual(lesson["artifact"]["type"], "sql")
        self.assertFalse((ROOT / "outputs" / "safe_join.py").exists())
        self.assertNotIn("argparse", CODE.read_text(encoding="utf-8"))

    def test_quiz_uses_varied_correct_answer_positions(self) -> None:
        quiz = json.loads(QUIZ.read_text(encoding="utf-8"))
        positions = [question["correct"] for question in quiz["questions"]]
        self.assertGreaterEqual(len(set(positions)), 3)
        self.assertEqual(
            sum(question["stage"] == "pre" for question in quiz["questions"]),
            2,
        )
        self.assertGreaterEqual(
            sum(question["stage"] == "post" for question in quiz["questions"]),
            3,
        )


if __name__ == "__main__":
    unittest.main()
