from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
ACTIVITY_SPEC = ROOT.parent / "03-activity" / "outputs" / "activity_spec.json"
SPEC = ROOT / "outputs" / "retention_spec.json"
ARTIFACT = ROOT / "outputs" / "retention_calculator.py"


def load_calculator():
    spec = importlib.util.spec_from_file_location("retention_calculator", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def manual_day_one_retention(events: list[dict[str, str]], users: list[dict[str, str]], return_names: set[str], timezone: ZoneInfo) -> dict[str, float | int]:
    cohort_users = {}
    for row in users:
        if row["is_test_user"].lower() == "true":
            continue
        cohort_users[row["user_id"]] = parse_timestamp(row["registered_at"]).astimezone(timezone).date()
    first_cohort_users = {user_id for user_id, cohort_date in cohort_users.items() if cohort_date.isoformat() == "2026-06-01"}
    retained = set()
    for row in events:
        if row["user_id"] not in first_cohort_users or row["event_name"] not in return_names:
            continue
        event_date = parse_timestamp(row["occurred_at"]).astimezone(timezone).date()
        age_day = (event_date - cohort_users[row["user_id"]]).days
        if age_day == 1:
            retained.add(row["user_id"])
    cohort_size = len(first_cohort_users)
    return {
        "cohort_size": cohort_size,
        "retained_users": len(retained),
        "retention_rate": len(retained) / cohort_size if cohort_size else 0.0,
    }


def main() -> None:
    calculator = load_calculator()
    events, event_columns = calculator.read_csv(EVENTS)
    users, user_columns = calculator.read_csv(USERS)
    tracking_plan = calculator.normalize_tracking_plan(calculator.read_json(TRACKING_PLAN))
    activity_spec = calculator.normalize_activity_spec(calculator.read_json(ACTIVITY_SPEC))
    retention_spec = calculator.normalize_spec(calculator.read_json(SPEC))
    result = calculator.calculate_retention(
        events,
        event_columns,
        users,
        user_columns,
        tracking_plan,
        activity_spec,
        retention_spec,
    )
    summary = {
        "manual_2026_06_01_day_1_exact": manual_day_one_retention(
            events,
            users,
            set(retention_spec["return_event_names"]),
            ZoneInfo(retention_spec["business_timezone"]),
        ),
        "calculator_summary": result.report["summary"],
        "exact_day_2026_06_01_day_1": next(
            row
            for row in result.table
            if row["retention_mode"] == "exact_day" and row["cohort_date"] == "2026-06-01" and row["age_day"] == "1"
        ),
        "on_or_after_2026_06_03_day_1": next(
            row
            for row in result.table
            if row["retention_mode"] == "on_or_after" and row["cohort_date"] == "2026-06-03" and row["age_day"] == "1"
        ),
        "valid": result.report["valid"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
