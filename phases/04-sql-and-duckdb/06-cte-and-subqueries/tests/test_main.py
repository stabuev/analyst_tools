from __future__ import annotations

import importlib.util
import json
import re
import unittest
from decimal import Decimal
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CODE_PATH = ROOT / "code" / "main.py"
PIPELINE_PATH = ROOT / "outputs" / "checked_order_pipeline.sql"
SUBQUERY_PATH = ROOT / "outputs" / "subquery_audit.sql"
ARTIFACT_PATH = ROOT / "outputs" / "artifact.json"
LESSON_PATH = ROOT / "lesson.json"
QUIZ_PATH = ROOT / "quiz.json"

SPEC = importlib.util.spec_from_file_location("cte_lesson", CODE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {CODE_PATH}")
LESSON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LESSON)


class CtePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        LESSON.prepare_relations(self.connection)
        LESSON.validate_input(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def stage(self, name: str, key: str) -> tuple[list[str], list[tuple]]:
        columns, _, rows = LESSON.execute_stage(
            self.connection,
            name,
            order_by=key,
        )
        return columns, rows

    def final(self) -> tuple[list[str], list[str], list[tuple]]:
        return LESSON.execute_pipeline(self.connection)

    def test_pipeline_has_four_named_stages_in_dependency_order(self) -> None:
        query = PIPELINE_PATH.read_text(encoding="utf-8")
        positions = [
            query.index(f"{stage} AS")
            for stage in (
                "item_totals",
                "safe_order_mart",
                "paid_order_mart",
                "currency_summary",
            )
        ]
        self.assertEqual(positions, sorted(positions))

    def test_every_stage_preserves_its_declared_grain(self) -> None:
        expectations = {
            "item_totals": ("order_id", 12),
            "safe_order_mart": ("order_id", 12),
            "paid_order_mart": ("order_id", 9),
            "currency_summary": ("currency", 4),
        }
        for stage, (key, expected_rows) in expectations.items():
            columns, rows = self.stage(stage, key)
            values = [row[columns.index(key)] for row in rows]
            self.assertEqual(len(rows), expected_rows, stage)
            self.assertEqual(len(set(values)), expected_rows, stage)

    def test_paid_stage_contains_only_paid_order_ids(self) -> None:
        columns, rows = self.stage("paid_order_mart", "order_id")
        actual = [row[columns.index("order_id")] for row in rows]
        expected = [
            row[0]
            for row in self.connection.execute(
                "SELECT order_id FROM orders WHERE status = 'paid' ORDER BY order_id"
            ).fetchall()
        ]
        self.assertEqual(actual, expected)

    def test_item_totals_keep_multirow_orders_at_one_row(self) -> None:
        columns, rows = self.stage("item_totals", "order_id")
        by_order = {row[columns.index("order_id")]: row for row in rows}
        o1001 = by_order["O1001"]
        self.assertEqual(o1001[columns.index("item_rows")], 2)
        self.assertEqual(o1001[columns.index("item_total")], Decimal("1200.00"))
        self.assertTrue(o1001[columns.index("item_amount_complete")])

    def test_safe_mart_keeps_orphan_reference_visible(self) -> None:
        columns, rows = self.stage("safe_order_mart", "order_id")
        by_order = {row[columns.index("order_id")]: row for row in rows}
        o1010 = by_order["O1010"]
        self.assertEqual(
            o1010[columns.index("user_match_state")],
            "orphan_reference",
        )

    def test_final_schema_and_types_are_stable(self) -> None:
        columns, types, rows = self.final()
        self.assertEqual(columns, LESSON.EXPECTED_FINAL_COLUMNS)
        self.assertEqual(types, LESSON.EXPECTED_FINAL_TYPES)
        LESSON.validate_pipeline(self.connection, columns, types, rows)

    def test_final_amounts_remain_separate_by_currency(self) -> None:
        columns, _, rows = self.final()
        amount_at = columns.index("known_paid_amount")
        actual = {row[0]: row[amount_at] for row in rows}
        self.assertEqual(
            actual,
            {
                "EUR": Decimal("1625.00"),
                "KZT": Decimal("500.00"),
                "RUB": Decimal("2700.00"),
                "USD": Decimal("180.00"),
            },
        )
        self.assertNotIn(Decimal("5005.00"), actual.values())

    def test_final_reports_orphan_in_its_currency(self) -> None:
        columns, _, rows = self.final()
        orphan_at = columns.index("orphan_user_orders")
        actual = {row[0]: row[orphan_at] for row in rows}
        self.assertEqual(actual, {"EUR": 0, "KZT": 0, "RUB": 0, "USD": 1})

    def test_missing_items_survive_left_join_as_explicit_state(self) -> None:
        self.connection.execute("DELETE FROM order_items WHERE order_id = 'O1012'")
        columns, rows = self.stage("safe_order_mart", "order_id")
        by_order = {row[columns.index("order_id")]: row for row in rows}
        self.assertEqual(
            by_order["O1012"][columns.index("item_match_state")],
            "no_items",
        )
        final_columns, _, final_rows = self.final()
        eur = next(row for row in final_rows if row[0] == "EUR")
        self.assertEqual(
            eur[final_columns.index("orders_without_items")],
            1,
        )

    def test_missing_order_and_item_amounts_remain_distinguishable(self) -> None:
        self.connection.execute("DELETE FROM order_items WHERE order_id = 'O1008'")
        columns, rows = self.stage("safe_order_mart", "order_id")
        by_order = {row[columns.index("order_id")]: row for row in rows}
        self.assertEqual(
            by_order["O1008"][columns.index("amount_reconciliation_state")],
            "both_missing",
        )

    def test_partial_item_total_is_not_reported_as_complete(self) -> None:
        self.connection.execute(
            """
            UPDATE order_items
            SET unit_price = NULL
            WHERE order_id = 'O1001' AND product_id = 'P02'
            """
        )
        columns, rows = self.stage("safe_order_mart", "order_id")
        by_order = {row[columns.index("order_id")]: row for row in rows}
        self.assertEqual(
            by_order["O1001"][columns.index("amount_reconciliation_state")],
            "item_total_incomplete",
        )
        final_columns, _, final_rows = self.final()
        rub = next(row for row in final_rows if row[0] == "RUB")
        self.assertEqual(
            rub[final_columns.index("incomplete_item_total_orders")],
            1,
        )

    def test_duplicate_user_key_is_rejected_before_fanout(self) -> None:
        self.connection.execute("INSERT INTO users SELECT * FROM users WHERE user_id = 'U001'")
        with self.assertRaisesRegex(ValueError, "grain violation"):
            LESSON.validate_input(self.connection)

    def test_duplicate_item_key_is_rejected(self) -> None:
        self.connection.execute(
            """
            INSERT INTO order_items
            SELECT * FROM order_items
            WHERE order_id = 'O1001' AND product_id = 'P01'
            """
        )
        with self.assertRaisesRegex(ValueError, "grain violation"):
            LESSON.validate_input(self.connection)

    def test_derived_table_can_supply_one_use_relation(self) -> None:
        row = self.connection.execute(
            """
            SELECT count(*)
            FROM (
                SELECT order_id
                FROM orders
                WHERE status = 'paid'
            ) AS paid_orders
            """
        ).fetchone()
        self.assertEqual(row[0], 9)

    def test_scalar_subquery_rejects_more_than_one_row(self) -> None:
        with self.assertRaises(duckdb.InvalidInputException):
            self.connection.execute("SELECT (SELECT order_id FROM orders)").fetchall()

    def test_not_exists_is_null_safe_where_not_in_is_not(self) -> None:
        self.connection.execute(
            """
            CREATE TEMP TABLE known_users AS
            SELECT user_id FROM users
            UNION ALL
            SELECT NULL
            """
        )
        not_exists = self.connection.execute(
            """
            SELECT DISTINCT o.user_id
            FROM orders AS o
            WHERE o.user_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM known_users AS k
                  WHERE k.user_id = o.user_id
              )
            ORDER BY o.user_id
            """
        ).fetchall()
        not_in = self.connection.execute(
            """
            SELECT DISTINCT user_id
            FROM orders
            WHERE user_id NOT IN (SELECT user_id FROM known_users)
            ORDER BY user_id
            """
        ).fetchall()
        self.assertEqual(not_exists, [("U999",)])
        self.assertEqual(not_in, [])

    def test_subquery_audit_returns_scalar_and_existence_checks(self) -> None:
        audit = LESSON.execute_subquery_audit(self.connection)
        self.assertEqual(audit["source_order_rows"], 12)
        self.assertEqual(audit["source_paid_order_rows"], 9)
        self.assertTrue(audit["has_orphan_user_reference"])

    def test_sql_artifacts_do_not_hide_future_or_infrastructure_topics(self) -> None:
        sql = "\n".join(
            [
                PIPELINE_PATH.read_text(encoding="utf-8"),
                SUBQUERY_PATH.read_text(encoding="utf-8"),
            ]
        )
        for forbidden in (
            "read_csv",
            "TIMESTAMPTZ",
            "argparse",
            "MATERIALIZED",
            "EXPLAIN",
            "RECURSIVE",
        ):
            self.assertNotIn(forbidden.lower(), sql.lower())
        self.assertIsNone(re.search(r"\bSELECT\s+\*", sql, flags=re.IGNORECASE))

    def test_artifact_is_sql_not_cli(self) -> None:
        lesson = json.loads(LESSON_PATH.read_text(encoding="utf-8"))
        artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(lesson["artifact"]["type"], "sql")
        self.assertEqual(artifact["type"], "sql")
        self.assertEqual(
            lesson["artifact"]["path"],
            "outputs/checked_order_pipeline.sql",
        )
        self.assertFalse((ROOT / "outputs" / "cte_pipeline.py").exists())

    def test_quiz_has_varied_correct_positions(self) -> None:
        quiz = json.loads(QUIZ_PATH.read_text(encoding="utf-8"))
        positions = [question["correct"] for question in quiz["questions"]]
        self.assertGreater(len(set(positions)), 1)


if __name__ == "__main__":
    unittest.main()
