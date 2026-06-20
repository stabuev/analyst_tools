from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REQUIRED_EVENT_COLUMNS = {
    "event_id",
    "user_id",
    "session_id",
    "event_name",
    "occurred_at",
    "received_at",
}
REQUIRED_USER_COLUMNS = {"user_id", "is_test_user"}
REQUIRED_SPEC_FIELDS = {"funnels", "business_timezone", "exclude_test_users"}
REQUIRED_FUNNEL_FIELDS = {
    "funnel_id",
    "metric_id",
    "unit",
    "ordering",
    "entry_policy",
    "conversion_window_minutes",
    "steps",
}
SUPPORTED_UNITS = {"user_id", "session_id", "user_day"}
SUPPORTED_ORDERING = {"strict", "loose"}
SUPPORTED_ENTRY_POLICIES = {"closed"}
OUTPUT_COLUMNS = [
    "funnel_id",
    "metric_id",
    "unit",
    "ordering",
    "entry_policy",
    "conversion_window_minutes",
    "step_index",
    "step_id",
    "event_name",
    "units",
    "conversion_from_start",
    "conversion_from_previous",
    "dropoff_from_previous",
]


class FunnelResult:
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


def normalize_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("funnel spec must be an object")
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


def validate_spec(spec: dict[str, Any], tracking_plan: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        checks.append(failed("funnel_spec_required_fields", missing, "all required funnel spec fields"))
    else:
        checks.append(passed("funnel_spec_required_fields", len(REQUIRED_SPEC_FIELDS), "all required funnel spec fields"))

    funnels = spec.get("funnels", [])
    if not isinstance(funnels, list) or not funnels:
        checks.append(failed("funnels_declared", funnels, "non-empty funnels list"))
        funnels = []
    else:
        checks.append(passed("funnels_declared", len(funnels), "non-empty funnels list"))

    try:
        ZoneInfo(str(spec.get("business_timezone", "")))
    except ZoneInfoNotFoundError:
        checks.append(failed("business_timezone_valid", spec.get("business_timezone"), "IANA timezone name"))
    else:
        checks.append(passed("business_timezone_valid", spec.get("business_timezone"), "IANA timezone name"))

    plan_names = tracking_event_names(tracking_plan)
    missing_fields: list[dict[str, Any]] = []
    step_errors: list[dict[str, Any]] = []
    event_errors: list[dict[str, Any]] = []
    unit_errors: list[dict[str, Any]] = []
    ordering_errors: list[dict[str, Any]] = []
    entry_errors: list[dict[str, Any]] = []
    window_errors: list[dict[str, Any]] = []
    ids = [funnel.get("funnel_id", "") for funnel in funnels if isinstance(funnel, dict)]
    duplicate_ids = duplicate_values([value for value in ids if value])
    for funnel in funnels:
        if not isinstance(funnel, dict):
            missing_fields.append({"funnel_id": "<not-object>", "missing": sorted(REQUIRED_FUNNEL_FIELDS)})
            continue
        funnel_id = funnel.get("funnel_id", "<missing>")
        missing_funnel_fields = sorted(REQUIRED_FUNNEL_FIELDS - set(funnel))
        if missing_funnel_fields:
            missing_fields.append({"funnel_id": funnel_id, "missing": missing_funnel_fields})
        steps = funnel.get("steps", [])
        if not isinstance(steps, list) or len(steps) < 2:
            step_errors.append({"funnel_id": funnel_id, "reason": "at least two steps are required"})
            steps = []
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict) or not step.get("step_id") or not step.get("event_name"):
                step_errors.append({"funnel_id": funnel_id, "step_index": index, "reason": "step_id and event_name are required"})
                continue
            if step["event_name"] not in plan_names:
                event_errors.append({"funnel_id": funnel_id, "event_name": step["event_name"]})
        if funnel.get("unit") not in SUPPORTED_UNITS:
            unit_errors.append({"funnel_id": funnel_id, "unit": funnel.get("unit")})
        if funnel.get("ordering") not in SUPPORTED_ORDERING:
            ordering_errors.append({"funnel_id": funnel_id, "ordering": funnel.get("ordering")})
        if funnel.get("entry_policy") not in SUPPORTED_ENTRY_POLICIES:
            entry_errors.append({"funnel_id": funnel_id, "entry_policy": funnel.get("entry_policy")})
        if not isinstance(funnel.get("conversion_window_minutes"), int) or funnel.get("conversion_window_minutes", 0) <= 0:
            window_errors.append({"funnel_id": funnel_id, "conversion_window_minutes": funnel.get("conversion_window_minutes")})

    if duplicate_ids:
        checks.append(failed("funnel_ids_unique", len(duplicate_ids), "unique funnel_id values", duplicate_ids))
    else:
        checks.append(passed("funnel_ids_unique", len(ids), "unique funnel_id values"))
    if missing_fields:
        checks.append(failed("funnel_required_fields", len(missing_fields), "all required funnel fields", missing_fields))
    else:
        checks.append(passed("funnel_required_fields", len(funnels), "all required funnel fields"))
    if step_errors:
        checks.append(failed("funnel_steps_valid", len(step_errors), "each funnel has at least two valid steps", step_errors))
    else:
        checks.append(passed("funnel_steps_valid", len(funnels), "each funnel has at least two valid steps"))
    if event_errors:
        checks.append(failed("funnel_events_in_tracking_plan", len(event_errors), "step events exist in tracking plan", event_errors))
    else:
        checks.append(passed("funnel_events_in_tracking_plan", sum(len(funnel.get("steps", [])) for funnel in funnels), "step events exist in tracking plan"))
    if unit_errors:
        checks.append(failed("funnel_units_supported", len(unit_errors), sorted(SUPPORTED_UNITS), unit_errors))
    else:
        checks.append(passed("funnel_units_supported", len(funnels), sorted(SUPPORTED_UNITS)))
    if ordering_errors:
        checks.append(failed("funnel_ordering_supported", len(ordering_errors), sorted(SUPPORTED_ORDERING), ordering_errors))
    else:
        checks.append(passed("funnel_ordering_supported", len(funnels), sorted(SUPPORTED_ORDERING)))
    if entry_errors:
        checks.append(failed("funnel_entry_policy_supported", len(entry_errors), sorted(SUPPORTED_ENTRY_POLICIES), entry_errors))
    else:
        checks.append(passed("funnel_entry_policy_supported", len(funnels), sorted(SUPPORTED_ENTRY_POLICIES)))
    if window_errors:
        checks.append(failed("funnel_windows_positive", len(window_errors), "positive conversion_window_minutes", window_errors))
    else:
        checks.append(passed("funnel_windows_positive", len(funnels), "positive conversion_window_minutes"))
    return checks


def validate_inputs(
    events: list[dict[str, str]],
    event_columns: list[str],
    users: list[dict[str, str]],
    user_columns: list[str],
    step_event_names: set[str],
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
        if row.get("event_name") not in step_event_names:
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
        checks.append(failed("funnel_events_have_user_id", len(missing_identity), "funnel step events have user_id", missing_identity[:10]))
    else:
        checks.append(passed("funnel_events_have_user_id", len(events), "funnel step events have user_id"))
    if unknown_users:
        checks.append(failed("funnel_events_reference_known_users", len(unknown_users), "funnel event user_id exists in users", unknown_users[:10]))
    else:
        checks.append(passed("funnel_events_reference_known_users", len(events), "funnel event user_id exists in users"))
    if timestamp_errors:
        checks.append(failed("funnel_event_timestamps_valid", len(timestamp_errors), "occurred_at and received_at are timezone-aware", timestamp_errors[:10]))
    else:
        checks.append(passed("funnel_event_timestamps_valid", len(events), "occurred_at and received_at are timezone-aware"))
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


def eligible_user_ids(users: list[dict[str, str]], exclude_test_users: bool) -> set[str]:
    eligible = set()
    for row in users:
        user_id = row.get("user_id", "")
        if not user_id:
            continue
        if exclude_test_users and parse_bool(row.get("is_test_user", "")):
            continue
        eligible.add(user_id)
    return eligible


def unit_key(row: dict[str, str], unit: str, timezone: ZoneInfo) -> str:
    if unit == "user_id":
        return row.get("user_id", "")
    if unit == "session_id":
        return row.get("session_id", "")
    if unit == "user_day":
        event_date = parse_timestamp(row["occurred_at"]).astimezone(timezone).date().isoformat()
        return f"{row.get('user_id', '')}|{event_date}"
    raise ValueError(f"unsupported unit: {unit}")


def events_by_unit(
    events: list[dict[str, str]],
    eligible_users: set[str],
    step_event_names: set[str],
    unit: str,
    timezone: ZoneInfo,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in deduplicate_events(events):
        if row.get("event_name") not in step_event_names:
            continue
        if row.get("user_id") not in eligible_users:
            continue
        key = unit_key(row, unit, timezone)
        if not key:
            continue
        enriched = dict(row)
        enriched["_occurred_at"] = parse_timestamp(row["occurred_at"])
        grouped.setdefault(key, []).append(enriched)
    for rows in grouped.values():
        rows.sort(key=lambda item: (item["_occurred_at"], item.get("event_id", "")))
    return grouped


def strict_step_times(rows: list[dict[str, Any]], step_names: list[str], window_minutes: int) -> list[datetime]:
    matched: list[datetime] = []
    start_time: datetime | None = None
    last_time: datetime | None = None
    for step_index, event_name in enumerate(step_names):
        found: datetime | None = None
        for row in rows:
            occurred_at = row["_occurred_at"]
            if row.get("event_name") != event_name:
                continue
            if last_time is not None and occurred_at < last_time:
                continue
            if start_time is not None and (occurred_at - start_time).total_seconds() / 60 > window_minutes:
                continue
            found = occurred_at
            break
        if found is None:
            return matched
        if step_index == 0:
            start_time = found
        last_time = found
        matched.append(found)
    return matched


def loose_step_times(rows: list[dict[str, Any]], step_names: list[str], window_minutes: int) -> list[datetime]:
    earliest: dict[str, datetime] = {}
    for row in rows:
        event_name = row.get("event_name")
        if event_name not in step_names or event_name in earliest:
            continue
        earliest[event_name] = row["_occurred_at"]
    if step_names[0] not in earliest:
        return []
    matched: list[datetime] = []
    for event_name in step_names:
        if event_name not in earliest:
            return matched
        candidate = matched + [earliest[event_name]]
        if (max(candidate) - min(candidate)).total_seconds() / 60 > window_minutes:
            return matched
        matched = candidate
    return matched


def calculate_one_funnel(
    events: list[dict[str, str]],
    users: list[dict[str, str]],
    funnel: dict[str, Any],
    business_timezone: str,
    exclude_test_users: bool,
) -> list[dict[str, str]]:
    timezone = ZoneInfo(business_timezone)
    steps = funnel["steps"]
    step_names = [step["event_name"] for step in steps]
    eligible = eligible_user_ids(users, exclude_test_users)
    grouped = events_by_unit(events, eligible, set(step_names), funnel["unit"], timezone)
    reached = [0 for _step in steps]
    for rows in grouped.values():
        if funnel["ordering"] == "strict":
            matched = strict_step_times(rows, step_names, funnel["conversion_window_minutes"])
        else:
            matched = loose_step_times(rows, step_names, funnel["conversion_window_minutes"])
        for index in range(len(matched)):
            reached[index] += 1
    output: list[dict[str, str]] = []
    start_units = reached[0] if reached else 0
    for index, step in enumerate(steps):
        units = reached[index]
        previous = reached[index - 1] if index > 0 else units
        conversion_from_start = units / start_units if start_units else 0.0
        conversion_from_previous = units / previous if previous else 0.0
        dropoff = previous - units if index > 0 else 0
        output.append({
            "funnel_id": funnel["funnel_id"],
            "metric_id": funnel["metric_id"],
            "unit": funnel["unit"],
            "ordering": funnel["ordering"],
            "entry_policy": funnel["entry_policy"],
            "conversion_window_minutes": str(funnel["conversion_window_minutes"]),
            "step_index": str(index + 1),
            "step_id": step["step_id"],
            "event_name": step["event_name"],
            "units": str(units),
            "conversion_from_start": f"{conversion_from_start:.6f}",
            "conversion_from_previous": f"{conversion_from_previous:.6f}",
            "dropoff_from_previous": str(dropoff),
        })
    return output


def calculate_funnels(
    events: list[dict[str, str]],
    event_columns: list[str],
    users: list[dict[str, str]],
    user_columns: list[str],
    tracking_plan: dict[str, Any],
    spec: dict[str, Any],
) -> FunnelResult:
    checks = validate_spec(spec, tracking_plan)
    step_event_names = {
        step.get("event_name")
        for funnel in spec.get("funnels", [])
        if isinstance(funnel, dict)
        for step in funnel.get("steps", [])
        if isinstance(step, dict) and isinstance(step.get("event_name"), str)
    }
    checks.extend(
        validate_inputs(
            events,
            event_columns,
            users,
            user_columns,
            step_event_names,
            int(tracking_plan.get("max_late_minutes", 1440)),
        )
    )
    table: list[dict[str, str]] = []
    can_build = all(check["valid"] for check in checks if check["id"] != "event_ids_unique")
    if can_build:
        for funnel in spec.get("funnels", []):
            table.extend(
                calculate_one_funnel(
                    events,
                    users,
                    funnel,
                    spec["business_timezone"],
                    bool(spec.get("exclude_test_users", True)),
                )
            )
        if table:
            checks.append(passed("funnel_rows_present", len(table), "at least one funnel output row"))
        else:
            checks.append(failed("funnel_rows_present", 0, "at least one funnel output row"))
    else:
        checks.append(failed("funnel_rows_present", 0, "valid inputs before calculation"))
    report = {
        "valid": all(check["valid"] for check in checks),
        "checks": checks,
        "summary": {
            "rows": len(table),
            "funnels": len(spec.get("funnels", [])),
            "step_event_names": sorted(step_event_names),
            "deduplicated_events": len(deduplicate_events(events)),
        },
    }
    return FunnelResult(table=table, report=report)


def write_funnel_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(events_path: Path, users_path: Path, tracking_plan_path: Path, spec_path: Path) -> FunnelResult:
    events, event_columns = read_csv(events_path)
    users, user_columns = read_csv(users_path)
    tracking_plan = normalize_tracking_plan(read_json(tracking_plan_path))
    spec = normalize_spec(read_json(spec_path))
    return calculate_funnels(events, event_columns, users, user_columns, tracking_plan, spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate closed product funnels with explicit ordering and window")
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
        write_funnel_csv(args.output, result.table)
    rendered_report = json.dumps(result.report, ensure_ascii=False, indent=2) + "\n"
    if args.report is not None:
        args.report.write_text(rendered_report, encoding="utf-8")
    print(rendered_report, end="")
    if result.report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
