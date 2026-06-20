from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_EVENT_COLUMNS = {
    "event_id",
    "user_id",
    "anonymous_id",
    "session_id",
    "event_name",
    "event_version",
    "occurred_at",
    "received_at",
    "platform",
    "app_version",
    "properties_json",
}
REQUIRED_TRACKING_FIELDS = {
    "event_name",
    "version",
    "owner",
    "description",
    "trigger",
    "identity_policy",
    "required_properties",
    "optional_properties",
    "allowed_platforms",
    "app_version_policy",
    "used_by_metrics",
    "source",
}
LIST_FIELDS = {"required_properties", "optional_properties", "allowed_platforms", "used_by_metrics"}
IDENTITY_POLICIES = {"anonymous_or_user", "known_user"}
APP_VERSION_POLICIES = {"mobile_required", "optional"}
MOBILE_PLATFORMS = {"ios", "android"}


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


def read_events(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def normalize_tracking_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise ValueError("tracking plan must be an object with an events list")
    for event in value["events"]:
        if not isinstance(event, dict):
            raise ValueError("each tracking plan event must be an object")
    return value


def normalize_metric_specs(value: Any | None) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict) and isinstance(value.get("metrics"), list):
        value = value["metrics"]
    if not isinstance(value, list):
        raise ValueError("metric specs must be a list or an object with a metrics list")
    metrics: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each metric spec must be an object")
        metrics.append(item)
    return metrics


def non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def event_key(event: dict[str, Any]) -> tuple[str, str]:
    return (str(event.get("event_name", "")), str(event.get("version", "")))


def row_key(row: dict[str, str]) -> tuple[str, str]:
    return (row.get("event_name", ""), row.get("event_version", ""))


def parse_timestamp(value: str) -> datetime:
    if not value:
        raise ValueError("empty timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def parse_properties(rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    parsed: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        event_id = row.get("event_id", f"row-{index}")
        raw = row.get("properties_json", "")
        try:
            value = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as error:
            errors.append({"row": index, "event_id": event_id, "error": str(error)})
            continue
        if not isinstance(value, dict):
            errors.append({"row": index, "event_id": event_id, "error": "properties_json must decode to an object"})
            continue
        parsed[event_id] = value
    return parsed, errors


def validate_event_model(
    tracking_plan: dict[str, Any],
    rows: list[dict[str, str]],
    metric_specs: list[dict[str, Any]] | None = None,
    fieldnames: list[str] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    events = tracking_plan.get("events", [])
    metric_specs = metric_specs or []
    if fieldnames is not None:
        available_columns = set(fieldnames)
    elif rows:
        available_columns = set().union(*(row.keys() for row in rows))
    else:
        available_columns = set()
    missing_columns = sorted(REQUIRED_EVENT_COLUMNS - available_columns)
    if missing_columns:
        checks.append(failed("event_log_columns_present", missing_columns, "all required event log columns"))
    else:
        checks.append(passed("event_log_columns_present", len(available_columns), "all required event log columns"))

    plan_keys = [event_key(event) for event in events]
    duplicate_plan_keys = duplicate_values([f"{name}@{version}" for name, version in plan_keys])
    if duplicate_plan_keys:
        checks.append(failed("tracking_events_unique", len(duplicate_plan_keys), "unique event_name/version pairs", duplicate_plan_keys))
    else:
        checks.append(passed("tracking_events_unique", len(plan_keys), "unique event_name/version pairs"))

    missing_fields: list[dict[str, Any]] = []
    list_field_errors: list[dict[str, Any]] = []
    identity_policy_errors: list[dict[str, Any]] = []
    app_version_policy_errors: list[dict[str, Any]] = []
    name_errors: list[str] = []
    for event in events:
        name = str(event.get("event_name", "<missing>"))
        missing = sorted(REQUIRED_TRACKING_FIELDS - set(event))
        if missing:
            missing_fields.append({"event_name": name, "missing": missing})
        for field in LIST_FIELDS:
            if field in event and not isinstance(event.get(field), list):
                list_field_errors.append({"event_name": name, "field": field})
        if event.get("identity_policy") not in IDENTITY_POLICIES:
            identity_policy_errors.append({"event_name": name, "identity_policy": event.get("identity_policy")})
        if event.get("app_version_policy") not in APP_VERSION_POLICIES:
            app_version_policy_errors.append({"event_name": name, "app_version_policy": event.get("app_version_policy")})
        if not name.replace("_", "").isalnum() or name != name.lower() or name.startswith("_") or name.endswith("_"):
            name_errors.append(name)
    if missing_fields:
        checks.append(failed("tracking_event_required_fields", len(missing_fields), "all required tracking fields", missing_fields))
    else:
        checks.append(passed("tracking_event_required_fields", len(events), "all required tracking fields"))
    if list_field_errors:
        checks.append(failed("tracking_event_list_fields", len(list_field_errors), "list-valued tracking fields are lists", list_field_errors))
    else:
        checks.append(passed("tracking_event_list_fields", len(events), "list-valued tracking fields are lists"))
    if identity_policy_errors:
        checks.append(failed("tracking_identity_policies_known", len(identity_policy_errors), sorted(IDENTITY_POLICIES), identity_policy_errors))
    else:
        checks.append(passed("tracking_identity_policies_known", len(events), sorted(IDENTITY_POLICIES)))
    if app_version_policy_errors:
        checks.append(failed("tracking_app_version_policies_known", len(app_version_policy_errors), sorted(APP_VERSION_POLICIES), app_version_policy_errors))
    else:
        checks.append(passed("tracking_app_version_policies_known", len(events), sorted(APP_VERSION_POLICIES)))
    if name_errors:
        checks.append(failed("tracking_event_names_snake_case", len(name_errors), "lower snake_case event names", name_errors))
    else:
        checks.append(passed("tracking_event_names_snake_case", len(events), "lower snake_case event names"))

    plan_by_key = {
        event_key(event): event
        for event in events
        if non_empty(str(event.get("event_name", ""))) and non_empty(str(event.get("version", "")))
    }
    known_event_names = {name for name, _version in plan_by_key}
    event_ids = [row.get("event_id", "") for row in rows]
    missing_event_ids = [index for index, value in enumerate(event_ids, start=2) if not value]
    duplicate_event_ids = duplicate_values([value for value in event_ids if value])
    if missing_event_ids:
        checks.append(failed("event_ids_present", len(missing_event_ids), "each event has event_id", missing_event_ids[:10]))
    else:
        checks.append(passed("event_ids_present", len(rows), "each event has event_id"))
    if duplicate_event_ids:
        checks.append(failed("event_ids_unique", len(duplicate_event_ids), "0 duplicate event_id values", duplicate_event_ids))
    else:
        checks.append(passed("event_ids_unique", len(event_ids), "0 duplicate event_id values"))

    unknown_names = [
        {"event_id": row.get("event_id"), "event_name": row.get("event_name")}
        for row in rows
        if row.get("event_name") not in known_event_names
    ]
    if unknown_names:
        checks.append(failed("event_names_known", len(unknown_names), "all event_name values are in tracking plan", unknown_names[:10]))
    else:
        checks.append(passed("event_names_known", len(rows), "all event_name values are in tracking plan"))

    unknown_versions = [
        {
            "event_id": row.get("event_id"),
            "event_name": row.get("event_name"),
            "event_version": row.get("event_version"),
        }
        for row in rows
        if row.get("event_name") in known_event_names and row_key(row) not in plan_by_key
    ]
    if unknown_versions:
        checks.append(failed("event_versions_known", len(unknown_versions), "event_name/event_version pair exists", unknown_versions[:10]))
    else:
        checks.append(passed("event_versions_known", len(rows), "event_name/event_version pair exists"))

    platform_errors: list[dict[str, Any]] = []
    for row in rows:
        spec = plan_by_key.get(row_key(row))
        if spec is None:
            continue
        allowed = set(spec.get("allowed_platforms", []))
        if row.get("platform") not in allowed:
            platform_errors.append({
                "event_id": row.get("event_id"),
                "event_name": row.get("event_name"),
                "platform": row.get("platform"),
                "allowed_platforms": sorted(allowed),
            })
    if platform_errors:
        checks.append(failed("event_platforms_allowed", len(platform_errors), "platform is allowed by tracking plan", platform_errors[:10]))
    else:
        checks.append(passed("event_platforms_allowed", len(rows), "platform is allowed by tracking plan"))

    properties_by_event_id, property_errors = parse_properties(rows)
    if property_errors:
        checks.append(failed("properties_json_valid", len(property_errors), "properties_json decodes to an object", property_errors[:10]))
    else:
        checks.append(passed("properties_json_valid", len(rows), "properties_json decodes to an object"))

    missing_properties: list[dict[str, Any]] = []
    for row in rows:
        spec = plan_by_key.get(row_key(row))
        if spec is None or row.get("event_id") not in properties_by_event_id:
            continue
        properties = properties_by_event_id[row.get("event_id", "")]
        missing = [
            name
            for name in spec.get("required_properties", [])
            if name not in properties or properties.get(name) in ("", None)
        ]
        if missing:
            missing_properties.append({"event_id": row.get("event_id"), "event_name": row.get("event_name"), "missing": missing})
    if missing_properties:
        checks.append(failed("required_properties_present", len(missing_properties), "all required event properties are present", missing_properties[:10]))
    else:
        checks.append(passed("required_properties_present", len(rows), "all required event properties are present"))

    identity_errors: list[dict[str, Any]] = []
    for row in rows:
        spec = plan_by_key.get(row_key(row))
        if spec is None:
            continue
        policy = spec.get("identity_policy")
        has_user = non_empty(row.get("user_id"))
        has_anonymous = non_empty(row.get("anonymous_id"))
        if policy == "known_user" and not has_user:
            identity_errors.append({"event_id": row.get("event_id"), "event_name": row.get("event_name"), "identity_policy": policy})
        elif policy == "anonymous_or_user" and not (has_user or has_anonymous):
            identity_errors.append({"event_id": row.get("event_id"), "event_name": row.get("event_name"), "identity_policy": policy})
    if identity_errors:
        checks.append(failed("identity_policy_satisfied", len(identity_errors), "identity fields match event policy", identity_errors[:10]))
    else:
        checks.append(passed("identity_policy_satisfied", len(rows), "identity fields match event policy"))

    parsed_times: dict[str, tuple[datetime, datetime]] = {}
    timestamp_errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        event_id = row.get("event_id", f"row-{index}")
        try:
            occurred_at = parse_timestamp(row.get("occurred_at", ""))
            received_at = parse_timestamp(row.get("received_at", ""))
        except ValueError as error:
            timestamp_errors.append({"row": index, "event_id": event_id, "error": str(error)})
            continue
        parsed_times[event_id] = (occurred_at, received_at)
    if timestamp_errors:
        checks.append(failed("timestamps_timezone_aware", len(timestamp_errors), "occurred_at and received_at are timezone-aware", timestamp_errors[:10]))
    else:
        checks.append(passed("timestamps_timezone_aware", len(rows), "occurred_at and received_at are timezone-aware"))

    received_before_occurred: list[dict[str, Any]] = []
    late_arrivals: list[dict[str, Any]] = []
    max_late_minutes = int(tracking_plan.get("max_late_minutes", 1440))
    for row in rows:
        event_id = row.get("event_id", "")
        if event_id not in parsed_times:
            continue
        occurred_at, received_at = parsed_times[event_id]
        delay_minutes = (received_at - occurred_at).total_seconds() / 60
        if delay_minutes < 0:
            received_before_occurred.append({"event_id": event_id, "delay_minutes": round(delay_minutes, 2)})
        elif delay_minutes > max_late_minutes:
            late_arrivals.append({"event_id": event_id, "delay_minutes": round(delay_minutes, 2)})
    if received_before_occurred:
        checks.append(failed("received_after_occurred", len(received_before_occurred), "received_at >= occurred_at", received_before_occurred[:10]))
    else:
        checks.append(passed("received_after_occurred", len(rows), "received_at >= occurred_at"))
    if late_arrivals:
        checks.append(failed("late_arrivals_within_policy", len(late_arrivals), f"delay <= {max_late_minutes} minutes", late_arrivals[:10]))
    else:
        checks.append(passed("late_arrivals_within_policy", len(rows), f"delay <= {max_late_minutes} minutes"))

    app_version_errors: list[dict[str, Any]] = []
    for row in rows:
        spec = plan_by_key.get(row_key(row))
        if spec is None:
            continue
        if spec.get("app_version_policy") == "mobile_required" and row.get("platform") in MOBILE_PLATFORMS and not non_empty(row.get("app_version")):
            app_version_errors.append({"event_id": row.get("event_id"), "event_name": row.get("event_name"), "platform": row.get("platform")})
    if app_version_errors:
        checks.append(failed("mobile_app_version_present", len(app_version_errors), "mobile events have app_version", app_version_errors[:10]))
    else:
        checks.append(passed("mobile_app_version_present", len(rows), "mobile events have app_version"))

    metric_ids = {spec.get("metric_id") for spec in metric_specs if isinstance(spec.get("metric_id"), str)}
    unresolved_metric_links: list[dict[str, Any]] = []
    for event in events:
        for metric_id in event.get("used_by_metrics", []):
            if metric_id not in metric_ids:
                unresolved_metric_links.append({"event_name": event.get("event_name"), "metric_id": metric_id})
    if unresolved_metric_links:
        checks.append(failed("metric_links_resolve", len(unresolved_metric_links), "used_by_metrics reference metric specs", unresolved_metric_links[:10]))
    else:
        checks.append(passed("metric_links_resolve", sum(len(event.get("used_by_metrics", [])) for event in events), "used_by_metrics reference metric specs"))

    return {
        "valid": all(check["valid"] for check in checks),
        "checks": checks,
        "summary": {
            "events": len(rows),
            "tracking_events": len(events),
            "known_event_names": sorted(known_event_names),
            "max_late_minutes": max_late_minutes,
            "metric_specs": len(metric_specs),
        },
    }


def run(events_path: Path, tracking_plan_path: Path, metric_specs_path: Path | None = None) -> dict[str, Any]:
    rows, fieldnames = read_events(events_path)
    tracking_plan = normalize_tracking_plan(read_json(tracking_plan_path))
    metric_specs = normalize_metric_specs(read_json(metric_specs_path) if metric_specs_path else None)
    return validate_event_model(tracking_plan, rows, metric_specs, fieldnames)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a product tracking plan and event log")
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--tracking-plan", type=Path, required=True)
    parser.add_argument("--metric-specs", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run(args.events, args.tracking_plan, args.metric_specs)
    except (OSError, csv.Error, json.JSONDecodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
