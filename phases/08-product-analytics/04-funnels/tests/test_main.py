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
ARTIFACT = ROOT / "outputs" / "funnel_calculator.py"
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
SPEC_PATH = ROOT / "outputs" / "funnel_spec.json"
SAMPLE_FUNNEL = ROOT / "outputs" / "funnel.csv"
MODULE_SPEC = importlib.util.spec_from_file_location("funnel_calculator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CALCULATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CALCULATOR)


def load_inputs() -> tuple[list[dict[str, str]], list[str], list[dict[str, str]], list[str], dict, dict]:
    events, event_columns = CALCULATOR.read_csv(EVENTS)
    users, user_columns = CALCULATOR.read_csv(USERS)
    tracking_plan = CALCULATOR.normalize_tracking_plan(CALCULATOR.read_json(TRACKING_PLAN))
    funnel_spec = CALCULATOR.normalize_spec(CALCULATOR.read_json(SPEC_PATH))
    return events, event_columns, users, user_columns, tracking_plan, funnel_spec


def calculate(
    events: list[dict[str, str]] | None = None,
    users: list[dict[str, str]] | None = None,
    funnel_spec: dict | None = None,
    tracking_plan: dict | None = None,
) -> object:
    base_events, event_columns, base_users, user_columns, base_tracking_plan, base_spec = load_inputs()
    return CALCULATOR.calculate_funnels(
        base_events if events is None else events,
        event_columns,
        base_users if users is None else users,
        user_columns,
        base_tracking_plan if tracking_plan is None else tracking_plan,
        base_spec if funnel_spec is None else funnel_spec,
    )


def table_row(rows: list[dict[str, str]], funnel_id: str, step_id: str) -> dict[str, str]:
    return next(row for row in rows if row["funnel_id"] == funnel_id and row["step_id"] == step_id)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def one_paywall_funnel(base_spec: dict, unit: str = "user_id", ordering: str = "strict") -> dict:
    funnel_spec = copy.deepcopy(base_spec)
    paywall = next(funnel for funnel in funnel_spec["funnels"] if funnel["metric_id"] == "paywall_to_trial_conversion_7d")
    paywall = copy.deepcopy(paywall)
    paywall["unit"] = unit
    paywall["ordering"] = ordering
    paywall["funnel_id"] = f"paywall_trial_{unit}_{ordering}_7d"
    funnel_spec["funnels"] = [paywall]
    return funnel_spec


def add_user(users: list[dict[str, str]], user_id: str) -> list[dict[str, str]]:
    updated = copy.deepcopy(users)
    user = copy.deepcopy(updated[0])
    user.update({
        "user_id": user_id,
        "registered_at": "2026-06-06T09:55:00+03:00",
        "country": "RU",
        "acquisition_channel": "organic",
        "platform": "web",
        "is_test_user": "false",
    })
    updated.append(user)
    return updated


class FunnelCalculatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.events, self.event_columns, self.users, self.user_columns, self.tracking_plan, self.spec = load_inputs()

    def test_valid_tiny_funnels_have_expected_counts(self) -> None:
        result = calculate()
        self.assertTrue(result.report["valid"])
        self.assertEqual(result.report["summary"]["rows"], 6)
        self.assertEqual(result.report["summary"]["funnels"], 2)
        activation_id = "activation_user_strict_7d"
        self.assertEqual(table_row(result.table, activation_id, "account_created")["units"], "6")
        self.assertEqual(table_row(result.table, activation_id, "onboarding_started")["units"], "6")
        self.assertEqual(table_row(result.table, activation_id, "onboarding_completed")["units"], "5")
        self.assertEqual(table_row(result.table, activation_id, "feature_value_seen")["units"], "2")
        paywall_trial = table_row(result.table, "paywall_trial_user_strict_7d", "trial_started")
        self.assertEqual(paywall_trial["units"], "2")
        self.assertEqual(paywall_trial["conversion_from_start"], "0.500000")
        self.assertEqual(paywall_trial["dropoff_from_previous"], "2")

    def test_sample_funnel_csv_matches_calculated_table(self) -> None:
        result = calculate()
        with SAMPLE_FUNNEL.open(encoding="utf-8", newline="") as source:
            expected = list(csv.DictReader(source))
        self.assertEqual(result.table, expected)

    def test_duplicate_event_id_is_reported_and_deduplicated(self) -> None:
        events = copy.deepcopy(self.events)
        duplicate = copy.deepcopy(next(row for row in events if row["event_id"] == "E038"))
        events.append(duplicate)
        result = calculate(events=events)
        self.assertFalse(result.report["valid"])
        self.assertEqual(check(result.report, "event_ids_unique")["sample"], ["E038"])
        paywall_trial = table_row(result.table, "paywall_trial_user_strict_7d", "trial_started")
        self.assertEqual(paywall_trial["units"], "2")

    def test_funnel_events_must_exist_in_tracking_plan(self) -> None:
        funnel_spec = copy.deepcopy(self.spec)
        funnel_spec["funnels"][0]["steps"][-1]["event_name"] = "magic_value_seen"
        result = calculate(funnel_spec=funnel_spec)
        event_check = check(result.report, "funnel_events_in_tracking_plan")
        self.assertFalse(event_check["valid"])
        self.assertEqual(event_check["sample"], [{"funnel_id": "activation_user_strict_7d", "event_name": "magic_value_seen"}])

    def test_units_must_be_supported(self) -> None:
        funnel_spec = copy.deepcopy(self.spec)
        funnel_spec["funnels"][0]["unit"] = "account_id"
        result = calculate(funnel_spec=funnel_spec)
        unit_check = check(result.report, "funnel_units_supported")
        self.assertFalse(unit_check["valid"])
        self.assertEqual(unit_check["sample"], [{"funnel_id": "activation_user_strict_7d", "unit": "account_id"}])

    def test_conversion_windows_must_be_positive(self) -> None:
        funnel_spec = copy.deepcopy(self.spec)
        funnel_spec["funnels"][0]["conversion_window_minutes"] = 0
        result = calculate(funnel_spec=funnel_spec)
        window_check = check(result.report, "funnel_windows_positive")
        self.assertFalse(window_check["valid"])

    def test_step_event_without_user_id_is_rejected(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row["event_id"] == "E037":
                row["user_id"] = ""
        result = calculate(events=events)
        identity_check = check(result.report, "funnel_events_have_user_id")
        self.assertFalse(identity_check["valid"])
        self.assertEqual(identity_check["sample"][0]["event_id"], "E037")

    def test_strict_order_rejects_out_of_order_conversion_but_loose_counts_it(self) -> None:
        events = copy.deepcopy(self.events)
        users = add_user(self.users, "U008")
        trial = copy.deepcopy(next(row for row in events if row["event_id"] == "E038"))
        trial.update({
            "event_id": "E900",
            "user_id": "U008",
            "anonymous_id": "A008",
            "session_id": "S008",
            "occurred_at": "2026-06-06T10:00:00+03:00",
            "received_at": "2026-06-06T10:00:07+03:00",
        })
        paywall = copy.deepcopy(next(row for row in events if row["event_id"] == "E037"))
        paywall.update({
            "event_id": "E901",
            "user_id": "U008",
            "anonymous_id": "A008",
            "session_id": "S008",
            "occurred_at": "2026-06-06T10:05:00+03:00",
            "received_at": "2026-06-06T10:05:07+03:00",
        })
        events.extend([trial, paywall])
        strict_spec = one_paywall_funnel(self.spec, ordering="strict")
        loose_spec = one_paywall_funnel(self.spec, ordering="loose")
        strict = calculate(events=events, users=users, funnel_spec=strict_spec)
        loose = calculate(events=events, users=users, funnel_spec=loose_spec)
        self.assertEqual(table_row(strict.table, "paywall_trial_user_id_strict_7d", "paywall_viewed")["units"], "5")
        self.assertEqual(table_row(strict.table, "paywall_trial_user_id_strict_7d", "trial_started")["units"], "2")
        self.assertEqual(table_row(loose.table, "paywall_trial_user_id_loose_7d", "trial_started")["units"], "3")

    def test_session_unit_does_not_cross_sessions(self) -> None:
        events = copy.deepcopy(self.events)
        trial = copy.deepcopy(next(row for row in events if row["event_id"] == "E038"))
        trial.update({
            "event_id": "E910",
            "user_id": "U005",
            "anonymous_id": "A005",
            "session_id": "S006",
            "occurred_at": "2026-06-04T14:00:00+03:00",
            "received_at": "2026-06-04T14:00:07+03:00",
        })
        events.append(trial)
        user_spec = one_paywall_funnel(self.spec, unit="user_id")
        session_spec = one_paywall_funnel(self.spec, unit="session_id")
        user_result = calculate(events=events, funnel_spec=user_spec)
        session_result = calculate(events=events, funnel_spec=session_spec)
        self.assertEqual(table_row(user_result.table, "paywall_trial_user_id_strict_7d", "trial_started")["units"], "3")
        self.assertEqual(table_row(session_result.table, "paywall_trial_session_id_strict_7d", "trial_started")["units"], "2")

    def test_user_day_unit_does_not_cross_calendar_dates(self) -> None:
        events = copy.deepcopy(self.events)
        trial = copy.deepcopy(next(row for row in events if row["event_id"] == "E038"))
        trial.update({
            "event_id": "E920",
            "user_id": "U005",
            "anonymous_id": "A005",
            "session_id": "S005",
            "occurred_at": "2026-06-05T09:00:00+03:00",
            "received_at": "2026-06-05T09:00:07+03:00",
        })
        events.append(trial)
        user_spec = one_paywall_funnel(self.spec, unit="user_id")
        user_day_spec = one_paywall_funnel(self.spec, unit="user_day")
        user_result = calculate(events=events, funnel_spec=user_spec)
        user_day_result = calculate(events=events, funnel_spec=user_day_spec)
        self.assertEqual(table_row(user_result.table, "paywall_trial_user_id_strict_7d", "trial_started")["units"], "3")
        self.assertEqual(table_row(user_day_result.table, "paywall_trial_user_day_strict_7d", "trial_started")["units"], "2")

    def test_late_step_events_are_reported(self) -> None:
        events = copy.deepcopy(self.events)
        for row in events:
            if row["event_id"] == "E038":
                row["received_at"] = "2026-06-10T15:12:07+03:00"
        result = calculate(events=events)
        late_check = check(result.report, "late_events_within_policy")
        self.assertFalse(late_check["valid"])
        self.assertEqual(late_check["sample"][0]["event_id"], "E038")

    def test_cli_writes_funnel_csv_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "funnel.csv"
            report_path = root / "funnel-report.json"
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
                self.assertEqual(len(list(csv.DictReader(source))), 6)

            invalid_spec_path = root / "bad_funnel_spec.json"
            invalid_spec = copy.deepcopy(self.spec)
            invalid_spec["funnels"][0]["unit"] = "account_id"
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
                    "--spec",
                    invalid_spec_path,
                    "--output",
                    root / "bad-funnel.csv",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(invalid_result.returncode, 1, invalid_result.stderr)
            self.assertFalse(json.loads(invalid_result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
