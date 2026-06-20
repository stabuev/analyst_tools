from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REQUIRED_USER_COLUMNS = {"user_id", "registered_at", "is_test_user"}
REQUIRED_EVENT_COLUMNS = {"event_id", "user_id", "event_name", "occurred_at", "received_at"}
REQUIRED_SPEC_FIELDS = {
    "metric_id",
    "base_metric_id",
    "cohort_unit",
    "start_source",
    "activation_event_name",
    "activation_window_days",
    "analysis_periods",
    "dimensions",
    "primary_decomposition_dimension",
    "minimum_cell_size",
    "business_timezone",
    "exclude_test_users",
    "incomplete_window_policy",
    "observation_end_date",
    "allowed_claim_types",
    "forbid_causal_claims",
}
SUPPORTED_UNITS = {"user_id"}
SUPPORTED_START_SOURCES = {"registered_at"}
SUPPORTED_DIMENSION_SOURCES = {"users"}
SUPPORTED_DIMENSION_STATUSES = {"predeclared", "exploratory"}
SUPPORTED_INCOMPLETE_POLICIES = {"exclude_users"}
OUTPUT_COLUMNS = [
    "metric_id",
    "row_type",
    "dimension",
    "segment_value",
    "period",
    "period_start",
    "period_end",
    "eligible_users",
    "activated_users",
    "activation_rate",
    "traffic_share",
    "is_reportable",
    "is_exploratory",
    "baseline_rate",
    "comparison_rate",
    "baseline_share",
    "comparison_share",
    "within_segment_effect",
    "composition_effect",
    "total_delta_contribution",
    "overall_baseline_rate",
    "overall_comparison_rate",
    "overall_delta",
]


class SegmentationResult:
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


def normalize_tracking_plan(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise ValueError("tracking plan must be an object with an events list")
    return value


def normalize_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("segmentation spec must be an object")
    return value


def parse_timestamp(value: str) -> datetime:
    if not value:
        raise ValueError("empty timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


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


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def validate_periods(spec: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    periods = spec.get("analysis_periods")
    if not isinstance(periods, list) or len(periods) != 2:
        checks.append(failed("analysis_periods_valid", periods, "exactly two periods: baseline and comparison"))
        return
    period_ids = [period.get("period_id") for period in periods if isinstance(period, dict)]
    if period_ids != ["baseline", "comparison"]:
        checks.append(failed("analysis_periods_valid", period_ids, ["baseline", "comparison"]))
        return
    errors: list[dict[str, Any]] = []
    for period in periods:
        try:
            start = date.fromisoformat(str(period.get("cohort_date_from", "")))
            end = date.fromisoformat(str(period.get("cohort_date_to", "")))
        except ValueError as error:
            errors.append({"period_id": period.get("period_id"), "error": str(error)})
            continue
        if start > end:
            errors.append({"period_id": period.get("period_id"), "error": "cohort_date_from after cohort_date_to"})
    if errors:
        checks.append(failed("analysis_periods_valid", len(errors), "valid YYYY-MM-DD ranges", errors))
    else:
        checks.append(passed("analysis_periods_valid", period_ids, "baseline and comparison ranges"))


def validate_dimensions(spec: dict[str, Any], user_columns: list[str], checks: list[dict[str, Any]]) -> None:
    dimensions = spec.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        checks.append(failed("segment_dimensions_valid", dimensions, "non-empty dimension list"))
        return
    errors: list[dict[str, Any]] = []
    names: list[str] = []
    statuses: dict[str, str] = {}
    for item in dimensions:
        if not isinstance(item, dict):
            errors.append({"dimension": item, "error": "dimension must be object"})
            continue
        name = item.get("name")
        source = item.get("source")
        status = item.get("status")
        if not isinstance(name, str) or not name:
            errors.append({"dimension": item, "error": "name is required"})
            continue
        names.append(name)
        statuses[name] = str(status)
        if source not in SUPPORTED_DIMENSION_SOURCES:
            errors.append({"dimension": name, "error": "unsupported source"})
        if status not in SUPPORTED_DIMENSION_STATUSES:
            errors.append({"dimension": name, "error": "status must be predeclared or exploratory"})
        if name not in user_columns:
            errors.append({"dimension": name, "error": "dimension is not a users column"})
    duplicate_names = duplicate_values(names)
    for name in duplicate_names:
        errors.append({"dimension": name, "error": "duplicate dimension"})
    if errors:
        checks.append(failed("segment_dimensions_valid", len(errors), "declared users dimensions with status", errors[:10]))
    else:
        checks.append(passed("segment_dimensions_valid", names, "declared users dimensions with status"))

    primary = spec.get("primary_decomposition_dimension")
    if primary not in statuses:
        checks.append(failed("primary_decomposition_dimension_valid", primary, "one declared dimension"))
    elif statuses[primary] != "predeclared":
        checks.append(failed("primary_decomposition_dimension_valid", primary, "predeclared dimension"))
    else:
        checks.append(passed("primary_decomposition_dimension_valid", primary, "predeclared dimension"))


def validate_spec(spec: dict[str, Any], user_columns: list[str], tracking_plan: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        checks.append(failed("segmentation_spec_required_fields", missing, "all required segmentation spec fields"))
    else:
        checks.append(passed("segmentation_spec_required_fields", len(REQUIRED_SPEC_FIELDS), "all required segmentation spec fields"))

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

    activation_window = spec.get("activation_window_days")
    if not isinstance(activation_window, int) or activation_window < 0:
        checks.append(failed("activation_window_valid", activation_window, "non-negative integer"))
    else:
        checks.append(passed("activation_window_valid", activation_window, "non-negative integer"))

    min_cell = spec.get("minimum_cell_size")
    if not isinstance(min_cell, int) or min_cell < 1:
        checks.append(failed("minimum_cell_size_valid", min_cell, "positive integer"))
    else:
        checks.append(passed("minimum_cell_size_valid", min_cell, "positive integer"))

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

    event_names = tracking_event_names(tracking_plan)
    activation_event = spec.get("activation_event_name")
    if activation_event not in event_names:
        checks.append(failed("activation_event_in_tracking_plan", activation_event, "known event_name"))
    else:
        checks.append(passed("activation_event_in_tracking_plan", activation_event, "known event_name"))

    validate_periods(spec, checks)
    validate_dimensions(spec, user_columns, checks)

    allowed_claim_types = spec.get("allowed_claim_types")
    causal_allowed = isinstance(allowed_claim_types, list) and "causal" in allowed_claim_types
    if spec.get("forbid_causal_claims") is not True or causal_allowed:
        checks.append(failed("causal_claims_forbidden", allowed_claim_types, "only descriptive/hypothesis claims"))
    else:
        checks.append(passed("causal_claims_forbidden", allowed_claim_types, "only descriptive/hypothesis claims"))
    return checks


def validate_inputs(
    users: list[dict[str, str]],
    user_columns: list[str],
    events: list[dict[str, str]],
    event_columns: list[str],
    activation_event_name: str,
    max_late_minutes: int,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing_user_columns = sorted(REQUIRED_USER_COLUMNS - set(user_columns))
    missing_event_columns = sorted(REQUIRED_EVENT_COLUMNS - set(event_columns))
    if missing_user_columns:
        checks.append(failed("user_columns_present", missing_user_columns, "all required user columns"))
    else:
        checks.append(passed("user_columns_present", len(user_columns), "all required user columns"))
    if missing_event_columns:
        checks.append(failed("event_columns_present", missing_event_columns, "all required event columns"))
    else:
        checks.append(passed("event_columns_present", len(event_columns), "all required event columns"))

    user_ids = [row.get("user_id", "") for row in users if row.get("user_id")]
    duplicate_user_ids = duplicate_values(user_ids)
    if duplicate_user_ids:
        checks.append(failed("user_ids_unique", len(duplicate_user_ids), "0 duplicate user_id values", duplicate_user_ids[:10]))
    else:
        checks.append(passed("user_ids_unique", len(user_ids), "0 duplicate user_id values"))

    event_ids = [row.get("event_id", "") for row in events if row.get("event_id")]
    duplicate_event_ids = duplicate_values(event_ids)
    if duplicate_event_ids:
        checks.append(failed("event_ids_unique", len(duplicate_event_ids), "0 duplicate event_id values", duplicate_event_ids[:10]))
    else:
        checks.append(passed("event_ids_unique", len(event_ids), "0 duplicate event_id values"))

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

    known_users = set(user_ids)
    missing_identity: list[dict[str, Any]] = []
    unknown_users: list[dict[str, Any]] = []
    timestamp_errors: list[dict[str, Any]] = []
    late_events: list[dict[str, Any]] = []
    for index, row in enumerate(events, start=2):
        if row.get("event_name") != activation_event_name:
            continue
        event_id = row.get("event_id", f"row-{index}")
        user_id = row.get("user_id", "")
        if not user_id:
            missing_identity.append({"row": index, "event_id": event_id})
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
        checks.append(failed("activation_events_have_user_id", len(missing_identity), "activation events have user_id", missing_identity[:10]))
    else:
        checks.append(passed("activation_events_have_user_id", len(events), "activation events have user_id"))
    if unknown_users:
        checks.append(failed("activation_events_reference_known_users", len(unknown_users), "activation event user_id exists in users", unknown_users[:10]))
    else:
        checks.append(passed("activation_events_reference_known_users", len(events), "activation event user_id exists in users"))
    if timestamp_errors:
        checks.append(failed("activation_event_timestamps_valid", len(timestamp_errors), "occurred_at and received_at are timezone-aware", timestamp_errors[:10]))
    else:
        checks.append(passed("activation_event_timestamps_valid", len(events), "occurred_at and received_at are timezone-aware"))
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


def resolve_observation_end(users: list[dict[str, str]], events: list[dict[str, str]], spec: dict[str, Any], timezone: ZoneInfo) -> date:
    if spec.get("observation_end_date") != "auto":
        return date.fromisoformat(str(spec["observation_end_date"]))
    observed_dates: list[date] = []
    observed_dates.extend(parse_timestamp(row["registered_at"]).astimezone(timezone).date() for row in users if row.get("registered_at"))
    observed_dates.extend(parse_timestamp(row["occurred_at"]).astimezone(timezone).date() for row in events if row.get("occurred_at"))
    if not observed_dates:
        raise ValueError("cannot infer observation_end_date from empty segmentation inputs")
    return max(observed_dates)


def dimension_statuses(spec: dict[str, Any]) -> dict[str, str]:
    return {item["name"]: item["status"] for item in spec["dimensions"]}


def user_records(users: list[dict[str, str]], spec: dict[str, Any], observation_end: date, timezone: ZoneInfo) -> list[dict[str, Any]]:
    activation_window = int(spec["activation_window_days"])
    records: list[dict[str, Any]] = []
    for row in users:
        if spec.get("exclude_test_users", True) and parse_bool(row.get("is_test_user", "")):
            continue
        cohort_date = parse_timestamp(row["registered_at"]).astimezone(timezone).date()
        complete = cohort_date + timedelta(days=activation_window) <= observation_end
        if not complete:
            continue
        item = dict(row)
        item["cohort_date"] = cohort_date
        item["activated"] = False
        records.append(item)
    return records


def apply_activation(records: list[dict[str, Any]], events: list[dict[str, str]], spec: dict[str, Any], timezone: ZoneInfo) -> None:
    by_user = {record["user_id"]: record for record in records}
    activation_event = spec["activation_event_name"]
    activation_window = int(spec["activation_window_days"])
    for row in deduplicate_events(events):
        if row.get("event_name") != activation_event:
            continue
        record = by_user.get(row.get("user_id", ""))
        if record is None:
            continue
        event_date = parse_timestamp(row["occurred_at"]).astimezone(timezone).date()
        age_day = (event_date - record["cohort_date"]).days
        if 0 <= age_day <= activation_window:
            record["activated"] = True


def period_for_user(record: dict[str, Any], spec: dict[str, Any]) -> str | None:
    cohort_date = record["cohort_date"]
    for period in spec["analysis_periods"]:
        start = date.fromisoformat(period["cohort_date_from"])
        end = date.fromisoformat(period["cohort_date_to"])
        if start <= cohort_date <= end:
            return period["period_id"]
    return None


def counts_for(records: list[dict[str, Any]], period_id: str, dimension: str | None = None, value: str | None = None) -> tuple[int, int]:
    selected = [record for record in records if record.get("period_id") == period_id]
    if dimension is not None:
        selected = [record for record in selected if record.get(dimension, "") == value]
    eligible = len(selected)
    activated = sum(1 for record in selected if record.get("activated"))
    return eligible, activated


def empty_row(spec: dict[str, Any], row_type: str, dimension: str, segment_value: str) -> dict[str, str]:
    return {
        "metric_id": spec["metric_id"],
        "row_type": row_type,
        "dimension": dimension,
        "segment_value": segment_value,
        "period": "",
        "period_start": "",
        "period_end": "",
        "eligible_users": "",
        "activated_users": "",
        "activation_rate": "",
        "traffic_share": "",
        "is_reportable": "",
        "is_exploratory": "",
        "baseline_rate": "",
        "comparison_rate": "",
        "baseline_share": "",
        "comparison_share": "",
        "within_segment_effect": "",
        "composition_effect": "",
        "total_delta_contribution": "",
        "overall_baseline_rate": "",
        "overall_comparison_rate": "",
        "overall_delta": "",
    }


def calculate_table(users: list[dict[str, str]], events: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    timezone = ZoneInfo(spec["business_timezone"])
    observation_end = resolve_observation_end(users, deduplicate_events(events), spec, timezone)
    records = user_records(users, spec, observation_end, timezone)
    apply_activation(records, events, spec, timezone)
    for record in records:
        record["period_id"] = period_for_user(record, spec)
    records = [record for record in records if record["period_id"] is not None]
    min_cell = int(spec["minimum_cell_size"])
    statuses = dimension_statuses(spec)
    periods_by_id = {period["period_id"]: period for period in spec["analysis_periods"]}

    table: list[dict[str, str]] = []
    period_totals: dict[str, dict[str, float | int | None]] = {}
    for period_id in ("baseline", "comparison"):
        eligible, activated = counts_for(records, period_id)
        rate = ratio(activated, eligible)
        period_totals[period_id] = {"eligible": eligible, "activated": activated, "rate": rate}
        period = periods_by_id[period_id]
        row = empty_row(spec, "overall", "__overall__", "__all__")
        row.update({
            "period": period_id,
            "period_start": period["cohort_date_from"],
            "period_end": period["cohort_date_to"],
            "eligible_users": str(eligible),
            "activated_users": str(activated),
            "activation_rate": fmt(rate),
            "traffic_share": "1.000000" if eligible else "",
            "is_reportable": "true" if eligible >= min_cell else "false",
            "is_exploratory": "false",
        })
        if eligible < min_cell:
            row["activation_rate"] = ""
            row["traffic_share"] = ""
        table.append(row)

    for dimension in [item["name"] for item in spec["dimensions"]]:
        is_exploratory = statuses[dimension] == "exploratory"
        for period_id in ("baseline", "comparison"):
            period = periods_by_id[period_id]
            period_eligible = int(period_totals[period_id]["eligible"] or 0)
            values = sorted({record.get(dimension, "") for record in records if record.get("period_id") == period_id})
            for value in values:
                eligible, activated = counts_for(records, period_id, dimension, value)
                reportable = eligible >= min_cell
                row = empty_row(spec, "segment_metric", dimension, value)
                row.update({
                    "period": period_id,
                    "period_start": period["cohort_date_from"],
                    "period_end": period["cohort_date_to"],
                    "eligible_users": str(eligible),
                    "activated_users": str(activated),
                    "activation_rate": fmt(ratio(activated, eligible)) if reportable else "",
                    "traffic_share": fmt(ratio(eligible, period_eligible)) if reportable else "",
                    "is_reportable": "true" if reportable else "false",
                    "is_exploratory": "true" if is_exploratory else "false",
                })
                table.append(row)

    baseline_rate = period_totals["baseline"]["rate"]
    comparison_rate = period_totals["comparison"]["rate"]
    overall_delta = None if baseline_rate is None or comparison_rate is None else float(comparison_rate) - float(baseline_rate)
    primary = spec["primary_decomposition_dimension"]
    segment_values = sorted({record.get(primary, "") for record in records})
    decomposition_rows = 0
    for value in segment_values:
        base_eligible, base_activated = counts_for(records, "baseline", primary, value)
        comp_eligible, comp_activated = counts_for(records, "comparison", primary, value)
        base_total = int(period_totals["baseline"]["eligible"] or 0)
        comp_total = int(period_totals["comparison"]["eligible"] or 0)
        base_rate = ratio(base_activated, base_eligible)
        comp_rate = ratio(comp_activated, comp_eligible)
        base_share = ratio(base_eligible, base_total)
        comp_share = ratio(comp_eligible, comp_total)
        reportable = base_eligible >= min_cell and comp_eligible >= min_cell and base_rate is not None and comp_rate is not None
        within = composition = total = None
        if reportable and base_share is not None and comp_share is not None:
            within = comp_share * (comp_rate - base_rate)
            composition = (comp_share - base_share) * base_rate
            total = within + composition
        row = empty_row(spec, "decomposition", primary, value)
        row.update({
            "eligible_users": f"{base_eligible}->{comp_eligible}",
            "activated_users": f"{base_activated}->{comp_activated}",
            "is_reportable": "true" if reportable else "false",
            "is_exploratory": "false",
            "baseline_rate": fmt(base_rate) if reportable else "",
            "comparison_rate": fmt(comp_rate) if reportable else "",
            "baseline_share": fmt(base_share) if reportable else "",
            "comparison_share": fmt(comp_share) if reportable else "",
            "within_segment_effect": fmt(within),
            "composition_effect": fmt(composition),
            "total_delta_contribution": fmt(total),
            "overall_baseline_rate": fmt(float(baseline_rate)) if baseline_rate is not None else "",
            "overall_comparison_rate": fmt(float(comparison_rate)) if comparison_rate is not None else "",
            "overall_delta": fmt(overall_delta),
        })
        table.append(row)
        decomposition_rows += 1

    complete_users = len(records)
    eligible_before_window_filter = sum(1 for row in users if not (spec.get("exclude_test_users", True) and parse_bool(row.get("is_test_user", ""))))
    summary = {
        "rows": len(table),
        "segment_metric_rows": sum(1 for row in table if row["row_type"] == "segment_metric"),
        "decomposition_rows": decomposition_rows,
        "eligible_users": complete_users,
        "excluded_test_users": len(users) - eligible_before_window_filter,
        "excluded_incomplete_users": eligible_before_window_filter - complete_users,
        "observation_end_date": observation_end.isoformat(),
        "minimum_cell_size": min_cell,
        "overall_baseline_rate": fmt(float(baseline_rate)) if baseline_rate is not None else "",
        "overall_comparison_rate": fmt(float(comparison_rate)) if comparison_rate is not None else "",
        "overall_delta": fmt(overall_delta),
        "primary_decomposition_dimension": primary,
        "deduplicated_events": len(deduplicate_events(events)),
    }
    return table, summary


def calculate_segmentation(
    users: list[dict[str, str]],
    user_columns: list[str],
    events: list[dict[str, str]],
    event_columns: list[str],
    tracking_plan: dict[str, Any],
    spec: dict[str, Any],
) -> SegmentationResult:
    checks = validate_spec(spec, user_columns, tracking_plan)
    checks.extend(
        validate_inputs(
            users,
            user_columns,
            events,
            event_columns,
            str(spec.get("activation_event_name", "")),
            int(tracking_plan.get("max_late_minutes", 1440)),
        )
    )
    table: list[dict[str, str]] = []
    summary: dict[str, Any] = {
        "rows": 0,
        "segment_metric_rows": 0,
        "decomposition_rows": 0,
        "eligible_users": 0,
        "excluded_test_users": 0,
        "excluded_incomplete_users": 0,
        "observation_end_date": None,
        "minimum_cell_size": spec.get("minimum_cell_size"),
        "overall_baseline_rate": "",
        "overall_comparison_rate": "",
        "overall_delta": "",
        "primary_decomposition_dimension": spec.get("primary_decomposition_dimension"),
        "deduplicated_events": len(deduplicate_events(events)),
    }
    can_build = all(check["valid"] for check in checks if check["id"] != "event_ids_unique")
    if can_build:
        table, summary = calculate_table(users, events, spec)
        if table:
            checks.append(passed("segment_rows_present", len(table), "at least one segmentation output row"))
        else:
            checks.append(failed("segment_rows_present", 0, "at least one segmentation output row"))
    else:
        checks.append(failed("segment_rows_present", 0, "valid inputs before calculation"))
    report = {
        "valid": all(check["valid"] for check in checks),
        "checks": checks,
        "summary": summary,
    }
    return SegmentationResult(table=table, report=report)


def write_segments_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(users_path: Path, events_path: Path, tracking_plan_path: Path, spec_path: Path) -> SegmentationResult:
    users, user_columns = read_csv(users_path)
    events, event_columns = read_csv(events_path)
    tracking_plan = normalize_tracking_plan(read_json(tracking_plan_path))
    spec = normalize_spec(read_json(spec_path))
    return calculate_segmentation(users, user_columns, events, event_columns, tracking_plan, spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate declared segment rates and composition decomposition")
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--tracking-plan", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args.users, args.events, args.tracking_plan, args.spec)
    except (OSError, csv.Error, json.JSONDecodeError, ValueError, ZoneInfoNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 2
    if result.table:
        write_segments_csv(args.output, result.table)
    rendered_report = json.dumps(result.report, ensure_ascii=False, indent=2) + "\n"
    if args.report is not None:
        args.report.write_text(rendered_report, encoding="utf-8")
    print(rendered_report, end="")
    if result.report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
