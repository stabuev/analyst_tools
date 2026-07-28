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
FRAMES_SQL_PATH = ROOT / "outputs" / "order_amount_frames.sql"
EXPERIMENT_SQL_PATH = ROOT / "outputs" / "frame_semantics_experiment.sql"
ARTIFACT_PATH = ROOT / "outputs" / "artifact.json"
LESSON_PATH = ROOT / "lesson.json"
QUIZ_PATH = ROOT / "quiz.json"

SPEC = importlib.util.spec_from_file_location("frame_lesson", CODE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {CODE_PATH}")
LESSON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LESSON)


class WindowAggregateFrameTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        LESSON.prepare_orders(self.connection)
        LESSON.validate_input(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def frames(
        self,
    ) -> tuple[list[str], list[str], list[tuple]]:
        return LESSON.execute_frames(self.connection)

    def frame_rows(self) -> tuple[list[str], dict[str, tuple]]:
        columns, _, rows = self.frames()
        order_id_at = columns.index("order_id")
        return columns, {row[order_id_at]: row for row in rows}

    def experiment_rows(self) -> tuple[list[str], dict[str, tuple]]:
        columns, _, rows = LESSON.execute_experiment(self.connection)
        row_id_at = columns.index("row_id")
        return columns, {row[row_id_at]: row for row in rows}

    def test_window_aggregates_preserve_paid_order_grain(self) -> None:
        columns, types, rows = self.frames()
        LESSON.validate_frames(columns, types, rows)
        order_ids = [row[columns.index("order_id")] for row in rows]
        self.assertEqual(len(rows), 9)
        self.assertEqual(len(set(order_ids)), 9)

    def test_schema_and_types_are_stable(self) -> None:
        columns, types, _ = self.frames()
        self.assertEqual(columns, LESSON.EXPECTED_FRAME_COLUMNS)
        self.assertEqual(types, LESSON.EXPECTED_FRAME_TYPES)

    def test_partition_total_is_constant_without_window_order(self) -> None:
        columns, by_order = self.frame_rows()
        total_at = columns.index("currency_total_known_amount")
        self.assertEqual(by_order["O1006"][total_at], Decimal("1625.00"))
        self.assertEqual(by_order["O1009"][total_at], Decimal("1625.00"))
        self.assertEqual(by_order["O1012"][total_at], Decimal("1625.00"))
        self.assertEqual(by_order["O1001"][total_at], Decimal("2700.00"))
        self.assertEqual(by_order["O1003"][total_at], Decimal("180.00"))

    def test_running_sum_uses_currency_partition_and_order(self) -> None:
        columns, by_order = self.frame_rows()
        running_at = columns.index("currency_running_known_amount")
        self.assertEqual(by_order["O1006"][running_at], Decimal("25.00"))
        self.assertEqual(by_order["O1009"][running_at], Decimal("925.00"))
        self.assertEqual(by_order["O1012"][running_at], Decimal("1625.00"))
        self.assertEqual(by_order["O1003"][running_at], Decimal("75.00"))
        self.assertEqual(by_order["O1010"][running_at], Decimal("135.00"))
        self.assertEqual(by_order["O1011"][running_at], Decimal("180.00"))

    def test_recent_frame_is_cropped_at_partition_start(self) -> None:
        columns, by_order = self.frame_rows()
        rows_at = columns.index("recent_3_order_rows")
        avg_at = columns.index("recent_3_known_amount_avg")
        self.assertEqual(by_order["O1006"][rows_at], 1)
        self.assertEqual(by_order["O1009"][rows_at], 2)
        self.assertEqual(by_order["O1012"][rows_at], 3)
        self.assertAlmostEqual(by_order["O1006"][avg_at], 25.0)
        self.assertAlmostEqual(by_order["O1009"][avg_at], 462.5)
        self.assertAlmostEqual(by_order["O1012"][avg_at], 1625 / 3)

    def test_prior_frame_excludes_current_row(self) -> None:
        columns, by_order = self.frame_rows()
        rows_at = columns.index("prior_3_order_rows")
        avg_at = columns.index("prior_3_known_amount_avg")
        self.assertEqual(by_order["O1006"][rows_at], 0)
        self.assertIsNone(by_order["O1006"][avg_at])
        self.assertEqual(by_order["O1009"][rows_at], 1)
        self.assertAlmostEqual(by_order["O1009"][avg_at], 25.0)
        self.assertEqual(by_order["O1012"][rows_at], 2)
        self.assertAlmostEqual(by_order["O1012"][avg_at], 462.5)

    def test_missing_amount_changes_known_denominator_not_frame_size(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders
            VALUES (
                'O1013',
                'U008',
                TIMESTAMPTZ '2026-01-20 10:00:00+00',
                'paid',
                'RUB',
                NULL
            )
            """
        )
        LESSON.validate_input(self.connection)
        columns, by_order = self.frame_rows()

        running_rows_at = columns.index("currency_running_order_rows")
        running_known_at = columns.index("currency_running_known_amounts")
        running_amount_at = columns.index("currency_running_known_amount")
        recent_rows_at = columns.index("recent_3_order_rows")
        recent_known_at = columns.index("recent_3_known_amounts")
        recent_avg_at = columns.index("recent_3_known_amount_avg")
        prior_rows_at = columns.index("prior_3_order_rows")
        prior_known_at = columns.index("prior_3_known_amounts")
        prior_avg_at = columns.index("prior_3_known_amount_avg")

        self.assertEqual(by_order["O1005"][running_rows_at], 3)
        self.assertEqual(by_order["O1005"][running_known_at], 2)
        self.assertEqual(by_order["O1005"][running_amount_at], Decimal("2700.00"))
        self.assertEqual(by_order["O1005"][recent_rows_at], 3)
        self.assertEqual(by_order["O1005"][recent_known_at], 2)
        self.assertAlmostEqual(by_order["O1005"][recent_avg_at], 1350.0)
        self.assertEqual(by_order["O1005"][prior_rows_at], 2)
        self.assertEqual(by_order["O1005"][prior_known_at], 1)
        self.assertAlmostEqual(by_order["O1005"][prior_avg_at], 1200.0)

    def test_nonempty_frame_with_only_unknown_amount_has_null_average(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders
            VALUES (
                'O1013',
                'U008',
                TIMESTAMPTZ '2026-05-01 10:00:00+00',
                'paid',
                'GBP',
                NULL
            )
            """
        )
        LESSON.validate_input(self.connection)
        columns, by_order = self.frame_rows()
        row = by_order["O1013"]

        self.assertEqual(row[columns.index("currency_running_order_rows")], 1)
        self.assertEqual(row[columns.index("currency_running_known_amounts")], 0)
        self.assertIsNone(row[columns.index("currency_running_known_amount")])
        self.assertEqual(row[columns.index("recent_3_order_rows")], 1)
        self.assertEqual(row[columns.index("recent_3_known_amounts")], 0)
        self.assertIsNone(row[columns.index("recent_3_known_amount_avg")])
        self.assertEqual(row[columns.index("prior_3_order_rows")], 0)
        self.assertEqual(row[columns.index("prior_3_known_amounts")], 0)
        self.assertIsNone(row[columns.index("prior_3_known_amount_avg")])

    def test_order_id_makes_rows_frame_deterministic_for_equal_timestamps(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders
            VALUES
                (
                    'O1013',
                    'U008',
                    TIMESTAMPTZ '2026-05-01 10:00:00+00',
                    'paid',
                    'EUR',
                    10.00
                ),
                (
                    'O1014',
                    'U009',
                    TIMESTAMPTZ '2026-05-01 10:00:00+00',
                    'paid',
                    'EUR',
                    20.00
                )
            """
        )
        LESSON.validate_input(self.connection)
        columns, by_order = self.frame_rows()
        running_at = columns.index("currency_running_known_amount")
        self.assertEqual(by_order["O1013"][running_at], Decimal("1635.00"))
        self.assertEqual(by_order["O1014"][running_at], Decimal("1655.00"))

    def test_default_frame_and_explicit_range_include_peers_together(self) -> None:
        columns, by_id = self.experiment_rows()
        default_at = columns.index("default_running_sum")
        range_at = columns.index("range_running_sum")
        rows_at = columns.index("rows_running_sum")
        self.assertEqual(by_id["A"][default_at], 30)
        self.assertEqual(by_id["A"][range_at], 30)
        self.assertEqual(by_id["A"][rows_at], 10)
        self.assertEqual(by_id["B"][default_at], 30)
        self.assertEqual(by_id["B"][rows_at], 30)

    def test_rows_distance_and_range_distance_answer_different_questions(self) -> None:
        columns, by_id = self.experiment_rows()
        rows_at = columns.index("rows_distance_1_sum")
        range_at = columns.index("range_distance_1_sum")
        self.assertEqual(by_id["C"][rows_at], 25)
        self.assertEqual(by_id["C"][range_at], 35)
        self.assertEqual(by_id["D"][rows_at], 45)
        self.assertEqual(by_id["D"][range_at], 40)

    def test_last_value_depends_on_frame_end(self) -> None:
        columns, by_id = self.experiment_rows()
        default_at = columns.index("default_last_value")
        partition_at = columns.index("partition_last_value")
        self.assertEqual(by_id["A"][default_at], "A")
        self.assertEqual(by_id["C"][default_at], "C")
        self.assertTrue(all(row[partition_at] == "D" for row in by_id.values()))

    def test_duplicate_order_id_is_rejected_before_windowing(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders
            SELECT * FROM orders WHERE order_id = 'O1001'
            """
        )
        with self.assertRaisesRegex(ValueError, "grain violation"):
            LESSON.validate_input(self.connection)

    def test_paid_order_requires_currency(self) -> None:
        self.connection.execute("UPDATE orders SET currency = NULL WHERE order_id = 'O1001'")
        with self.assertRaisesRegex(ValueError, "orders.currency"):
            LESSON.validate_input(self.connection)

    def test_status_must_be_canonical(self) -> None:
        self.connection.execute("UPDATE orders SET status = 'completed' WHERE order_id = 'O1001'")
        with self.assertRaisesRegex(ValueError, "canonical values"):
            LESSON.validate_input(self.connection)

    def test_paid_order_requires_user_id(self) -> None:
        self.connection.execute("UPDATE orders SET user_id = '' WHERE order_id = 'O1001'")
        with self.assertRaisesRegex(ValueError, "orders.user_id"):
            LESSON.validate_input(self.connection)

    def test_paid_order_requires_ordered_at(self) -> None:
        self.connection.execute("UPDATE orders SET ordered_at = NULL WHERE order_id = 'O1001'")
        with self.assertRaisesRegex(ValueError, "require ordered_at"):
            LESSON.validate_input(self.connection)

    def test_main_artifact_uses_explicit_rows_frames(self) -> None:
        sql = re.sub(r"\s+", " ", FRAMES_SQL_PATH.read_text(encoding="utf-8").lower())
        self.assertGreaterEqual(sql.count(" rows between "), 3)
        self.assertNotIn(" range between ", sql)
        self.assertIn("2 preceding and current row", sql)
        self.assertIn("3 preceding and 1 preceding", sql)
        self.assertIn("count(*) over currency_recent_3_rows", sql)
        self.assertIn("count(amount) over currency_recent_3_rows", sql)

    def test_experiment_keeps_default_rows_and_range_visible(self) -> None:
        sql = re.sub(
            r"\s+",
            " ",
            EXPERIMENT_SQL_PATH.read_text(encoding="utf-8").lower(),
        )
        self.assertIn("order by sort_key ) as default_running_sum", sql)
        self.assertIn("rows between 1 preceding and current row", sql)
        self.assertIn("range between 1 preceding and current row", sql)
        self.assertIn(
            "rows between unbounded preceding and unbounded following",
            sql,
        )

    def test_sql_artifacts_do_not_take_over_loading_or_date_normalization(self) -> None:
        sql = (
            FRAMES_SQL_PATH.read_text(encoding="utf-8")
            + EXPERIMENT_SQL_PATH.read_text(encoding="utf-8")
        ).lower()
        for forbidden in (
            "read_csv",
            "read_parquet",
            "::timestamp",
            "::timestamptz",
            "date_trunc",
            "timezone(",
            "qualify",
        ):
            self.assertNotIn(forbidden, sql)

    def test_named_artifact_is_sql_and_runner_is_not_a_cli(self) -> None:
        lesson = json.loads(LESSON_PATH.read_text(encoding="utf-8"))
        artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        runner = CODE_PATH.read_text(encoding="utf-8")
        self.assertEqual(lesson["artifact"]["path"], "outputs/order_amount_frames.sql")
        self.assertEqual(artifact["path"], "outputs/order_amount_frames.sql")
        self.assertNotIn("argparse", runner)
        self.assertNotIn("sys.argv", runner)

    def test_quiz_activates_prerequisites_and_varies_answer_positions(self) -> None:
        quiz = json.loads(QUIZ_PATH.read_text(encoding="utf-8"))
        pre = [question for question in quiz["questions"] if question["stage"] == "pre"]
        post = [question for question in quiz["questions"] if question["stage"] == "post"]
        self.assertGreaterEqual(len(pre), 2)
        self.assertGreaterEqual(len(post), 5)
        self.assertGreater(len({question["correct"] for question in post}), 2)
        joined_pre = " ".join(question["question"].lower() for question in pre)
        self.assertIn("partition", joined_pre)
        self.assertIn("null", joined_pre)
        joined_post = " ".join(question["question"].lower() for question in post)
        self.assertIn("rows", joined_post)
        self.assertIn("range", joined_post)
        self.assertNotIn("last_value", joined_post)


if __name__ == "__main__":
    unittest.main()
