from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
SPEC = ROOT / "outputs" / "activity_spec.json"
ARTIFACT = ROOT / "outputs" / "activity_calculator.py"


def load_calculator():
    spec = importlib.util.spec_from_file_location("activity_calculator", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manual_daily_active_users(events: list[dict[str, str]], active_names: set[str]) -> dict[str, int]:
    users_by_date: dict[str, set[str]] = {}
    for row in events:
        if row["event_name"] not in active_names:
            continue
        activity_date = row["occurred_at"][:10]
        users_by_date.setdefault(activity_date, set()).add(row["user_id"])
    return {day: len(users) for day, users in sorted(users_by_date.items())}


def main() -> None:
    calculator = load_calculator()
    events, event_columns = calculator.read_csv(EVENTS)
    users, user_columns = calculator.read_csv(USERS)
    tracking_plan = calculator.normalize_tracking_plan(calculator.read_json(TRACKING_PLAN))
    activity_spec = calculator.normalize_spec(calculator.read_json(SPEC))
    result = calculator.calculate_activity(
        events,
        event_columns,
        users,
        user_columns,
        tracking_plan,
        activity_spec,
    )
    summary = {
        "manual_daily_active_users": manual_daily_active_users(
            events,
            set(activity_spec["active_event_names"]),
        ),
        "calculator_summary": result.report["summary"],
        "valid": result.report["valid"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
