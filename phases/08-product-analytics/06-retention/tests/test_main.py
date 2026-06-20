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
ARTIFACT = ROOT / "outputs" / "retention_calculator.py"
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
ACTIVITY_SPEC = ROOT.parent / "03-activity" / "outputs" / "activity_spec.json"
SPEC_PATH = ROOT / "outputs" / "retention_spec.json"
SAMPLE_RETENTION = ROOT / "outputs" / "retention.csv"
MODULE_SPEC = importlib.util.spec_from_file_location("retention_calculator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CALCULATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CALCULATOR)


def load_inputs() -> tuple[list[dict[str, str]], list[str], list[dict[str, str]], list[str], dict, dict, dict]:
    events, event_columns = CALCULATOR.read_csv(EVENTS)
    users, user_columns = CALCULATOR.read_csv(USERS)
    tracking_plan = CALCULATOR.normalize_tracking_plan(CALCULATOR.read_json(TRACKING_PLAN))
    activity_spec = CALCULATOR.normalize_activity_spec(CALCULATOR.read_json(ACTIVITY_SPEC))
    retention_spec = CALCULATOR.normalize_spec(CALCULATOR.read_json(SPEC_PATH))
    return events, event_columns, users, user_columns, tracking_plan, activity_spec, retention_spec


def calculate(
    events: list[dict[str, str]] | None = None,
    users: list[dict[str, str]] | None = None,
    tracking_plan: dict | None = None,
    activity_spec: dict | None = None,
    retention_spec: dict | None = None,
) -> object:
    base_events, event_columns, base_users, user_columns, base_tracking_plan, base_activity_spec, base_spec = load_inputs()
    return CALCULATOR.calculate_retention(
        base_events if events is None else events,
        event_columns,
        base_users if users is None else users,
        user_columns,
        base_tracking_plan if tracking_plan is None else tracking_plan,
        base_activity_spec if activity_spec is None else activity_spec,
        base_spec if retention_spec is None else retention_spec,
    )


def table_row(rows: list[dict[str, str]], mode: str, cohort_date: str, age_day: int) -> dict[str, str]:
    return next(
        row
        for row in rows
        if row["retention_mode"] == mode and row["cohort_date"] == cohort_date and row["age_day"] == str(age_day)
    )


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def add_return_event(
    events: list[dict[str, str]],
    event_id: str,
    user_id: str,
    session_id: str,
    occurred_at: str,
    event_name: str = "feature_value_seen",
) -> list[dict[str, str]]:
    updated = copy.deepcopy(events)
    event = copy.deepcopy(next(row for row in events if row["event_id"] == "E031"))
    event.update({
        "event_id": event_id,
        "user_id": user_id,
        "anonymous_id": f"A{user_id[1:]}",
        "session_id": session_id,
        "event_name": event_name,
        "occurred_at": occurred_at,
        "received_at": occurred_at.replace(":00+03:00", ":07+03:00"),
    })
    updated.append(event)
    return updated


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


class RetentionCalculatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.events, self.event_columns, self.users, self.user_columns, self.tracking_plan, self.activity_spec, self.spec = load_inputs()

    def test_valid_tiny_retention_has_expected_grid_and_zero_returns(self) -> None:
        result = calculate()
        self.assertTrue(result.report["valid"])
        self.assertEqual(result.report["summary"]["rows"], 84)
        self.assertEqual(result.report["summary"]["cohorts"], 6)
        self.assertEqual(result.report["summary"]["eligible_users"], 7)
        self.assertEqual(result.report["summary"]["complete_windows"], 44)
        self.assertEqual(result.report["summary"]["incomplete_windows"], 40)
        exact = table_row(result.table, "exact_day", "2026-06-01", 1)
        self.assertEqual(exact["cohort_size"], "2")
        self.assertEqual(exact["retained_users"], "0")
        self.assertEqual(exact["retention_rate"], "0.000000")
        on_or_after = table_row(result.table, "on_or_after", "2026-06-01", 1)
        self.assertEqual(on_or_after["return_window_start"], "2026-06-02")
        self.assertEqual(on_or_after["return_window_end"], "2026-06-08")
        self.assertEqual(on_or_after["retention_rate"], "0.000000")

    def test_sample_retention_csv_matches_calculated_table(self) -> None:
        result = calculate()
        with SAMPLE_RETENTION.open(encoding="utf-8", newline="") as source:
            expected = list(csv.DictReader(source))
        self.assertEqual(result.table, expected)

    def test_start_day_activity_is_not_counted_as_return(self) -> None:
        result = calculate()
        day_one = table_row(result.table, "exact_day", "2026-06-01", 1)
        self.assertEqual(day_one["return_event_count"], "0")
        self.assertEqual(day_one["retained_users"], "0")

    def test_exact_day_and_on_or_after_have_different_semantics(self) -> None:
        events = add_return_event(self.events, "E900", "U001", "S900", "2026-06-03T09:00:00+03:00")
        events = add_return_event(events, "E901", "U002", "S901", "2026-06-06T09:00:00+03:00")
        result = calculate(events=events)
        self.assertEqual(table_row(result.table, "exact_day", "2026-06-01", 2)["retained_users"], "1")
        self.assertEqual(table_row(result.table, "exact_day", "2026-06-01", 2)["retention_rate"], "0.500000")
        self.assertEqual(table_row(result.table, "exact_day", "2026-06-01", 3)["retained_users"], "0")
        self.assertEqual(table_row(result.table, "exact_day", "2026-06-01", 5)["retained_users"], "1")
        self.assertEqual(table_row(result.table, "on_or_after", "2026-06-01", 1)["retained_users"], "2")
        self.assertEqual(table_row(result.table, "on_or_after", "2026-06-01", 1)["retention_rate"], "1.000000")
        self.assertEqual(table_row(result.table, "on_or_after", "2026-06-01", 3)["retained_users"], "1")
        self.assertEqual(table_row(result.table, "on_or_after", "2026-06-01", 6)["retained_users"], "0")

    def test_on_or_after_requires_complete_horizon(self) -> None:
        result = calculate()
        exact = table_row(result.table, "exact_day", "2026-06-03", 1)
        on_or_after = table_row(result.table, "on_or_after", "2026-06-03", 1)
        self.assertEqual(exact["is_complete_window"], "true")
        self.assertEqual(exact["retention_rate"], "0.000000")
        self.assertEqual(on_or_after["is_complete_window"], "false")
        self.assertEqual(on_or_after["retention_rate"], "")

    def test_duplicate_return_event_is_reported_and_deduplicated(self) -> None:
        events = add_return_event(self.events, "E900", "U001", "S900", "2026-06-03T09:00:00+03:00")
        duplicate = copy.deepcopy(next(row for row in events if row["event_id"] == "E900"))
        events.append(duplicate)
        result = calculate(events=events)
        self.assertFalse(result.report["valid"])
        self.assertEqual(check(result.report, "event_ids_unique")["sample"], ["E900"])
        exact = table_row(result.table, "exact_day", "2026-06-01", 2)
        self.assertEqual(exact["retained_users"], "1")
        self.assertEqual(exact["return_event_count"], "1")

    def test_return_event_without_user_id_is_rejected(self) -> None:
        events = add_return_event(self.events, "E900", "U001", "S900", "2026-06-03T09:00:00+03:00")
        events[-1]["user_id"] = ""
        result = calculate(events=events)
        identity_check = check(result.report, "return_events_have_user_id")
        self.assertFalse(identity_check["valid"])
        self.assertEqual(identity_check["sample"][0]["event_id"], "E900")

    def test_return_events_must_exist_in_activity_spec_and_tracking_plan(self) -> None:
        retention_spec = copy.deepcopy(self.spec)
        retention_spec["return_event_names"].append("weekly_report_opened")
        result = calculate(retention_spec=retention_spec)
        self.assertFalse(check(result.report, "return_events_in_activity_spec")["valid"])
        self.assertFalse(check(result.report, "return_events_in_tracking_plan")["valid"])

    def test_age_days_must_be_contiguous_from_one(self) -> None:
        retention_spec = copy.deepcopy(self.spec)
        retention_spec["age_days"] = [1, 2, 4]
        result = calculate(retention_spec=retention_spec)
        self.assertFalse(check(result.report, "retention_age_days_contiguous")["valid"])

    def test_retention_modes_must_be_supported(self) -> None:
        retention_spec = copy.deepcopy(self.spec)
        retention_spec["retention_modes"] = ["exact_day", "rolling"]
        result = calculate(retention_spec=retention_spec)
        self.assertFalse(check(result.report, "retention_modes_supported")["valid"])

    def test_observation_end_date_controls_completeness(self) -> None:
        retention_spec = copy.deepcopy(self.spec)
        retention_spec["observation_end_date"] = "2026-06-08"
        result = calculate(retention_spec=retention_spec)
        self.assertEqual(table_row(result.table, "exact_day", "2026-06-02", 6)["is_complete_window"], "true")
        self.assertEqual(table_row(result.table, "exact_day", "2026-06-02", 7)["is_complete_window"], "false")
        self.assertEqual(table_row(result.table, "on_or_after", "2026-06-02", 1)["is_complete_window"], "false")

    def test_business_timezone_controls_start_cohort_date(self) -> None:
        users = add_user(self.users, "U008", "2026-06-01T22:30:00+00:00")
        events = add_return_event(self.events, "E900", "U008", "S900", "2026-06-03T00:05:00+03:00")
        result = calculate(events=events, users=users)
        row = table_row(result.table, "exact_day", "2026-06-02", 1)
        self.assertEqual(row["cohort_size"], "2")
        self.assertEqual(row["retained_users"], "1")
        self.assertEqual(row["retention_rate"], "0.500000")

    def test_late_return_event_is_reported(self) -> None:
        events = add_return_event(self.events, "E900", "U001", "S900", "2026-06-03T09:00:00+03:00")
        events[-1]["received_at"] = "2026-06-05T09:00:07+03:00"
        result = calculate(events=events)
        late_check = check(result.report, "late_events_within_policy")
        self.assertFalse(late_check["valid"])
        self.assertEqual(late_check["sample"][0]["event_id"], "E900")

    def test_cli_writes_retention_csv_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "retention.csv"
            report_path = root / "retention-report.json"
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
                self.assertEqual(len(list(csv.DictReader(source))), 84)

            invalid_spec = copy.deepcopy(self.spec)
            invalid_spec["retention_modes"] = ["rolling"]
            invalid_spec_path = root / "bad_retention_spec.json"
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
                    root / "bad-retention.csv",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(invalid_result.returncode, 1, invalid_result.stderr)
            self.assertFalse(json.loads(invalid_result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
