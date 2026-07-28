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
SEQUENCE_SQL_PATH = ROOT / "outputs" / "order_sequence_windows.sql"
LATEST_SQL_PATH = ROOT / "outputs" / "latest_paid_order_per_user.sql"
ARTIFACT_PATH = ROOT / "outputs" / "artifact.json"
LESSON_PATH = ROOT / "lesson.json"
QUIZ_PATH = ROOT / "quiz.json"
OLD_ARTIFACT_PATH = ROOT / "outputs" / "window_metrics.py"

SPEC = importlib.util.spec_from_file_location("window_lesson", CODE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {CODE_PATH}")
LESSON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LESSON)


class WindowSequenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        LESSON.prepare_orders(self.connection)
        LESSON.validate_input(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def sequence(
        self,
    ) -> tuple[list[str], list[str], list[tuple]]:
        return LESSON.execute_sequence(self.connection)

    def sequence_rows(self) -> tuple[list[str], dict[str, tuple]]:
        columns, _, rows = self.sequence()
        order_id_at = columns.index("order_id")
        return columns, {row[order_id_at]: row for row in rows}

    def test_window_columns_preserve_paid_order_grain(self) -> None:
        columns, types, rows = self.sequence()
        LESSON.validate_sequence(columns, types, rows)
        order_ids = [row[columns.index("order_id")] for row in rows]
        self.assertEqual(len(rows), 9)
        self.assertEqual(len(set(order_ids)), 9)

    def test_sequence_schema_and_types_are_stable(self) -> None:
        columns, types, _ = self.sequence()
        self.assertEqual(columns, LESSON.EXPECTED_SEQUENCE_COLUMNS)
        self.assertEqual(types, LESSON.EXPECTED_SEQUENCE_TYPES)

    def test_row_number_restarts_for_each_user(self) -> None:
        columns, by_order = self.sequence_rows()
        number_at = columns.index("user_order_number")
        self.assertEqual(by_order["O1001"][number_at], 1)
        self.assertEqual(by_order["O1005"][number_at], 2)
        self.assertEqual(by_order["O1003"][number_at], 1)
        self.assertEqual(by_order["O1011"][number_at], 2)

    def test_lag_and_lead_follow_the_same_user_chronology(self) -> None:
        columns, by_order = self.sequence_rows()
        previous_order_at = columns.index("previous_order_id")
        previous_amount_at = columns.index("previous_amount")
        next_order_at = columns.index("next_order_id")

        self.assertIsNone(by_order["O1001"][previous_order_at])
        self.assertEqual(by_order["O1001"][next_order_at], "O1005")
        self.assertEqual(by_order["O1005"][previous_order_at], "O1001")
        self.assertEqual(
            by_order["O1005"][previous_amount_at],
            Decimal("1200.00"),
        )
        self.assertIsNone(by_order["O1005"][next_order_at])

    def test_previous_order_id_distinguishes_boundary_from_missing_value(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders
            VALUES (
                'O1013',
                'U008',
                TIMESTAMPTZ '2026-04-06 10:00:00+00',
                'paid',
                'EUR',
                NULL
            )
            """
        )
        self.connection.execute(
            """
            INSERT INTO orders
            VALUES (
                'O1014',
                'U008',
                TIMESTAMPTZ '2026-04-07 10:00:00+00',
                'paid',
                'EUR',
                30.00
            )
            """
        )
        LESSON.validate_input(self.connection)
        columns, by_order = self.sequence_rows()
        previous_order_at = columns.index("previous_order_id")
        previous_amount_at = columns.index("previous_amount")

        self.assertEqual(by_order["O1014"][previous_order_at], "O1013")
        self.assertIsNone(by_order["O1014"][previous_amount_at])

    def test_reverse_row_number_marks_latest_order(self) -> None:
        columns, by_order = self.sequence_rows()
        latest_at = columns.index("latest_order_number")
        self.assertEqual(by_order["O1001"][latest_at], 2)
        self.assertEqual(by_order["O1005"][latest_at], 1)
        self.assertEqual(by_order["O1011"][latest_at], 1)

    def test_later_cte_filters_one_latest_order_per_user(self) -> None:
        columns, _, rows = LESSON.execute_latest(self.connection)
        user_at = columns.index("user_id")
        order_at = columns.index("order_id")
        latest = {row[user_at]: row[order_at] for row in rows}
        self.assertEqual(
            latest,
            {
                "U001": "O1005",
                "U002": "O1007",
                "U003": "O1011",
                "U005": "O1006",
                "U007": "O1012",
                "U999": "O1010",
            },
        )

    def test_rank_and_dense_rank_treat_equal_amounts_as_peers(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders
            VALUES (
                'O1013',
                'U008',
                TIMESTAMPTZ '2026-04-06 10:00:00+00',
                'paid',
                'RUB',
                1500.00
            )
            """
        )
        LESSON.validate_input(self.connection)
        columns, by_order = self.sequence_rows()
        rank_at = columns.index("amount_rank_in_currency")
        dense_at = columns.index("amount_dense_rank_in_currency")

        self.assertEqual(by_order["O1005"][rank_at], 1)
        self.assertEqual(by_order["O1013"][rank_at], 1)
        self.assertEqual(by_order["O1001"][rank_at], 3)
        self.assertEqual(by_order["O1005"][dense_at], 1)
        self.assertEqual(by_order["O1013"][dense_at], 1)
        self.assertEqual(by_order["O1001"][dense_at], 2)

    def test_row_number_uses_order_id_as_tie_breaker(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders
            VALUES (
                'O1005A',
                'U001',
                TIMESTAMPTZ '2026-02-05 08:00:00+00',
                'paid',
                'RUB',
                1000.00
            )
            """
        )
        LESSON.validate_input(self.connection)
        columns, by_order = self.sequence_rows()
        number_at = columns.index("user_order_number")
        self.assertEqual(by_order["O1005"][number_at], 2)
        self.assertEqual(by_order["O1005A"][number_at], 3)

    def test_missing_amount_does_not_receive_false_numeric_rank(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders
            VALUES (
                'O1013',
                'U008',
                TIMESTAMPTZ '2026-04-06 10:00:00+00',
                'paid',
                'EUR',
                NULL
            )
            """
        )
        LESSON.validate_input(self.connection)
        columns, by_order = self.sequence_rows()
        amount_at = columns.index("amount")
        rank_at = columns.index("amount_rank_in_currency")
        dense_at = columns.index("amount_dense_rank_in_currency")
        self.assertIsNone(by_order["O1013"][amount_at])
        self.assertIsNone(by_order["O1013"][rank_at])
        self.assertIsNone(by_order["O1013"][dense_at])

    def test_duplicate_order_id_is_rejected_before_windowing(self) -> None:
        self.connection.execute(
            "INSERT INTO orders SELECT * FROM orders WHERE order_id = 'O1001'"
        )
        with self.assertRaisesRegex(ValueError, "grain violation"):
            LESSON.validate_input(self.connection)

    def test_blank_status_is_rejected_before_population_filter(self) -> None:
        self.connection.execute(
            "UPDATE orders SET status = '' WHERE order_id = 'O1004'"
        )
        with self.assertRaisesRegex(ValueError, "orders.status"):
            LESSON.validate_input(self.connection)

    def test_noncanonical_status_is_rejected_before_population_filter(self) -> None:
        self.connection.execute(
            "UPDATE orders SET status = 'Paid' WHERE order_id = 'O1001'"
        )
        with self.assertRaisesRegex(ValueError, "canonical values"):
            LESSON.validate_input(self.connection)

    def test_paid_order_requires_user_id(self) -> None:
        self.connection.execute(
            "UPDATE orders SET user_id = NULL WHERE order_id = 'O1001'"
        )
        with self.assertRaisesRegex(ValueError, "orders.user_id"):
            LESSON.validate_input(self.connection)

    def test_paid_order_requires_currency(self) -> None:
        self.connection.execute(
            "UPDATE orders SET currency = NULL WHERE order_id = 'O1001'"
        )
        with self.assertRaisesRegex(ValueError, "orders.currency"):
            LESSON.validate_input(self.connection)

    def test_paid_order_requires_ordered_at(self) -> None:
        self.connection.execute(
            "UPDATE orders SET ordered_at = NULL WHERE order_id = 'O1001'"
        )
        with self.assertRaisesRegex(ValueError, "require ordered_at"):
            LESSON.validate_input(self.connection)

    def test_window_order_and_final_output_order_are_both_explicit(self) -> None:
        sql = SEQUENCE_SQL_PATH.read_text(encoding="utf-8")
        self.assertIn("PARTITION BY user_id", sql)
        self.assertIn("ORDER BY ordered_at, order_id", sql)
        self.assertRegex(
            sql,
            r"FROM sequenced_orders\s+ORDER BY user_id, ordered_at, order_id;",
        )

    def test_peer_rank_does_not_use_unique_order_id_as_tie_breaker(self) -> None:
        sql = SEQUENCE_SQL_PATH.read_text(encoding="utf-8")
        match = re.search(
            r"currency_amount_peers AS \((.*?)\)\s*\)\s*SELECT",
            sql,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        peer_window = match.group(1)
        self.assertIn("ORDER BY amount DESC NULLS LAST", peer_window)
        self.assertNotIn("order_id", peer_window)

    def test_sql_artifacts_stop_before_window_aggregates_and_future_topics(self) -> None:
        sql = "\n".join(
            [
                SEQUENCE_SQL_PATH.read_text(encoding="utf-8"),
                LATEST_SQL_PATH.read_text(encoding="utf-8"),
            ]
        ).lower()
        for forbidden in (
            " rows between ",
            " range between ",
            "sum(",
            "avg(",
            "read_csv",
            "::timestamptz",
            "qualify",
        ):
            self.assertNotIn(forbidden, sql)

    def test_named_artifact_is_sql_and_old_cli_is_removed(self) -> None:
        lesson = json.loads(LESSON_PATH.read_text(encoding="utf-8"))
        artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        expected = {
            "name": artifact["name"],
            "type": artifact["type"],
            "path": artifact["path"],
        }
        self.assertEqual(lesson["artifact"], expected)
        self.assertEqual(artifact["type"], "sql")
        self.assertEqual(artifact["path"], "outputs/order_sequence_windows.sql")
        self.assertFalse(OLD_ARTIFACT_PATH.exists())

    def test_quiz_activates_prerequisites_and_varies_answer_positions(self) -> None:
        quiz = json.loads(QUIZ_PATH.read_text(encoding="utf-8"))
        pre = [
            question
            for question in quiz["questions"]
            if question["stage"] == "pre"
        ]
        post = [
            question
            for question in quiz["questions"]
            if question["stage"] == "post"
        ]
        self.assertEqual(len(pre), 2)
        self.assertGreaterEqual(len(post), 5)
        self.assertGreater(len({question["correct"] for question in quiz["questions"]}), 2)
        self.assertTrue(
            any("grain" in question["question"].lower() for question in pre)
        )
        self.assertTrue(
            any("cte" in question["question"].lower() for question in pre)
        )


if __name__ == "__main__":
    unittest.main()
