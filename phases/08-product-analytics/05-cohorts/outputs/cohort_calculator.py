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
    "received_at",
}
REQUIRED_USER_COLUMNS = {"user_id", "registered_at", "is_test_user"}
REQUIRED_SPEC_FIELDS = {
    "metric_id",
    "cohort_unit",
    "cohort_start",
    "period",
    "age_days",
    "business_timezone",
    "exclude_test_users",
    "incomplete_window_policy",
    "observation_end_date",
}
SUPPORTED_UNITS = {"user_id"}
SUPPORTED_COHORT_STARTS = {"registered_at"}
SUPPORTED_PERIODS = {"day"}
SUPPORTED_INCOMPLETE_POLICIES = {"blank_rate"}
OUTPUT_COLUMNS = [
    "metric_id",
    "cohort_date",
    "age_day",
    "activity_date",
    "cohort_size",
    "active_users",
    "activity_rate",
    "is_complete_window",
    "active_event_count",
]


class CohortResult:
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


def normalize_tracking_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise ValueError("tracking plan must be an object with an events list")
    return value


def normalize_activity_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("active_event_names"), list):
        raise ValueError("activity spec must be an object with active_event_names")
    return value


def normalize_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("cohort spec must be an object")
    return value


def duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def tracking_event_names(tracking_plan: dict[str, Any]) -> set[str]:
    return {
        event["event_name"]
        for event in tracking_plan.get("events", [])
        if isinstance(event, dict) and isinstance(event.get("event_name"), str)
    }


def active_event_names(activity_spec: dict[str, Any]) -> set[str]:
    return {name for name in activity_spec.get("active_event_names", []) if isinstance(name, str)}


def validate_spec(spec: dict[str, Any], activity_spec: dict[str, Any], tracking_plan: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        checks.append(failed("cohort_spec_required_fields", missing, "all required cohort spec fields"))
    else:
        checks.append(passed("cohort_spec_required_fields", len(REQUIRED_SPEC_FIELDS), "all required cohort spec fields"))

    try:
        ZoneInfo(str(spec.get("business_timezone", "")))
    except ZoneInfoNotFoundError:
        checks.append(failed("business_timezone_valid", spec.get("business_timezone"), "IANA timezone name"))
    else:
        checks.append(passed("business_timezone_valid", spec.get("business_timezone"), "IANA timezone name"))

    if spec.get("cohort_unit") not in SUPPORTED_UNITS:
        checks.append(failed("cohort_unit_supported", spec.get("cohort_unit"), sorted(SUPPORTED_UNITS)))
    else:
        checks.append(passed("cohort_unit_supported", spec.get("cohort_unit"), sorted(SUPPORTED_UNITS)))

    if spec.get("cohort_start") not in SUPPORTED_COHORT_STARTS:
        checks.append(failed("cohort_start_supported", spec.get("cohort_start"), sorted(SUPPORTED_COHORT_STARTS)))
    else:
        checks.append(passed("cohort_start_supported", spec.get("cohort_start"), sorted(SUPPORTED_COHORT_STARTS)))

    if spec.get("period") not in SUPPORTED_PERIODS:
        checks.append(failed("cohort_period_supported", spec.get("period"), sorted(SUPPORTED_PERIODS)))
    else:
        checks.append(passed("cohort_period_supported", spec.get("period"), sorted(SUPPORTED_PERIODS)))

    if spec.get("incomplete_window_policy") not in SUPPORTED_INCOMPLETE_POLICIES:
        checks.append(failed("incomplete_window_policy_supported", spec.get("incomplete_window_policy"), sorted(SUPPORTED_INCOMPLETE_POLICIES)))
    else:
        checks.append(passed("incomplete_window_policy_supported", spec.get("incomplete_window_policy"), sorted(SUPPORTED_INCOMPLETE_POLICIES)))

    age_days = spec.get("age_days", [])
    expected_age_days = list(range(max(age_days) + 1)) if isinstance(age_days, list) and age_days and all(isinstance(item, int) for item in age_days) else []
    if not isinstance(age_days, list) or not age_days or sorted(age_days) != expected_age_days:
        checks.append(failed("cohort_age_days_contiguous", age_days, "contiguous integer ages starting at 0"))
    else:
        checks.append(passed("cohort_age_days_contiguous", age_days, "contiguous integer ages starting at 0"))

    observation_end = spec.get("observation_end_date")
    if observation_end != "auto":
        try:
            date.fromisoformat(str(observation_end))
        except ValueError:
            checks.append(failed("observation_end_date_valid", observation_end, "auto or YYYY-MM-DD"))
        else:
            checks.append(passed("observation_end_date_valid", observation_end, "auto or YYYY-MM-DD"))
    else:
        checks.append(passed("observation_end_date_valid", observation_end, "auto or YYYY-MM-DD"))

    plan_names = tracking_event_names(tracking_plan)
    active_names = active_event_names(activity_spec)
    unknown_active_events = sorted(active_names - plan_names)
    if unknown_active_events:
        checks.append(failed("active_events_in_tracking_plan", len(unknown_active_events), "active events exist in tracking plan", unknown_active_events))
    else:
        checks.append(passed("active_events_in_tracking_plan", len(active_names), "active events exist in tracking plan"))
    return checks


def validate_inputs(
    events: list[dict[str, str]],
    event_columns: list[str],
    users: list[dict[str, str]],
    user_columns: list[str],
    active_names: set[str],
    max_late_minutes: int,
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

    user_ids = [row.get("user_id", "") for row in users if row.get("user_id")]
    duplicate_user_ids = duplicate_values(user_ids)
    if duplicate_user_ids:
        checks.append(failed("user_ids_unique", len(duplicate_user_ids), "0 duplicate user_id values", duplicate_user_ids[:10]))
    else:
        checks.append(passed("user_ids_unique", len(user_ids), "0 duplicate user_id values"))

    registered_errors: list[dict[str, Any]] = []
    for index, row in enumerate(users, start=2):
        try:
            parse_timestamp(row.get("registered_at", ""))
        except ValueError as error:
            registered_errors.append({"row": index, "user_id": row.get("user_id", ""), "error": str(error)})
    if registered_errors:
        checks.append(failed("registered_timestamps_valid", len(registered_errors), "registered_at is timezone-aware", registered_errors[:10]))
    else:
        checks.append(passed("registered_timestamps_valid", len(users), "registered_at is timezone-aware"))

    event_ids = [row.get("event_id", "") for row in events if row.get("event_id")]
    duplicate_event_ids = duplicate_values(event_ids)
    if duplicate_event_ids:
        checks.append(failed("event_ids_unique", len(duplicate_event_ids), "0 duplicate event_id values", duplicate_event_ids[:10]))
    else:
        checks.append(passed("event_ids_unique", len(event_ids), "0 duplicate event_id values"))

    known_users = {row.get("user_id") for row in users if row.get("user_id")}
    missing_identity: list[dict[str, Any]] = []
    unknown_users: list[dict[str, Any]] = []
    timestamp_errors: list[dict[str, Any]] = []
    late_events: list[dict[str, Any]] = []
    for index, row in enumerate(events, start=2):
        if row.get("event_name") not in active_names:
            continue
        event_id = row.get("event_id", f"row-{index}")
        user_id = row.get("user_id", "")
        if not user_id:
            missing_identity.append({"row": index, "event_id": event_id, "event_name": row.get("event_name")})
        elif user_id not in known_users:
            unknown_users.append({"row": index, "event_id": event_id, "user_id": user_id})
        try:
            occurred_at = parse_timestamp(row.get("occurred_at", ""))
            received_at = parse_timestamp(row.get("received_at", ""))
        except ValueError as error:
            timestamp_errors.append({"row": index, "event_id": event_id, "error": str(error)})
            continue
        delay_minutes = (received_at - occurred_at).total_seconds() / 60
        if delay_minutes > max_late_minutes:
            late_events.append({"row": index, "event_id": event_id, "delay_minutes": round(delay_minutes, 2)})
    if missing_identity:
        checks.append(failed("active_events_have_user_id", len(missing_identity), "active events have user_id", missing_identity[:10]))
    else:
        checks.append(passed("active_events_have_user_id", len(events), "active events have user_id"))
    if unknown_users:
        checks.append(failed("active_events_reference_known_users", len(unknown_users), "active event user_id exists in users", unknown_users[:10]))
    else:
        checks.append(passed("active_events_reference_known_users", len(events), "active event user_id exists in users"))
    if timestamp_errors:
        checks.append(failed("active_event_timestamps_valid", len(timestamp_errors), "occurred_at and received_at are timezone-aware", timestamp_errors[:10]))
    else:
        checks.append(passed("active_event_timestamps_valid", len(events), "occurred_at and received_at are timezone-aware"))
    if late_events:
        checks.append(failed("late_events_within_policy", len(late_events), f"delay <= {max_late_minutes} minutes", late_events[:10]))
    else:
        checks.append(passed("late_events_within_policy", len(events), f"delay <= {max_late_minutes} minutes"))
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


def cohort_users(users: list[dict[str, str]], exclude_test_users: bool, timezone: ZoneInfo) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in users:
        user_id = row.get("user_id", "")
        if not user_id:
            continue
        if exclude_test_users and parse_bool(row.get("is_test_user", "")):
            continue
        registered_date = parse_timestamp(row["registered_at"]).astimezone(timezone).date()
        output[user_id] = {"cohort_date": registered_date}
    return output


def resolve_observation_end(events: list[dict[str, str]], spec: dict[str, Any], timezone: ZoneInfo) -> date:
    if spec.get("observation_end_date") != "auto":
        return date.fromisoformat(str(spec["observation_end_date"]))
    observed_dates = [parse_timestamp(row["occurred_at"]).astimezone(timezone).date() for row in events if row.get("occurred_at")]
    if not observed_dates:
        raise ValueError("cannot infer observation_end_date from empty events")
    return max(observed_dates)


def calculate_table(
    events: list[dict[str, str]],
    users: list[dict[str, str]],
    spec: dict[str, Any],
    active_names: set[str],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    timezone = ZoneInfo(spec["business_timezone"])
    user_cohorts = cohort_users(users, bool(spec.get("exclude_test_users", True)), timezone)
    cohort_sizes: dict[date, int] = {}
    for user in user_cohorts.values():
        cohort_sizes[user["cohort_date"]] = cohort_sizes.get(user["cohort_date"], 0) + 1
    observation_end = resolve_observation_end(deduplicate_events(events), spec, timezone)
    age_days = sorted(spec["age_days"])
    active_by_cohort_age: dict[tuple[date, int], dict[str, Any]] = {}
    for row in deduplicate_events(events):
        if row.get("event_name") not in active_names:
            continue
        user = user_cohorts.get(row.get("user_id", ""))
        if user is None:
            continue
        activity_date = parse_timestamp(row["occurred_at"]).astimezone(timezone).date()
        age_day = (activity_date - user["cohort_date"]).days
        if age_day not in age_days:
            continue
        bucket = active_by_cohort_age.setdefault((user["cohort_date"], age_day), {"users": set(), "events": 0})
        bucket["users"].add(row["user_id"])
        bucket["events"] += 1

    table: list[dict[str, str]] = []
    complete_windows = 0
    incomplete_windows = 0
    for cohort_date in sorted(cohort_sizes):
        cohort_size = cohort_sizes[cohort_date]
        for age_day in age_days:
            activity_date = cohort_date + timedelta(days=age_day)
            is_complete = activity_date <= observation_end
            if is_complete:
                complete_windows += 1
            else:
                incomplete_windows += 1
            bucket = active_by_cohort_age.get((cohort_date, age_day), {"users": set(), "events": 0})
            active_users = len(bucket["users"])
            activity_rate = active_users / cohort_size if cohort_size and is_complete else None
            table.append({
                "metric_id": spec["metric_id"],
                "cohort_date": cohort_date.isoformat(),
                "age_day": str(age_day),
                "activity_date": activity_date.isoformat(),
                "cohort_size": str(cohort_size),
                "active_users": str(active_users if is_complete else 0),
                "activity_rate": f"{activity_rate:.6f}" if activity_rate is not None else "",
                "is_complete_window": "true" if is_complete else "false",
                "active_event_count": str(bucket["events"] if is_complete else 0),
            })
    summary = {
        "rows": len(table),
        "cohorts": len(cohort_sizes),
        "eligible_users": len(user_cohorts),
        "excluded_test_users": len(users) - len(user_cohorts),
        "observation_end_date": observation_end.isoformat(),
        "complete_windows": complete_windows,
        "incomplete_windows": incomplete_windows,
        "deduplicated_events": len(deduplicate_events(events)),
    }
    return table, summary


def calculate_cohorts(
    events: list[dict[str, str]],
    event_columns: list[str],
    users: list[dict[str, str]],
    user_columns: list[str],
    tracking_plan: dict[str, Any],
    activity_spec: dict[str, Any],
    spec: dict[str, Any],
) -> CohortResult:
    active_names = active_event_names(activity_spec)
    checks = validate_spec(spec, activity_spec, tracking_plan)
    checks.extend(
        validate_inputs(
            events,
            event_columns,
            users,
            user_columns,
            active_names,
            int(tracking_plan.get("max_late_minutes", 1440)),
        )
    )
    table: list[dict[str, str]] = []
    summary: dict[str, Any] = {
        "rows": 0,
        "cohorts": 0,
        "eligible_users": 0,
        "excluded_test_users": 0,
        "observation_end_date": None,
        "complete_windows": 0,
        "incomplete_windows": 0,
        "deduplicated_events": len(deduplicate_events(events)),
    }
    can_build = all(check["valid"] for check in checks if check["id"] != "event_ids_unique")
    if can_build:
        table, summary = calculate_table(events, users, spec, active_names)
        if table:
            checks.append(passed("cohort_rows_present", len(table), "at least one cohort output row"))
        else:
            checks.append(failed("cohort_rows_present", 0, "at least one cohort output row"))
    else:
        checks.append(failed("cohort_rows_present", 0, "valid inputs before calculation"))
    report = {
        "valid": all(check["valid"] for check in checks),
        "checks": checks,
        "summary": summary,
    }
    return CohortResult(table=table, report=report)


def write_cohort_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(events_path: Path, users_path: Path, tracking_plan_path: Path, activity_spec_path: Path, spec_path: Path) -> CohortResult:
    events, event_columns = read_csv(events_path)
    users, user_columns = read_csv(users_path)
    tracking_plan = normalize_tracking_plan(read_json(tracking_plan_path))
    activity_spec = normalize_activity_spec(read_json(activity_spec_path))
    spec = normalize_spec(read_json(spec_path))
    return calculate_cohorts(events, event_columns, users, user_columns, tracking_plan, activity_spec, spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate daily product cohort matrix with complete-window flags")
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--tracking-plan", type=Path, required=True)
    parser.add_argument("--activity-spec", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args.events, args.users, args.tracking_plan, args.activity_spec, args.spec)
    except (OSError, csv.Error, json.JSONDecodeError, ValueError, ZoneInfoNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 2
    if result.table:
        write_cohort_csv(args.output, result.table)
    rendered_report = json.dumps(result.report, ensure_ascii=False, indent=2) + "\n"
    if args.report is not None:
        args.report.write_text(rendered_report, encoding="utf-8")
    print(rendered_report, end="")
    if result.report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
