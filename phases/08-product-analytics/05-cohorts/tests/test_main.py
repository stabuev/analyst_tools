from __future__ import annotations

import copy
import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "cohort_calculator.py"
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
ACTIVITY_SPEC = ROOT.parent / "03-activity" / "outputs" / "activity_spec.json"
SPEC_PATH = ROOT / "outputs" / "cohort_spec.json"
SAMPLE_COHORTS = ROOT / "outputs" / "cohorts.csv"
MODULE_SPEC = importlib.util.spec_from_file_location("cohort_calculator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CALCULATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CALCULATOR)


def load_inputs() -> tuple[list[dict[str, str]], list[str], list[dict[str, str]], list[str], dict, dict, dict]:
    events, event_columns = CALCULATOR.read_csv(EVENTS)
    users, user_columns = CALCULATOR.read_csv(USERS)
    tracking_plan = CALCULATOR.normalize_tracking_plan(CALCULATOR.read_json(TRACKING_PLAN))
    activity_spec = CALCULATOR.normalize_activity_spec(CALCULATOR.read_json(ACTIVITY_SPEC))
    cohort_spec = CALCULATOR.normalize_spec(CALCULATOR.read_json(SPEC_PATH))
    return events, event_columns, users, user_columns, tracking_plan, activity_spec, cohort_spec


def calculate(
    events: list[dict[str, str]] | None = None,
    users: list[dict[str, str]] | None = None,
    tracking_plan: dict | None = None,
    activity_spec: dict | None = None,
    cohort_spec: dict | None = None,
) -> object:
    base_events, event_columns, base_users, user_columns, base_tracking_plan, base_activity_spec, base_spec = load_inputs()
    return CALCULATOR.calculate_cohorts(
        base_events if events is None else events,
        event_columns,
        base_users if users is None else users,
        user_columns,
        base_tracking_plan if tracking_plan is None else tracking_plan,
        base_activity_spec if activity_spec is None else activity_spec,
        base_spec if cohort_spec is None else cohort_spec,
    )


def table_row(rows: list[dict[str, str]], cohort_date: str, age_day: int) -> dict[str, str]:
    return next(row for row in rows if row["cohort_date"] == cohort_date and row["age_day"] == str(age_day))


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def add_user(users: list[dict[str, str]], user_id: str, registered_at: str) -> list[dict[str, str]]:
    updated = copy.deepcopy(users)
    user = copy.deepcopy(updated[0])
    user.update({
        "user_id": user_id,
        "registered_at": registered_at,
        "country": "RU",
        "acquisition_channel": "organic",
        "platform": "web",
        "is_test_user": "false",
    })
    updated.append(user)
    return updated


class CohortCalculatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.events, self.event_columns, self.users, self.user_columns, self.tracking_plan, self.activity_spec, self.spec = load_inputs()

    def test_valid_tiny_cohort_matrix_has_expected_counts(self) -> None:
        result = calculate()
        self.assertTrue(result.report["valid"])
        self.assertEqual(result.report["summary"]["rows"], 48)
        self.assertEqual(result.report["summary"]["cohorts"], 6)
        self.assertEqual(result.report["summary"]["eligible_users"], 7)
        self.assertEqual(result.report["summary"]["excluded_test_users"], 1)
        self.assertEqual(result.report["summary"]["complete_windows"], 36)
        self.assertEqual(result.report["summary"]["incomplete_windows"], 12)
        day_zero = table_row(result.table, "2026-06-01", 0)
        self.assertEqual(day_zero["cohort_size"], "2")
        self.assertEqual(day_zero["active_users"], "2")
        self.assertEqual(day_zero["activity_rate"], "1.000000")
        self.assertEqual(day_zero["active_event_count"], "6")
        self.assertEqual(table_row(result.table, "2026-06-03", 0)["activity_rate"], "0.000000")
        self.assertEqual(table_row(result.table, "2026-06-08", 0)["active_event_count"], "3")

    def test_sample_cohorts_csv_matches_calculated_table(self) -> None:
        result = calculate()
        with SAMPLE_COHORTS.open(encoding="utf-8", newline="") as source:
            expected = list(csv.DictReader(source))
        self.assertEqual(result.table, expected)

    def test_full_grid_keeps_zero_activity_cells(self) -> None:
        result = calculate()
        june_one_age_one = table_row(result.table, "2026-06-01", 1)
        self.assertEqual(june_one_age_one["activity_date"], "2026-06-02")
        self.assertEqual(june_one_age_one["active_users"], "0")
        self.assertEqual(june_one_age_one["activity_rate"], "0.000000")

    def test_incomplete_windows_have_blank_rate(self) -> None:
        result = calculate()
        incomplete = table_row(result.table, "2026-06-03", 7)
        self.assertEqual(incomplete["is_complete_window"], "false")
        self.assertEqual(incomplete["activity_rate"], "")
        self.assertEqual(incomplete["active_users"], "0")

    def test_test_users_do_not_enter_cohorts_or_activity_counts(self) -> None:
        events = copy.deepcopy(self.events)
        test_active = copy.deepcopy(next(row for row in events if row["event_id"] == "E031"))
        test_active.update({
            "event_id": "E900",
            "user_id": "U999",
            "anonymous_id": "A999",
            "session_id": "S999",
            "occurred_at": "2026-06-08T16:10:00+03:00",
            "received_at": "2026-06-08T16:10:07+03:00",
        })
        events.append(test_active)
        result = calculate(events=events)
        self.assertEqual(result.report["summary"]["eligible_users"], 7)
        self.assertEqual(table_row(result.table, "2026-06-08", 0)["active_event_count"], "3")

    def test_duplicate_event_id_is_reported_and_deduplicated(self) -> None:
        events = copy.deepcopy(self.events)
        duplicate = copy.deepcopy(next(row for row in events if row["event_id"] == "E031"))
        events.append(duplicate)
        result = calculate(events=events)
        self.assertFalse(result.report["valid"])
        self.assertEqual(check(result.report, "event_ids_unique")["sample"], ["E031"])
        self.assertEqual(table_row(result.table, "2026-06-05", 0)["active_event_count"], "3")

    def test_active_event_without_user_id_is_rejected(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row["event_id"] == "E031":
                row["user_id"] = ""
        result = calculate(events=events)
        identity_check = check(result.report, "active_events_have_user_id")
        self.assertFalse(identity_check["valid"])
        self.assertEqual(identity_check["sample"][0]["event_id"], "E031")

    def test_activity_events_must_exist_in_tracking_plan(self) -> None:
        activity_spec = copy.deepcopy(self.activity_spec)
        activity_spec["active_event_names"].append("weekly_report_opened")
        result = calculate(activity_spec=activity_spec)
        event_check = check(result.report, "active_events_in_tracking_plan")
        self.assertFalse(event_check["valid"])
        self.assertEqual(event_check["sample"], ["weekly_report_opened"])

    def test_age_days_must_be_contiguous_from_zero(self) -> None:
        cohort_spec = copy.deepcopy(self.spec)
        cohort_spec["age_days"] = [0, 1, 3]
        result = calculate(cohort_spec=cohort_spec)
        age_check = check(result.report, "cohort_age_days_contiguous")
        self.assertFalse(age_check["valid"])

    def test_observation_end_date_controls_completeness(self) -> None:
        cohort_spec = copy.deepcopy(self.spec)
        cohort_spec["observation_end_date"] = "2026-06-08"
        result = calculate(cohort_spec=cohort_spec)
        self.assertEqual(result.report["summary"]["complete_windows"], 31)
        self.assertEqual(table_row(result.table, "2026-06-02", 7)["is_complete_window"], "false")
        self.assertEqual(table_row(result.table, "2026-06-02", 7)["activity_rate"], "")

    def test_business_timezone_controls_cohort_date(self) -> None:
        users = add_user(self.users, "U008", "2026-06-01T22:30:00+00:00")
        events = copy.deepcopy(self.events)
        event = copy.deepcopy(next(row for row in events if row["event_id"] == "E031"))
        event.update({
            "event_id": "E910",
            "user_id": "U008",
            "anonymous_id": "A008",
            "session_id": "S008",
            "occurred_at": "2026-06-02T00:05:00+03:00",
            "received_at": "2026-06-02T00:05:07+03:00",
        })
        events.append(event)
        result = calculate(events=events, users=users)
        june_two = table_row(result.table, "2026-06-02", 0)
        self.assertEqual(june_two["cohort_size"], "2")
        self.assertEqual(june_two["active_users"], "2")
        self.assertEqual(june_two["active_event_count"], "2")

    def test_late_active_event_is_reported(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row["event_id"] == "E031":
                row["received_at"] = "2026-06-08T14:56:07+03:00"
        result = calculate(events=events)
        late_check = check(result.report, "late_events_within_policy")
        self.assertFalse(late_check["valid"])
        self.assertEqual(late_check["sample"][0]["event_id"], "E031")

    def test_cli_writes_cohorts_csv_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "cohorts.csv"
            report_path = root / "cohort-report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--events",
                    EVENTS,
                    "--users",
                    USERS,
                    "--tracking-plan",
                    TRACKING_PLAN,
                    "--activity-spec",
                    ACTIVITY_SPEC,
                    "--spec",
                    SPEC_PATH,
                    "--output",
                    output_path,
                    "--report",
                    report_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["valid"])
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text()))
            with output_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 48)

            invalid_spec = copy.deepcopy(self.spec)
            invalid_spec["period"] = "week"
            invalid_spec_path = root / "bad_cohort_spec.json"
            invalid_spec_path.write_text(json.dumps(invalid_spec, ensure_ascii=False, indent=2), encoding="utf-8")
            invalid_result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--events",
                    EVENTS,
                    "--users",
                    USERS,
                    "--tracking-plan",
                    TRACKING_PLAN,
                    "--activity-spec",
                    ACTIVITY_SPEC,
                    "--spec",
                    invalid_spec_path,
                    "--output",
                    root / "bad-cohorts.csv",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(invalid_result.returncode, 1, invalid_result.stderr)
            self.assertFalse(json.loads(invalid_result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
