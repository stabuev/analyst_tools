from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
SPEC = ROOT / "outputs" / "funnel_spec.json"
ARTIFACT = ROOT / "outputs" / "funnel_calculator.py"


def load_calculator():
    spec = importlib.util.spec_from_file_location("funnel_calculator", ARTIFACT)
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


def manual_paywall_to_trial_users(events: list[dict[str, str]], eligible_users: set[str]) -> dict[str, float | int]:
    paywall_time_by_user: dict[str, datetime] = {}
    trial_users: set[str] = set()
    for row in sorted(events, key=lambda item: (item["occurred_at"], item["event_id"])):
        user_id = row["user_id"]
        if user_id not in eligible_users:
            continue
        event_time = parse_timestamp(row["occurred_at"])
        if row["event_name"] == "paywall_viewed":
            paywall_time_by_user.setdefault(user_id, event_time)
        if row["event_name"] == "trial_started" and user_id in paywall_time_by_user:
            if event_time >= paywall_time_by_user[user_id]:
                trial_users.add(user_id)
    paywall_users = len(paywall_time_by_user)
    return {
        "paywall_users": paywall_users,
        "trial_users_after_paywall": len(trial_users),
        "conversion": len(trial_users) / paywall_users if paywall_users else 0.0,
    }


def main() -> None:
    calculator = load_calculator()
    events, event_columns = calculator.read_csv(EVENTS)
    users, user_columns = calculator.read_csv(USERS)
    tracking_plan = calculator.normalize_tracking_plan(calculator.read_json(TRACKING_PLAN))
    funnel_spec = calculator.normalize_spec(calculator.read_json(SPEC))
    eligible_users = {row["user_id"] for row in users if row["is_test_user"].lower() != "true"}
    result = calculator.calculate_funnels(
        events,
        event_columns,
        users,
        user_columns,
        tracking_plan,
        funnel_spec,
    )
    summary = {
        "manual_paywall_to_trial": manual_paywall_to_trial_users(events, eligible_users),
        "calculator_summary": result.report["summary"],
        "paywall_trial_rows": [
            row for row in result.table if row["funnel_id"] == "paywall_trial_user_strict_7d"
        ],
        "valid": result.report["valid"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
