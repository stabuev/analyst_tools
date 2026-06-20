from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REQUIRED_EVENT_COLUMNS = {
    "event_id",
    "user_id",
    "event_name",
    "occurred_at",
}
REQUIRED_USER_COLUMNS = {
    "user_id",
    "registered_at",
    "is_test_user",
}
REQUIRED_SPEC_FIELDS = {
    "metric_id",
    "grain",
    "active_event_names",
    "windows_days",
    "business_timezone",
    "exclude_test_users",
}
OUTPUT_COLUMNS = [
    "activity_date",
    "window_days",
    "is_complete_window",
    "eligible_users",
    "active_users",
    "activity_rate",
    "active_event_count",
]


class ActivityResult:
    def __init__(self, table: list[dict[str, str]], report: dict[str, Any]) -> None:
        self.table = table
        self.report = report


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"id": check_id, "valid": True, "observed": observed, "expected": expected, "sample": []}


def failed(check_id: str, observed: Any, expected: Any, sample: list[Any] | None = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def parse_timestamp(value: str) -> datetime:
    if not value:
        raise ValueError("empty timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def daterange(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def normalize_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("activity spec must be an object")
    return value


def normalize_tracking_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise ValueError("tracking plan must be an object with an events list")
    return value


def duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def validate_configuration(spec: dict[str, Any], tracking_plan: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing_fields = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing_fields:
        checks.append(failed("activity_spec_required_fields", missing_fields, "all required activity spec fields"))
    else:
        checks.append(passed("activity_spec_required_fields", len(REQUIRED_SPEC_FIELDS), "all required activity spec fields"))

    active_events = spec.get("active_event_names", [])
    if not isinstance(active_events, list) or not active_events or not all(isinstance(name, str) and name for name in active_events):
        checks.append(failed("active_events_declared", active_events, "non-empty list of event names"))
        active_events = []
    else:
        checks.append(passed("active_events_declared", len(active_events), "non-empty list of event names"))

    plan_names = {
        event.get("event_name")
        for event in tracking_plan.get("events", [])
        if isinstance(event, dict) and isinstance(event.get("event_name"), str)
    }
    unknown_active_events = sorted(set(active_events) - plan_names)
    if unknown_active_events:
        checks.append(failed("active_events_in_tracking_plan", len(unknown_active_events), "active events exist in tracking plan", unknown_active_events))
    else:
        checks.append(passed("active_events_in_tracking_plan", len(active_events), "active events exist in tracking plan"))

    windows = spec.get("windows_days", [])
    if not isinstance(windows, list) or not windows or not all(isinstance(window, int) and window > 0 for window in windows):
        checks.append(failed("activity_windows_positive", windows, "positive integer windows_days"))
    else:
        checks.append(passed("activity_windows_positive", windows, "positive integer windows_days"))

    if spec.get("grain") == "user_id":
        checks.append(passed("activity_grain_user_id", spec.get("grain"), "user_id"))
    else:
        checks.append(failed("activity_grain_user_id", spec.get("grain"), "user_id"))

    try:
        ZoneInfo(str(spec.get("business_timezone", "")))
    except ZoneInfoNotFoundError:
        checks.append(failed("business_timezone_valid", spec.get("business_timezone"), "IANA timezone name"))
    else:
        checks.append(passed("business_timezone_valid", spec.get("business_timezone"), "IANA timezone name"))
    return checks


def validate_inputs(
    events: list[dict[str, str]],
    event_columns: list[str],
    users: list[dict[str, str]],
    user_columns: list[str],
    active_event_names: set[str],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing_event_columns = sorted(REQUIRED_EVENT_COLUMNS - set(event_columns))
    if missing_event_columns:
        checks.append(failed("event_columns_present", missing_event_columns, "all required event columns"))
    else:
        checks.append(passed("event_columns_present", len(event_columns), "all required event columns"))
    missing_user_columns = sorted(REQUIRED_USER_COLUMNS - set(user_columns))
    if missing_user_columns:
        checks.append(failed("user_columns_present", missing_user_columns, "all required user columns"))
    else:
        checks.append(passed("user_columns_present", len(user_columns), "all required user columns"))

    event_ids = [row.get("event_id", "") for row in events if row.get("event_id")]
    duplicate_event_ids = duplicate_values(event_ids)
    if duplicate_event_ids:
        checks.append(failed("event_ids_unique", len(duplicate_event_ids), "0 duplicate event_id values", duplicate_event_ids[:10]))
    else:
        checks.append(passed("event_ids_unique", len(event_ids), "0 duplicate event_id values"))

    user_ids = [row.get("user_id", "") for row in users if row.get("user_id")]
    duplicate_user_ids = duplicate_values(user_ids)
    if duplicate_user_ids:
        checks.append(failed("user_ids_unique", len(duplicate_user_ids), "0 duplicate user_id values", duplicate_user_ids[:10]))
    else:
        checks.append(passed("user_ids_unique", len(user_ids), "0 duplicate user_id values"))

    known_users = set(user_ids)
    missing_identity: list[dict[str, Any]] = []
    unknown_users: list[dict[str, Any]] = []
    timestamp_errors: list[dict[str, Any]] = []
    for index, row in enumerate(events, start=2):
        if row.get("event_name") not in active_event_names:
            continue
        event_id = row.get("event_id", f"row-{index}")
        user_id = row.get("user_id", "")
        if not user_id:
            missing_identity.append({"row": index, "event_id": event_id, "event_name": row.get("event_name")})
        elif user_id not in known_users:
            unknown_users.append({"row": index, "event_id": event_id, "user_id": user_id})
        try:
            parse_timestamp(row.get("occurred_at", ""))
        except ValueError as error:
            timestamp_errors.append({"row": index, "event_id": event_id, "error": str(error)})
    if missing_identity:
        checks.append(failed("active_events_have_user_id", len(missing_identity), "active events have user_id", missing_identity[:10]))
    else:
        checks.append(passed("active_events_have_user_id", len(events), "active events have user_id"))
    if unknown_users:
        checks.append(failed("active_events_reference_known_users", len(unknown_users), "active event user_id exists in users", unknown_users[:10]))
    else:
        checks.append(passed("active_events_reference_known_users", len(events), "active event user_id exists in users"))
    if timestamp_errors:
        checks.append(failed("active_event_timestamps_valid", len(timestamp_errors), "active event occurred_at is timezone-aware", timestamp_errors[:10]))
    else:
        checks.append(passed("active_event_timestamps_valid", len(events), "active event occurred_at is timezone-aware"))
    return checks


def deduplicate_events(events: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for row in events:
        event_id = row.get("event_id", "")
        if event_id and event_id in seen:
            continue
        if event_id:
            seen.add(event_id)
        deduped.append(row)
    return deduped


def eligible_users_by_date(users: list[dict[str, str]], timezone: ZoneInfo, exclude_test_users: bool) -> dict[str, date]:
    eligible: dict[str, date] = {}
    for row in users:
        if exclude_test_users and parse_bool(row.get("is_test_user", "")):
            continue
        user_id = row.get("user_id", "")
        if not user_id:
            continue
        registered_at = parse_timestamp(row.get("registered_at", "")).astimezone(timezone).date()
        eligible[user_id] = registered_at
    return eligible


def active_events_by_date(
    events: list[dict[str, str]],
    eligible_users: dict[str, date],
    active_event_names: set[str],
    timezone: ZoneInfo,
) -> dict[date, list[dict[str, str]]]:
    by_date: dict[date, list[dict[str, str]]] = {}
    for row in deduplicate_events(events):
        if row.get("event_name") not in active_event_names:
            continue
        user_id = row.get("user_id", "")
        if user_id not in eligible_users:
            continue
        event_date = parse_timestamp(row["occurred_at"]).astimezone(timezone).date()
        by_date.setdefault(event_date, []).append(row)
    return by_date


def build_activity_table(
    events: list[dict[str, str]],
    users: list[dict[str, str]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    timezone = ZoneInfo(spec["business_timezone"])
    active_event_names = set(spec["active_event_names"])
    windows = sorted(spec["windows_days"])
    eligible = eligible_users_by_date(users, timezone, bool(spec.get("exclude_test_users", True)))
    events_by_date = active_events_by_date(events, eligible, active_event_names, timezone)

    all_dates: list[date] = []
    for row in events:
        try:
            all_dates.append(parse_timestamp(row.get("occurred_at", "")).astimezone(timezone).date())
        except ValueError:
            continue
    if not all_dates:
        return [], {"date_range": None, "deduplicated_events": 0}
    first_date = min(all_dates)
    last_date = max(all_dates)
    rows: list[dict[str, str]] = []
    for activity_date in daterange(first_date, last_date):
        eligible_users = {
            user_id
            for user_id, registered_date in eligible.items()
            if registered_date <= activity_date
        }
        for window in windows:
            window_start = activity_date - timedelta(days=window - 1)
            window_events = [
                event
                for event_date, day_events in events_by_date.items()
                if window_start <= event_date <= activity_date
                for event in day_events
            ]
            active_users = {event["user_id"] for event in window_events if event["user_id"] in eligible_users}
            denominator = len(eligible_users)
            rate = len(active_users) / denominator if denominator else 0.0
            rows.append({
                "activity_date": activity_date.isoformat(),
                "window_days": str(window),
                "is_complete_window": "true" if window_start >= first_date else "false",
                "eligible_users": str(denominator),
                "active_users": str(len(active_users)),
                "activity_rate": f"{rate:.6f}",
                "active_event_count": str(len(window_events)),
            })
    summary = {
        "date_range": {"start": first_date.isoformat(), "end": last_date.isoformat()},
        "deduplicated_events": len(deduplicate_events(events)),
        "excluded_test_users": sum(1 for user in users if parse_bool(user.get("is_test_user", ""))),
        "eligible_users": len(eligible),
        "active_event_names": sorted(active_event_names),
        "windows_days": windows,
    }
    return rows, summary


def calculate_activity(
    events: list[dict[str, str]],
    event_columns: list[str],
    users: list[dict[str, str]],
    user_columns: list[str],
    tracking_plan: dict[str, Any],
    spec: dict[str, Any],
) -> ActivityResult:
    checks = validate_configuration(spec, tracking_plan)
    active_event_names = set(spec.get("active_event_names", [])) if isinstance(spec.get("active_event_names"), list) else set()
    checks.extend(validate_inputs(events, event_columns, users, user_columns, active_event_names))

    table: list[dict[str, str]] = []
    table_summary: dict[str, Any] = {}
    can_build = all(check["valid"] for check in checks if check["id"] not in {"event_ids_unique"})
    if can_build:
        table, table_summary = build_activity_table(events, users, spec)
        if table:
            checks.append(passed("activity_rows_present", len(table), "at least one activity row"))
        else:
            checks.append(failed("activity_rows_present", 0, "at least one activity row"))
    else:
        checks.append(failed("activity_rows_present", 0, "valid inputs before calculation"))

    report = {
        "valid": all(check["valid"] for check in checks),
        "checks": checks,
        "summary": {
            "rows": len(table),
            **table_summary,
        },
    }
    return ActivityResult(table=table, report=report)


def write_activity_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(events_path: Path, users_path: Path, tracking_plan_path: Path, spec_path: Path) -> ActivityResult:
    events, event_columns = read_csv(events_path)
    users, user_columns = read_csv(users_path)
    tracking_plan = normalize_tracking_plan(read_json(tracking_plan_path))
    spec = normalize_spec(read_json(spec_path))
    return calculate_activity(events, event_columns, users, user_columns, tracking_plan, spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate product active audience with explicit windows")
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--tracking-plan", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args.events, args.users, args.tracking_plan, args.spec)
    except (OSError, csv.Error, json.JSONDecodeError, ValueError, ZoneInfoNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 2
    if result.table:
        write_activity_csv(args.output, result.table)
    rendered_report = json.dumps(result.report, ensure_ascii=False, indent=2) + "\n"
    if args.report is not None:
        args.report.write_text(rendered_report, encoding="utf-8")
    print(rendered_report, end="")
    if result.report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
