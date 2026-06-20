from __future__ import annotations

import importlib.util
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
ACTIVITY_SPEC = ROOT.parent / "03-activity" / "outputs" / "activity_spec.json"
SPEC = ROOT / "outputs" / "cohort_spec.json"
ARTIFACT = ROOT / "outputs" / "cohort_calculator.py"


def load_calculator():
    spec = importlib.util.spec_from_file_location("cohort_calculator", ARTIFACT)
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


def manual_cohort_sizes(users: list[dict[str, str]], timezone: ZoneInfo) -> dict[str, int]:
    sizes: Counter[str] = Counter()
    for row in users:
        if row["is_test_user"].lower() == "true":
            continue
        cohort_date = parse_timestamp(row["registered_at"]).astimezone(timezone).date().isoformat()
        sizes[cohort_date] += 1
    return dict(sorted(sizes.items()))


def main() -> None:
    calculator = load_calculator()
    events, event_columns = calculator.read_csv(EVENTS)
    users, user_columns = calculator.read_csv(USERS)
    tracking_plan = calculator.normalize_tracking_plan(calculator.read_json(TRACKING_PLAN))
    activity_spec = calculator.normalize_activity_spec(calculator.read_json(ACTIVITY_SPEC))
    cohort_spec = calculator.normalize_spec(calculator.read_json(SPEC))
    result = calculator.calculate_cohorts(
        events,
        event_columns,
        users,
        user_columns,
        tracking_plan,
        activity_spec,
        cohort_spec,
    )
    summary = {
        "manual_cohort_sizes": manual_cohort_sizes(users, ZoneInfo(cohort_spec["business_timezone"])),
        "calculator_summary": result.report["summary"],
        "first_cohort_day_zero": next(
            row for row in result.table if row["cohort_date"] == "2026-06-01" and row["age_day"] == "0"
        ),
        "newest_cohort_age_two": next(
            row for row in result.table if row["cohort_date"] == "2026-06-08" and row["age_day"] == "2"
        ),
        "valid": result.report["valid"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
