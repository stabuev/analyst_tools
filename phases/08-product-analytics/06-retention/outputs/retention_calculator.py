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
    "start_source",
    "return_event_names",
    "age_days",
    "retention_modes",
    "business_timezone",
    "exclude_test_users",
    "count_start_day_as_return",
    "incomplete_window_policy",
    "observation_end_date",
}
SUPPORTED_UNITS = {"user_id"}
SUPPORTED_START_SOURCES = {"registered_at"}
SUPPORTED_RETENTION_MODES = {"exact_day", "on_or_after"}
SUPPORTED_INCOMPLETE_POLICIES = {"blank_rate"}
OUTPUT_COLUMNS = [
    "metric_id",
    "retention_mode",
    "cohort_date",
    "age_day",
    "return_window_start",
    "return_window_end",
    "cohort_size",
    "retained_users",
    "retention_rate",
    "is_complete_window",
    "return_event_count",
]


class RetentionResult:
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
        raise ValueError("retention spec must be an object")
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


def return_event_names(spec: dict[str, Any]) -> set[str]:
    return {name for name in spec.get("return_event_names", []) if isinstance(name, str)}


def validate_spec(spec: dict[str, Any], activity_spec: dict[str, Any], tracking_plan: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        checks.append(failed("retention_spec_required_fields", missing, "all required retention spec fields"))
    else:
        checks.append(passed("retention_spec_required_fields", len(REQUIRED_SPEC_FIELDS), "all required retention spec fields"))

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

    if spec.get("start_source") not in SUPPORTED_START_SOURCES:
        checks.append(failed("start_source_supported", spec.get("start_source"), sorted(SUPPORTED_START_SOURCES)))
    else:
        checks.append(passed("start_source_supported", spec.get("start_source"), sorted(SUPPORTED_START_SOURCES)))

    age_days = spec.get("age_days", [])
    expected_age_days = list(range(1, max(age_days) + 1)) if isinstance(age_days, list) and age_days and all(isinstance(item, int) for item in age_days) else []
    if not isinstance(age_days, list) or not age_days or sorted(age_days) != expected_age_days:
        checks.append(failed("retention_age_days_contiguous", age_days, "contiguous integer ages starting at 1"))
    else:
        checks.append(passed("retention_age_days_contiguous", age_days, "contiguous integer ages starting at 1"))

    modes = spec.get("retention_modes", [])
    mode_errors = [mode for mode in modes if mode not in SUPPORTED_RETENTION_MODES] if isinstance(modes, list) else [modes]
    if not isinstance(modes, list) or not modes or mode_errors:
        checks.append(failed("retention_modes_supported", modes, sorted(SUPPORTED_RETENTION_MODES), mode_errors))
    else:
        checks.append(passed("retention_modes_supported", modes, sorted(SUPPORTED_RETENTION_MODES)))

    if spec.get("incomplete_window_policy") not in SUPPORTED_INCOMPLETE_POLICIES:
        checks.append(failed("incomplete_window_policy_supported", spec.get("incomplete_window_policy"), sorted(SUPPORTED_INCOMPLETE_POLICIES)))
    else:
        checks.append(passed("incomplete_window_policy_supported", spec.get("incomplete_window_policy"), sorted(SUPPORTED_INCOMPLETE_POLICIES)))

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
    return_names = return_event_names(spec)
    duplicate_return_events = duplicate_values([name for name in spec.get("return_event_names", []) if isinstance(name, str)])
    if duplicate_return_events:
        checks.append(failed("return_event_names_unique", len(duplicate_return_events), "unique return_event_names", duplicate_return_events))
    else:
        checks.append(passed("return_event_names_unique", len(return_names), "unique return_event_names"))

    if not return_names:
        checks.append(failed("return_events_declared", 0, "non-empty return_event_names"))
    else:
        checks.append(passed("return_events_declared", len(return_names), "non-empty return_event_names"))

    unknown_in_activity = sorted(return_names - active_names)
    if unknown_in_activity:
        checks.append(failed("return_events_in_activity_spec", len(unknown_in_activity), "return events exist in activity spec", unknown_in_activity))
    else:
        checks.append(passed("return_events_in_activity_spec", len(return_names), "return events exist in activity spec"))

    unknown_in_plan = sorted(return_names - plan_names)
    if unknown_in_plan:
        checks.append(failed("return_events_in_tracking_plan", len(unknown_in_plan), "return events exist in tracking plan", unknown_in_plan))
    else:
        checks.append(passed("return_events_in_tracking_plan", len(return_names), "return events exist in tracking plan"))
    return checks


def validate_inputs(
    events: list[dict[str, str]],
    event_columns: list[str],
    users: list[dict[str, str]],
    user_columns: list[str],
    return_names: set[str],
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
        if row.get("event_name") not in return_names:
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
        checks.append(failed("return_events_have_user_id", len(missing_identity), "return events have user_id", missing_identity[:10]))
    else:
        checks.append(passed("return_events_have_user_id", len(events), "return events have user_id"))
    if unknown_users:
        checks.append(failed("return_events_reference_known_users", len(unknown_users), "return event user_id exists in users", unknown_users[:10]))
    else:
        checks.append(passed("return_events_reference_known_users", len(events), "return event user_id exists in users"))
    if timestamp_errors:
        checks.append(failed("return_event_timestamps_valid", len(timestamp_errors), "occurred_at and received_at are timezone-aware", timestamp_errors[:10]))
    else:
        checks.append(passed("return_event_timestamps_valid", len(events), "occurred_at and received_at are timezone-aware"))
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
        cohort_date = parse_timestamp(row["registered_at"]).astimezone(timezone).date()
        output[user_id] = {"cohort_date": cohort_date}
    return output


def resolve_observation_end(events: list[dict[str, str]], spec: dict[str, Any], timezone: ZoneInfo) -> date:
    if spec.get("observation_end_date") != "auto":
        return date.fromisoformat(str(spec["observation_end_date"]))
    observed_dates = [parse_timestamp(row["occurred_at"]).astimezone(timezone).date() for row in events if row.get("occurred_at")]
    if not observed_dates:
        raise ValueError("cannot infer observation_end_date from empty events")
    return max(observed_dates)


def window_bounds(cohort_date: date, mode: str, age_day: int, max_age_day: int) -> tuple[date, date]:
    if mode == "exact_day":
        target = cohort_date + timedelta(days=age_day)
        return target, target
    if mode == "on_or_after":
        return cohort_date + timedelta(days=age_day), cohort_date + timedelta(days=max_age_day)
    raise ValueError(f"unsupported retention mode: {mode}")


def is_complete_window(cohort_date: date, mode: str, age_day: int, max_age_day: int, observation_end: date) -> bool:
    _start, end = window_bounds(cohort_date, mode, age_day, max_age_day)
    return end <= observation_end


def calculate_table(
    events: list[dict[str, str]],
    users: list[dict[str, str]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    timezone = ZoneInfo(spec["business_timezone"])
    user_cohorts = cohort_users(users, bool(spec.get("exclude_test_users", True)), timezone)
    cohort_members: dict[date, set[str]] = {}
    for user_id, user in user_cohorts.items():
        cohort_members.setdefault(user["cohort_date"], set()).add(user_id)
    observation_end = resolve_observation_end(deduplicate_events(events), spec, timezone)
    age_days = sorted(spec["age_days"])
    max_age_day = max(age_days)
    return_names = return_event_names(spec)
    count_start_day = bool(spec.get("count_start_day_as_return", False))
    return_ages_by_user: dict[date, dict[str, set[int]]] = {}
    return_events_by_cohort_age: dict[tuple[date, int], int] = {}
    for row in deduplicate_events(events):
        if row.get("event_name") not in return_names:
            continue
        user_id = row.get("user_id", "")
        user = user_cohorts.get(user_id)
        if user is None:
            continue
        return_date = parse_timestamp(row["occurred_at"]).astimezone(timezone).date()
        age_day = (return_date - user["cohort_date"]).days
        if age_day < 0:
            continue
        if age_day == 0 and not count_start_day:
            continue
        if age_day > max_age_day:
            continue
        return_ages_by_user.setdefault(user["cohort_date"], {}).setdefault(user_id, set()).add(age_day)
        return_events_by_cohort_age[(user["cohort_date"], age_day)] = return_events_by_cohort_age.get((user["cohort_date"], age_day), 0) + 1

    table: list[dict[str, str]] = []
    complete_windows = 0
    incomplete_windows = 0
    for cohort_date in sorted(cohort_members):
        cohort_size = len(cohort_members[cohort_date])
        user_ages = return_ages_by_user.get(cohort_date, {})
        for mode in spec["retention_modes"]:
            for age_day in age_days:
                start_date, end_date = window_bounds(cohort_date, mode, age_day, max_age_day)
                complete = is_complete_window(cohort_date, mode, age_day, max_age_day, observation_end)
                if complete:
                    complete_windows += 1
                else:
                    incomplete_windows += 1
                if mode == "exact_day":
                    retained = {user_id for user_id, ages in user_ages.items() if age_day in ages}
                    event_count = return_events_by_cohort_age.get((cohort_date, age_day), 0)
                else:
                    retained = {
                        user_id
                        for user_id, ages in user_ages.items()
                        if any(age_day <= observed_age <= max_age_day for observed_age in ages)
                    }
                    event_count = sum(
                        count
                        for (event_cohort_date, observed_age), count in return_events_by_cohort_age.items()
                        if event_cohort_date == cohort_date and age_day <= observed_age <= max_age_day
                    )
                retained_count = len(retained) if complete else 0
                retention_rate = retained_count / cohort_size if cohort_size and complete else None
                table.append({
                    "metric_id": spec["metric_id"],
                    "retention_mode": mode,
                    "cohort_date": cohort_date.isoformat(),
                    "age_day": str(age_day),
                    "return_window_start": start_date.isoformat(),
                    "return_window_end": end_date.isoformat(),
                    "cohort_size": str(cohort_size),
                    "retained_users": str(retained_count),
                    "retention_rate": f"{retention_rate:.6f}" if retention_rate is not None else "",
                    "is_complete_window": "true" if complete else "false",
                    "return_event_count": str(event_count if complete else 0),
                })
    summary = {
        "rows": len(table),
        "cohorts": len(cohort_members),
        "eligible_users": len(user_cohorts),
        "excluded_test_users": len(users) - len(user_cohorts),
        "observation_end_date": observation_end.isoformat(),
        "complete_windows": complete_windows,
        "incomplete_windows": incomplete_windows,
        "deduplicated_events": len(deduplicate_events(events)),
        "max_age_day": max_age_day,
    }
    return table, summary


def calculate_retention(
    events: list[dict[str, str]],
    event_columns: list[str],
    users: list[dict[str, str]],
    user_columns: list[str],
    tracking_plan: dict[str, Any],
    activity_spec: dict[str, Any],
    spec: dict[str, Any],
) -> RetentionResult:
    checks = validate_spec(spec, activity_spec, tracking_plan)
    checks.extend(
        validate_inputs(
            events,
            event_columns,
            users,
            user_columns,
            return_event_names(spec),
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
        "max_age_day": None,
    }
    can_build = all(check["valid"] for check in checks if check["id"] != "event_ids_unique")
    if can_build:
        table, summary = calculate_table(events, users, spec)
        if table:
            checks.append(passed("retention_rows_present", len(table), "at least one retention output row"))
        else:
            checks.append(failed("retention_rows_present", 0, "at least one retention output row"))
    else:
        checks.append(failed("retention_rows_present", 0, "valid inputs before calculation"))
    report = {
        "valid": all(check["valid"] for check in checks),
        "checks": checks,
        "summary": summary,
    }
    return RetentionResult(table=table, report=report)


def write_retention_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(events_path: Path, users_path: Path, tracking_plan_path: Path, activity_spec_path: Path, spec_path: Path) -> RetentionResult:
    events, event_columns = read_csv(events_path)
    users, user_columns = read_csv(users_path)
    tracking_plan = normalize_tracking_plan(read_json(tracking_plan_path))
    activity_spec = normalize_activity_spec(read_json(activity_spec_path))
    spec = normalize_spec(read_json(spec_path))
    return calculate_retention(events, event_columns, users, user_columns, tracking_plan, activity_spec, spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate daily retention with exact-day and on-or-after semantics")
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
        write_retention_csv(args.output, result.table)
    rendered_report = json.dumps(result.report, ensure_ascii=False, indent=2) + "\n"
    if args.report is not None:
        args.report.write_text(rendered_report, encoding="utf-8")
    print(rendered_report, end="")
    if result.report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
