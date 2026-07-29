from __future__ import annotations

import importlib.util
import json
import re
import unittest
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
CODE_PATH = ROOT / "code" / "main.py"
MODEL_SQL_PATH = ROOT / "outputs" / "monthly_cohort_activity.sql"
ARTIFACT_PATH = ROOT / "outputs" / "artifact.json"
LESSON_PATH = ROOT / "lesson.json"
QUIZ_PATH = ROOT / "quiz.json"

SPEC = importlib.util.spec_from_file_location("cohort_lesson", CODE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {CODE_PATH}")
LESSON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LESSON)


class CohortMartTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        self.connection.execute("SET TimeZone = 'UTC'")
        LESSON.prepare_inputs(self.connection)
        LESSON.validate_inputs(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def model(self) -> tuple[list[str], list[str], list[tuple]]:
        return LESSON.execute_model(self.connection)

    def rows_by_grain(self) -> tuple[list[str], dict[tuple[date, int], tuple]]:
        columns, _, rows = self.model()
        cohort_at = columns.index("cohort_month")
        period_at = columns.index("period_index")
        return columns, {(row[cohort_at], row[period_at]): row for row in rows}

    def test_model_has_typed_schema_unique_grain_and_twelve_cells(self) -> None:
        columns, types, rows = self.model()
        LESSON.validate_model(columns, types, rows)
        grain = [
            (row[columns.index("cohort_month")], row[columns.index("period_index")]) for row in rows
        ]
        self.assertEqual(columns, LESSON.EXPECTED_COLUMNS)
        self.assertEqual(types, LESSON.EXPECTED_TYPES)
        self.assertEqual(len(rows), 12)
        self.assertEqual(len(grain), len(set(grain)))

    def test_cohort_size_is_fixed_from_all_registered_users(self) -> None:
        columns, _, rows = self.model()
        cohort_at = columns.index("cohort_month")
        size_at = columns.index("cohort_size")
        sizes: dict[date, set[int]] = {}
        for row in rows:
            sizes.setdefault(row[cohort_at], set()).add(row[size_at])
        self.assertEqual(
            sizes,
            {
                date(2025, 12, 1): {2},
                date(2026, 1, 1): {3},
                date(2026, 2, 1): {3},
            },
        )

    def test_reference_activity_rates_use_relative_periods(self) -> None:
        columns, rows = self.rows_by_grain()
        active_at = columns.index("active_users")
        rate_at = columns.index("activity_rate")
        december_one = rows[(date(2025, 12, 1), 1)]
        self.assertEqual(december_one[active_at], 2)
        self.assertEqual(december_one[rate_at], 1.0)
        self.assertEqual(rows[(date(2025, 12, 1), 2)][rate_at], 0.5)
        self.assertEqual(rows[(date(2026, 1, 1), 2)][rate_at], 0.3333)
        self.assertEqual(rows[(date(2026, 2, 1), 2)][rate_at], 0.3333)

    def test_period_zero_exists_even_when_registration_is_not_activity(self) -> None:
        columns, _, rows = self.model()
        period_at = columns.index("period_index")
        active_at = columns.index("active_users")
        period_zero = [row for row in rows if row[period_at] == 0]
        self.assertEqual(len(period_zero), 3)
        self.assertTrue(all(row[active_at] == 0 for row in period_zero))

    def test_multiple_real_events_in_one_user_month_count_once(self) -> None:
        self.connection.execute(
            """
            INSERT INTO events
            VALUES (
                'E0016',
                'U001',
                TIMESTAMPTZ '2026-01-20 10:00:00+00',
                'app_open'
            )
            """
        )
        LESSON.validate_inputs(self.connection)
        columns, rows = self.rows_by_grain()
        row = rows[(date(2025, 12, 1), 1)]
        self.assertEqual(row[columns.index("active_users")], 2)

    def test_exact_duplicate_delivery_does_not_change_matrix(self) -> None:
        before = self.model()[2]
        self.connection.execute(
            """
            INSERT INTO events
            SELECT * FROM events WHERE event_id = 'E0003'
            """
        )
        LESSON.validate_inputs(self.connection)
        after = self.model()[2]
        self.assertEqual(after, before)
        counts = self.connection.execute(
            "SELECT count(*), count(DISTINCT event_id) FROM events"
        ).fetchone()
        self.assertEqual(counts, (17, 15))

    def test_conflicting_delivery_of_same_event_id_is_rejected(self) -> None:
        self.connection.execute(
            """
            INSERT INTO events
            VALUES (
                'E0005',
                'U002',
                TIMESTAMPTZ '2026-02-05 08:00:00+00',
                'order_paid'
            )
            """
        )
        with self.assertRaisesRegex(ValueError, "conflicting deliveries"):
            LESSON.validate_inputs(self.connection)

    def test_unknown_user_is_rejected_before_join_can_hide_event(self) -> None:
        self.connection.execute(
            """
            INSERT INTO events
            VALUES (
                'orphan-event',
                'U999',
                TIMESTAMPTZ '2026-03-01 08:00:00+00',
                'app_open'
            )
            """
        )
        with self.assertRaisesRegex(ValueError, "unknown user"):
            LESSON.validate_inputs(self.connection)

    def test_activity_before_registration_is_rejected(self) -> None:
        self.connection.execute(
            """
            INSERT INTO events
            VALUES (
                'early-event',
                'U006',
                TIMESTAMPTZ '2026-01-10 08:00:00+00',
                'app_open'
            )
            """
        )
        with self.assertRaisesRegex(ValueError, "before registration"):
            LESSON.validate_inputs(self.connection)

    def test_explicit_cutoff_keeps_complete_month_with_zero_activity(self) -> None:
        self.connection.execute(
            """
            DELETE FROM events
            WHERE occurred_at >= TIMESTAMPTZ '2026-04-01 00:00:00+00'
            """
        )
        columns, _, rows = self.model()
        activity_at = columns.index("activity_month")
        active_at = columns.index("active_users")
        april = [row for row in rows if row[activity_at] == date(2026, 4, 1)]
        self.assertEqual(len(rows), 12)
        self.assertEqual(len(april), 3)
        self.assertTrue(all(row[active_at] == 0 for row in april))

    def test_activity_after_cutoff_is_not_mislabeled_as_complete(self) -> None:
        self.connection.execute(
            """
            INSERT INTO events
            VALUES (
                'may-event',
                'U001',
                TIMESTAMPTZ '2026-05-02 08:00:00+00',
                'app_open'
            )
            """
        )
        LESSON.validate_inputs(self.connection)
        columns, _, rows = self.model()
        activity_at = columns.index("activity_month")
        self.assertEqual(len(rows), 12)
        self.assertNotIn(date(2026, 5, 1), {row[activity_at] for row in rows})

    def test_event_outside_activity_allow_list_is_ignored(self) -> None:
        before = self.model()[2]
        self.connection.execute(
            """
            INSERT INTO events
            VALUES (
                'support-event',
                'U002',
                TIMESTAMPTZ '2026-02-12 08:00:00+00',
                'support_ticket'
            )
            """
        )
        LESSON.validate_inputs(self.connection)
        self.assertEqual(self.model()[2], before)

    def test_business_months_do_not_depend_on_session_timezone(self) -> None:
        utc_rows = self.model()[2]
        self.connection.execute("SET TimeZone = 'America/New_York'")
        new_york_rows = self.model()[2]
        self.assertEqual(new_york_rows, utc_rows)

    def test_duplicate_user_grain_is_rejected(self) -> None:
        self.connection.execute(
            """
            INSERT INTO users
            SELECT * FROM users WHERE user_id = 'U001'
            """
        )
        with self.assertRaisesRegex(ValueError, "users grain violation"):
            LESSON.validate_inputs(self.connection)

    def test_sql_artifact_owns_model_not_loading_or_cli(self) -> None:
        sql = re.sub(r"\s+", " ", MODEL_SQL_PATH.read_text(encoding="utf-8").lower())
        self.assertIn("'europe/moscow'::varchar as business_timezone", sql)
        self.assertIn("date '2026-04-01' as last_complete_activity_month", sql)
        self.assertIn("qualifying_event_names", sql)
        self.assertIn("user_month_activity", sql)
        self.assertIn("cross join lateral range", sql)
        self.assertIn("left join active_users", sql)
        self.assertNotIn("max(activity_month)", sql)
        for forbidden in ("read_csv", "read_parquet", "argparse", "json.dumps"):
            self.assertNotIn(forbidden, sql)

    def test_named_artifact_is_sql_and_runner_is_not_a_cli(self) -> None:
        lesson = json.loads(LESSON_PATH.read_text(encoding="utf-8"))
        artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        runner = CODE_PATH.read_text(encoding="utf-8")
        self.assertEqual(lesson["artifact"]["type"], "sql")
        self.assertEqual(
            lesson["artifact"]["path"],
            "outputs/monthly_cohort_activity.sql",
        )
        self.assertEqual(artifact["type"], "sql")
        self.assertEqual(
            artifact["path"],
            "outputs/monthly_cohort_activity.sql",
        )
        self.assertNotIn("argparse", runner)
        self.assertNotIn("sys.argv", runner)

    def test_quiz_activates_prerequisites_and_varies_answers(self) -> None:
        quiz = json.loads(QUIZ_PATH.read_text(encoding="utf-8"))
        pre = [question for question in quiz["questions"] if question["stage"] == "pre"]
        post = [question for question in quiz["questions"] if question["stage"] == "post"]
        self.assertGreaterEqual(len(pre), 2)
        self.assertGreaterEqual(len(post), 7)
        self.assertGreater(len({question["correct"] for question in post}), 2)
        joined_pre = " ".join(question["question"].lower() for question in pre)
        for term in ("business timezone", "left join", "grain"):
            self.assertIn(term, joined_pre)
        joined_post = " ".join(question["question"].lower() for question in post)
        for term in (
            "знаменатель",
            "event_id",
            "последнем завершённом месяце",
            "period_index",
            "period 0",
        ):
            self.assertIn(term, joined_post)


if __name__ == "__main__":
    unittest.main()
