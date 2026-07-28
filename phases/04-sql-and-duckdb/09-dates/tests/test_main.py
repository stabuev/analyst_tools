from __future__ import annotations

import importlib.util
import json
import re
import unittest
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CODE_PATH = ROOT / "code" / "main.py"
MODEL_SQL_PATH = ROOT / "outputs" / "order_time_model.sql"
EXPERIMENT_SQL_PATH = ROOT / "outputs" / "temporal_semantics_experiment.sql"
ARTIFACT_PATH = ROOT / "outputs" / "artifact.json"
LESSON_PATH = ROOT / "lesson.json"
QUIZ_PATH = ROOT / "quiz.json"

SPEC = importlib.util.spec_from_file_location("dates_lesson", CODE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {CODE_PATH}")
LESSON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LESSON)


class SqlDatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        self.connection.execute("SET TimeZone = 'UTC'")
        LESSON.prepare_orders_source(self.connection)
        LESSON.validate_source(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def model(self) -> tuple[list[str], list[str], list[tuple]]:
        return LESSON.execute_time_model(self.connection)

    def model_rows(self) -> tuple[list[str], dict[str, tuple]]:
        columns, _, rows = self.model()
        order_id_at = columns.index("order_id")
        return columns, {row[order_id_at]: row for row in rows}

    def test_time_model_preserves_source_grain(self) -> None:
        columns, types, rows = self.model()
        LESSON.validate_time_model(columns, types, rows)
        order_ids = [row[columns.index("order_id")] for row in rows]
        self.assertEqual(len(rows), 12)
        self.assertEqual(len(set(order_ids)), 12)

    def test_schema_preserves_temporal_types(self) -> None:
        columns, types, _ = self.model()
        self.assertEqual(columns, LESSON.EXPECTED_MODEL_COLUMNS)
        self.assertEqual(types, LESSON.EXPECTED_MODEL_TYPES)
        self.assertEqual(types[columns.index("ordered_at_instant")], "TIMESTAMP WITH TIME ZONE")
        self.assertEqual(types[columns.index("business_local_time")], "TIMESTAMP")
        self.assertEqual(types[columns.index("business_date")], "DATE")
        self.assertEqual(types[columns.index("business_month")], "DATE")

    def test_offset_string_is_normalized_to_an_instant(self) -> None:
        columns, by_order = self.model_rows()
        instant_at = columns.index("ordered_at_instant")
        local_at = columns.index("business_local_time")
        self.assertEqual(
            by_order["O1001"][instant_at],
            datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
        )
        self.assertEqual(by_order["O1001"][local_at], datetime(2026, 1, 5, 10, 0))

    def test_different_offsets_can_describe_the_same_instant(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders_source
            VALUES
                ('same-plus-three', '2026-02-01T01:30:00+03:00'),
                ('same-utc', '2026-01-31T22:30:00Z')
            """
        )
        columns, by_order = self.model_rows()
        instant_at = columns.index("ordered_at_instant")
        local_at = columns.index("business_local_time")
        self.assertEqual(
            by_order["same-plus-three"][instant_at],
            by_order["same-utc"][instant_at],
        )
        self.assertEqual(
            by_order["same-plus-three"][local_at],
            by_order["same-utc"][local_at],
        )

    def test_business_calendar_is_cut_after_timezone_conversion(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders_source
            VALUES ('month-boundary', '2026-01-31T22:30:00Z')
            """
        )
        columns, by_order = self.model_rows()
        row = by_order["month-boundary"]
        self.assertEqual(row[columns.index("business_local_time")], datetime(2026, 2, 1, 1, 30))
        self.assertEqual(row[columns.index("business_date")], date(2026, 2, 1))
        self.assertEqual(row[columns.index("business_month")], date(2026, 2, 1))

    def test_business_calendar_does_not_depend_on_session_timezone(self) -> None:
        columns_utc, by_order_utc = self.model_rows()
        self.connection.execute("SET TimeZone = 'America/New_York'")
        columns_ny, by_order_ny = self.model_rows()
        for field in ("business_local_time", "business_date", "business_month"):
            self.assertEqual(
                by_order_utc["O1001"][columns_utc.index(field)],
                by_order_ny["O1001"][columns_ny.index(field)],
            )

    def test_missing_and_invalid_sources_remain_distinguishable(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders_source
            VALUES
                ('invalid-time', '2026-02-30T10:00:00Z'),
                ('naive-time', '2026-02-01 10:00:00')
            """
        )
        columns, by_order = self.model_rows()
        status_at = columns.index("timestamp_status")
        temporal_fields = (
            "ordered_at_instant",
            "business_local_time",
            "business_date",
            "business_month",
        )
        self.assertEqual(by_order["O1008"][status_at], "missing")
        self.assertEqual(by_order["invalid-time"][status_at], "invalid")
        self.assertEqual(by_order["naive-time"][status_at], "invalid")
        for order_id in ("O1008", "invalid-time", "naive-time"):
            self.assertTrue(
                all(by_order[order_id][columns.index(field)] is None for field in temporal_fields)
            )

    def test_reference_business_month_counts_are_typed_dates(self) -> None:
        columns, _, rows = self.model()
        month_at = columns.index("business_month")
        counts = Counter(row[month_at] for row in rows if row[month_at] is not None)
        self.assertEqual(
            counts,
            {
                date(2026, 1, 1): 2,
                date(2026, 2, 1): 4,
                date(2026, 3, 1): 3,
                date(2026, 4, 1): 2,
            },
        )

    def test_calendar_step_and_elapsed_duration_are_not_synonyms(self) -> None:
        columns, types, rows = LESSON.execute_temporal_experiment(self.connection)
        self.assertEqual(
            types,
            ["TIMESTAMP", "TIMESTAMP", "INTERVAL", "TIMESTAMP", "BIGINT", "BIGINT"],
        )
        row = rows[0]
        self.assertEqual(row[columns.index("elapsed_duration")], timedelta(hours=23))
        self.assertEqual(
            row[columns.index("after_24_hours_local_time")],
            datetime(2026, 3, 29, 13, 0),
        )
        self.assertEqual(row[columns.index("calendar_day_boundaries")], 1)
        self.assertEqual(row[columns.index("month_boundaries")], 1)

    def test_half_open_business_period_has_one_owner_for_each_boundary(self) -> None:
        selected = self.connection.execute(
            """
            WITH examples(order_id, ordered_at_instant) AS (
                VALUES
                    ('before', TIMESTAMPTZ '2026-01-31 20:59:59+00'),
                    ('at-start', TIMESTAMPTZ '2026-01-31 21:00:00+00'),
                    ('inside', TIMESTAMPTZ '2026-02-15 12:00:00+00'),
                    ('at-end', TIMESTAMPTZ '2026-02-28 21:00:00+00')
            )
            SELECT order_id
            FROM examples
            WHERE ordered_at_instant
                    >= TIMESTAMP '2026-02-01 00:00:00'
                        AT TIME ZONE 'Europe/Moscow'
              AND ordered_at_instant
                    < TIMESTAMP '2026-03-01 00:00:00'
                        AT TIME ZONE 'Europe/Moscow'
            ORDER BY order_id
            """
        ).fetchall()
        self.assertEqual(selected, [("at-start",), ("inside",)])

    def test_duplicate_source_key_is_rejected(self) -> None:
        self.connection.execute(
            """
            INSERT INTO orders_source
            SELECT * FROM orders_source WHERE order_id = 'O1001'
            """
        )
        with self.assertRaisesRegex(ValueError, "grain violation"):
            LESSON.validate_source(self.connection)

    def test_sql_artifact_owns_transformation_not_file_loading_or_formatting(self) -> None:
        sql = re.sub(r"\s+", " ", MODEL_SQL_PATH.read_text(encoding="utf-8").lower())
        self.assertIn("try_cast", sql)
        self.assertIn("'missing'", sql)
        self.assertIn("'invalid'", sql)
        self.assertIn("regexp_matches", sql)
        self.assertIn("'europe/moscow'::varchar as business_timezone", sql)
        self.assertIn("timezone(", sql)
        self.assertIn("date_trunc('month'", sql)
        for forbidden in ("read_csv", "read_parquet", "strftime", "argparse"):
            self.assertNotIn(forbidden, sql)

    def test_named_artifact_is_sql_and_runner_is_not_a_cli(self) -> None:
        lesson = json.loads(LESSON_PATH.read_text(encoding="utf-8"))
        artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        runner = CODE_PATH.read_text(encoding="utf-8")
        self.assertEqual(lesson["artifact"]["type"], "sql")
        self.assertEqual(lesson["artifact"]["path"], "outputs/order_time_model.sql")
        self.assertEqual(artifact["path"], "outputs/order_time_model.sql")
        self.assertNotIn("argparse", runner)
        self.assertNotIn("sys.argv", runner)

    def test_quiz_activates_prerequisites_and_varies_answer_positions(self) -> None:
        quiz = json.loads(QUIZ_PATH.read_text(encoding="utf-8"))
        pre = [question for question in quiz["questions"] if question["stage"] == "pre"]
        post = [question for question in quiz["questions"] if question["stage"] == "post"]
        self.assertGreaterEqual(len(pre), 2)
        self.assertGreaterEqual(len(post), 6)
        self.assertGreater(len({question["correct"] for question in post}), 2)
        joined_pre = " ".join(question["question"].lower() for question in pre)
        self.assertIn("offset", joined_pre)
        self.assertIn("пропущ", joined_pre)
        joined_post = " ".join(question["question"].lower() for question in post)
        for term in ("timestamptz", "time zone", "date_diff", "границ"):
            self.assertIn(term, joined_post)


if __name__ == "__main__":
    unittest.main()
