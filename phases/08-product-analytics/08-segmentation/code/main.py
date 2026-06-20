from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
SPEC = ROOT / "outputs" / "segmentation_spec.json"
ARTIFACT = ROOT / "outputs" / "segmentation_calculator.py"


def load_calculator():
    spec = importlib.util.spec_from_file_location("segmentation_calculator", ARTIFACT)
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


def manual_overall_activation(
    users: list[dict[str, str]],
    events: list[dict[str, str]],
    timezone: ZoneInfo,
    start: str,
    end: str,
) -> dict[str, str]:
    activated_users = {
        row["user_id"]
        for row in events
        if row["event_name"] == "feature_value_seen"
        and parse_timestamp(row["occurred_at"]).astimezone(timezone).date().isoformat() >= start
        and parse_timestamp(row["occurred_at"]).astimezone(timezone).date().isoformat() <= end
    }
    cohort_users = [
        row["user_id"]
        for row in users
        if row["is_test_user"].lower() != "true"
        and start <= parse_timestamp(row["registered_at"]).astimezone(timezone).date().isoformat() <= end
    ]
    activated = sum(1 for user_id in cohort_users if user_id in activated_users)
    return {
        "eligible_users": str(len(cohort_users)),
        "activated_users": str(activated),
        "activation_rate": f"{activated / len(cohort_users):.6f}" if cohort_users else "",
    }


def row_for(rows: list[dict[str, str]], row_type: str, dimension: str, segment_value: str) -> dict[str, str]:
    return next(
        row
        for row in rows
        if row["row_type"] == row_type
        and row["dimension"] == dimension
        and row["segment_value"] == segment_value
    )


def main() -> None:
    calculator = load_calculator()
    users, user_columns = calculator.read_csv(USERS)
    events, event_columns = calculator.read_csv(EVENTS)
    tracking_plan = calculator.normalize_tracking_plan(calculator.read_json(TRACKING_PLAN))
    segmentation_spec = calculator.normalize_spec(calculator.read_json(SPEC))
    result = calculator.calculate_segmentation(
        users,
        user_columns,
        events,
        event_columns,
        tracking_plan,
        segmentation_spec,
    )
    timezone = ZoneInfo(segmentation_spec["business_timezone"])
    summary = {
        "manual_baseline": manual_overall_activation(users, events, timezone, "2026-06-01", "2026-06-03"),
        "manual_comparison": manual_overall_activation(users, events, timezone, "2026-06-04", "2026-06-08"),
        "calculator_summary": result.report["summary"],
        "country_ru_baseline_is_exploratory": row_for(result.table, "segment_metric", "country", "RU"),
        "android_decomposition": row_for(result.table, "decomposition", "platform", "android"),
        "valid": result.report["valid"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
