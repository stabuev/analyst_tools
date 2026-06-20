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
ARTIFACT = ROOT / "outputs" / "activity_calculator.py"
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
SPEC_PATH = ROOT / "outputs" / "activity_spec.json"
SAMPLE_ACTIVITY = ROOT / "outputs" / "activity.csv"
SPEC = importlib.util.spec_from_file_location("activity_calculator", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CALCULATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CALCULATOR)


def load_inputs() -> tuple[list[dict[str, str]], list[str], list[dict[str, str]], list[str], dict, dict]:
    events, event_columns = CALCULATOR.read_csv(EVENTS)
    users, user_columns = CALCULATOR.read_csv(USERS)
    tracking_plan = CALCULATOR.normalize_tracking_plan(CALCULATOR.read_json(TRACKING_PLAN))
    activity_spec = CALCULATOR.normalize_spec(CALCULATOR.read_json(SPEC_PATH))
    return events, event_columns, users, user_columns, tracking_plan, activity_spec


def calculate(
    events: list[dict[str, str]] | None = None,
    users: list[dict[str, str]] | None = None,
    activity_spec: dict | None = None,
) -> object:
    base_events, event_columns, base_users, user_columns, tracking_plan, base_spec = load_inputs()
    return CALCULATOR.calculate_activity(
        events or base_events,
        event_columns,
        users or base_users,
        user_columns,
        tracking_plan,
        activity_spec or base_spec,
    )


def table_row(rows: list[dict[str, str]], activity_date: str, window_days: int) -> dict[str, str]:
    return next(row for row in rows if row["activity_date"] == activity_date and row["window_days"] == str(window_days))


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class ActivityCalculatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.events, self.event_columns, self.users, self.user_columns, self.tracking_plan, self.spec = load_inputs()

    def test_valid_tiny_activity_has_daily_and_rolling_windows(self) -> None:
        result = calculate()
        self.assertTrue(result.report["valid"])
        self.assertEqual(result.report["summary"]["rows"], 18)
        self.assertEqual(result.report["summary"]["eligible_users"], 7)
        self.assertEqual(result.report["summary"]["excluded_test_users"], 1)
        day_one = table_row(result.table, "2026-06-01", 1)
        self.assertEqual(day_one["active_users"], "2")
        self.assertEqual(day_one["activity_rate"], "1.000000")
        rolling_last = table_row(result.table, "2026-06-09", 7)
        self.assertEqual(rolling_last["active_users"], "3")
        self.assertEqual(rolling_last["activity_rate"], "0.428571")

    def test_sample_activity_csv_matches_calculated_table(self) -> None:
        result = calculate()
        with SAMPLE_ACTIVITY.open(encoding="utf-8", newline="") as source:
            expected = list(csv.DictReader(source))
        self.assertEqual(result.table, expected)

    def test_dates_without_active_events_are_kept(self) -> None:
        result = calculate()
        june_six = table_row(result.table, "2026-06-06", 1)
        self.assertEqual(june_six["eligible_users"], "6")
        self.assertEqual(june_six["active_users"], "0")
        self.assertEqual(june_six["active_event_count"], "0")

    def test_seven_day_windows_are_flagged_until_history_is_complete(self) -> None:
        result = calculate()
        self.assertEqual(table_row(result.table, "2026-06-06", 7)["is_complete_window"], "false")
        self.assertEqual(table_row(result.table, "2026-06-07", 7)["is_complete_window"], "true")

    def test_test_users_do_not_enter_denominator_or_activity(self) -> None:
        events = copy.deepcopy(self.events)
        test_event = copy.deepcopy(events[0])
        test_event.update({
            "event_id": "E999",
            "user_id": "U999",
            "event_name": "feature_value_seen",
            "occurred_at": "2026-06-08T16:05:00+03:00",
        })
        events.append(test_event)
        result = calculate(events=events)
        june_eight = table_row(result.table, "2026-06-08", 1)
        self.assertEqual(june_eight["eligible_users"], "7")
        self.assertEqual(june_eight["active_users"], "1")
        self.assertEqual(june_eight["active_event_count"], "3")

    def test_duplicate_event_id_is_reported_and_deduplicated(self) -> None:
        events = copy.deepcopy(self.events)
        duplicate = copy.deepcopy(next(row for row in events if row["event_id"] == "E031"))
        events.append(duplicate)
        result = calculate(events=events)
        self.assertFalse(result.report["valid"])
        self.assertEqual(check(result.report, "event_ids_unique")["sample"], ["E031"])
        june_five = table_row(result.table, "2026-06-05", 1)
        self.assertEqual(june_five["active_event_count"], "3")

    def test_active_event_without_user_id_is_rejected(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row["event_id"] == "E005":
                row["user_id"] = ""
        result = calculate(events=events)
        identity_check = check(result.report, "active_events_have_user_id")
        self.assertFalse(identity_check["valid"])
        self.assertEqual(identity_check["sample"][0]["event_id"], "E005")

    def test_activity_spec_active_events_must_exist_in_tracking_plan(self) -> None:
        activity_spec = copy.deepcopy(self.spec)
        activity_spec["active_event_names"].append("daily_active_user")
        result = calculate(activity_spec=activity_spec)
        event_check = check(result.report, "active_events_in_tracking_plan")
        self.assertFalse(event_check["valid"])
        self.assertEqual(event_check["sample"], ["daily_active_user"])

    def test_activity_windows_must_be_positive(self) -> None:
        activity_spec = copy.deepcopy(self.spec)
        activity_spec["windows_days"] = [1, 0]
        result = calculate(activity_spec=activity_spec)
        window_check = check(result.report, "activity_windows_positive")
        self.assertFalse(window_check["valid"])

    def test_business_timezone_controls_activity_date(self) -> None:
        events = copy.deepcopy(self.events)
        late_utc_event = copy.deepcopy(events[0])
        late_utc_event.update({
            "event_id": "E900",
            "user_id": "U001",
            "event_name": "feature_value_seen",
            "occurred_at": "2026-06-01T22:30:00+00:00",
        })
        events.append(late_utc_event)
        result = calculate(events=events)
        june_two = table_row(result.table, "2026-06-02", 1)
        self.assertEqual(june_two["active_users"], "2")
        self.assertEqual(june_two["active_event_count"], "2")

    def test_cli_writes_activity_csv_and_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "activity.csv"
            report_path = root / "activity-report.json"
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
                self.assertEqual(len(list(csv.DictReader(source))), 18)

    def test_cli_returns_nonzero_for_invalid_activity_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "activity_spec.json"
            output_path = root / "activity.csv"
            activity_spec = copy.deepcopy(self.spec)
            activity_spec["active_event_names"].append("daily_active_user")
            spec_path.write_text(json.dumps(activity_spec, ensure_ascii=False, indent=2), encoding="utf-8")
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
                    "--spec",
                    spec_path,
                    "--output",
                    output_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
