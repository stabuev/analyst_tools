from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REQUIRED_EVENT_COLUMNS = {
    "event_id",
    "segment_id",
    "occurred_at",
    "available_at",
    "event_type",
    "delta_active",
    "ingestion_status",
}
REQUIRED_METRIC_COLUMNS = {"metric_id", "segment_id", "observed_date", "value", "is_complete_period"}
REQUIRED_CALENDAR_COLUMNS = {"date", "week_start"}
REQUIRED_SCENARIO_FIELDS = {
    "forecast_id",
    "target_metric",
    "target_segments",
    "timezone",
    "frequency",
    "complete_through",
    "forecast_origin",
}
REQUIRED_SPEC_FIELDS = {
    "resampling_id",
    "source_time_column",
    "availability_column",
    "segment_column",
    "value_column",
    "target_metric",
    "target_segments",
    "timezone",
    "expected_start",
    "complete_through",
    "forecast_origin",
    "daily_frequency",
    "week_start_day",
    "weekly_label",
    "weekly_closed",
    "stock_aggregation",
    "weekly_stock_policy",
    "opening_balances",
    "complete_period_policy",
    "partial_period_policy",
    "reconciliation_tolerance",
}


class ResamplingError(ValueError):
    """Raised when resampling inputs cannot be interpreted."""


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ResamplingError(f"{path.name} must contain a JSON object")
    return value


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ResamplingError(f"{field} must be ISO date: {value}") from error


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ResamplingError(f"{field} must be ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResamplingError(f"{field} must be timezone-aware: {value}")
    return parsed


def parse_int(value: str, field: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ResamplingError(f"{field} must be an integer: {value}") from error


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ResamplingError(f"is_complete_period must be true or false: {value}")
    return normalized == "true"


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def monday_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def passed(check_id: str, observed: Any = None, expected: Any = None, sample: list[Any] | None = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": "error",
        "valid": True,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def failed(
    check_id: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
    *,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def normalize_spec(spec: dict[str, Any], scenario: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing_spec:
        checks.append(failed("resampling_spec_required_fields", missing_spec, "all required resampling fields"))
        return checks, None
    checks.append(passed("resampling_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))

    missing_scenario = sorted(REQUIRED_SCENARIO_FIELDS - set(scenario))
    if missing_scenario:
        checks.append(failed("scenario_required_fields", missing_scenario, "all required scenario fields"))
        return checks, None
    checks.append(passed("scenario_required_fields", len(REQUIRED_SCENARIO_FIELDS)))

    segments = spec.get("target_segments")
    if not isinstance(segments, list) or not segments or not all(isinstance(item, str) and item for item in segments):
        checks.append(failed("target_segments_declared", segments, "non-empty list of segment ids"))
        return checks, None
    checks.append(passed("target_segments_declared", segments))

    try:
        timezone = ZoneInfo(str(spec["timezone"]))
    except ZoneInfoNotFoundError:
        checks.append(failed("timezone_valid", spec["timezone"], "IANA timezone"))
        return checks, None
    checks.append(passed("timezone_valid", spec["timezone"]))

    opening = spec.get("opening_balances")
    if not isinstance(opening, dict):
        checks.append(failed("opening_balances_declared", opening, "object keyed by segment"))
        return checks, None
    missing_opening = sorted(set(segments) - set(opening))
    if missing_opening:
        checks.append(failed("opening_balances_declared", missing_opening, "opening balance for each target segment"))
        return checks, None
    checks.append(passed("opening_balances_declared", sorted(opening)))

    normalized = {
        "resampling_id": str(spec["resampling_id"]),
        "forecast_id": str(scenario["forecast_id"]),
        "source_time_column": str(spec["source_time_column"]),
        "availability_column": str(spec["availability_column"]),
        "segment_column": str(spec["segment_column"]),
        "value_column": str(spec["value_column"]),
        "target_metric": str(spec["target_metric"]),
        "target_segments": segments,
        "timezone": timezone,
        "timezone_name": str(spec["timezone"]),
        "expected_start": parse_date(str(spec["expected_start"]), "expected_start"),
        "complete_through": parse_date(str(spec["complete_through"]), "complete_through"),
        "forecast_origin": parse_timestamp(str(spec["forecast_origin"]), "forecast_origin"),
        "opening_balances": {segment: int(opening[segment]) for segment in segments},
        "reconciliation_tolerance": int(spec["reconciliation_tolerance"]),
    }

    alignment_errors = []
    for field in ("target_metric", "timezone", "complete_through", "forecast_origin"):
        if str(spec[field]) != str(scenario[field]):
            alignment_errors.append({"field": field, "spec": spec[field], "scenario": scenario[field]})
    if scenario["frequency"] != spec["daily_frequency"]:
        alignment_errors.append({"field": "frequency", "spec": spec["daily_frequency"], "scenario": scenario["frequency"]})
    if list(scenario["target_segments"]) != segments:
        alignment_errors.append({"field": "target_segments", "spec": segments, "scenario": scenario["target_segments"]})
    if alignment_errors:
        checks.append(failed("scenario_and_resampling_spec_align", len(alignment_errors), "matching forecast setup fields", alignment_errors))
    else:
        checks.append(passed("scenario_and_resampling_spec_align", 6))

    policy_errors = []
    expected_policies = {
        "daily_frequency": "D",
        "week_start_day": "Monday",
        "weekly_label": "left",
        "weekly_closed": "left",
        "stock_aggregation": "opening_balance_plus_cumulative_delta",
        "weekly_stock_policy": "last_complete_observation",
        "complete_period_policy": "exclude_after_complete_through",
    }
    for field, expected in expected_policies.items():
        if spec[field] != expected:
            policy_errors.append({"field": field, "observed": spec[field], "expected": expected})
    if policy_errors:
        checks.append(failed("resampling_policies_supported", len(policy_errors), "supported deterministic policies", policy_errors))
    else:
        checks.append(passed("resampling_policies_supported", expected_policies))

    return checks, normalized


def build_resampling_package(
    *,
    events_path: Path,
    metrics_path: Path,
    calendar_path: Path,
    scenario_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    events, event_columns = read_csv(events_path)
    metrics, metric_columns = read_csv(metrics_path)
    calendar, calendar_columns = read_csv(calendar_path)
    scenario = read_json(scenario_path)
    spec = read_json(spec_path)

    spec_checks, normalized = normalize_spec(spec, scenario)
    checks = list(spec_checks)

    missing_event_columns = sorted(REQUIRED_EVENT_COLUMNS - set(event_columns))
    if missing_event_columns:
        checks.append(failed("event_columns_present", missing_event_columns, "all required event columns"))
    else:
        checks.append(passed("event_columns_present", len(event_columns)))

    missing_metric_columns = sorted(REQUIRED_METRIC_COLUMNS - set(metric_columns))
    if missing_metric_columns:
        checks.append(failed("metric_columns_present", missing_metric_columns, "all required metric columns"))
    else:
        checks.append(passed("metric_columns_present", len(metric_columns)))

    missing_calendar_columns = sorted(REQUIRED_CALENDAR_COLUMNS - set(calendar_columns))
    if missing_calendar_columns:
        checks.append(failed("calendar_columns_present", missing_calendar_columns, "all required calendar columns"))
    else:
        checks.append(passed("calendar_columns_present", len(calendar_columns)))

    if normalized is None or missing_event_columns or missing_metric_columns or missing_calendar_columns:
        report = build_report(spec, scenario, checks, [], [], [])
        return {"report": report, "daily_rows": [], "weekly_rows": [], "reconciliation_rows": []}

    target_segments = set(normalized["target_segments"])
    event_id_counts = Counter(row.get("event_id", "") for row in events)
    duplicate_event_ids = [event_id for event_id, count in event_id_counts.items() if event_id and count > 1]
    if duplicate_event_ids:
        checks.append(failed("event_id_unique", len(duplicate_event_ids), "0 duplicate event ids", duplicate_event_ids[:10]))
    else:
        checks.append(passed("event_id_unique", len(events), "0 duplicate event ids"))

    published_rows, published_checks = parse_published_metrics(metrics, normalized)
    checks.extend(published_checks)
    observed_end = max((row["_observed_date"] for row in published_rows), default=normalized["complete_through"])

    calendar_dates = parse_calendar_dates(calendar)
    required_calendar = set(daterange(normalized["expected_start"], observed_end))
    missing_calendar = sorted(required_calendar - calendar_dates)
    if missing_calendar:
        checks.append(
            failed(
                "calendar_dates_cover_resampling_window",
                len(missing_calendar),
                "calendar row for each output date",
                [day.isoformat() for day in missing_calendar[:10]],
            )
        )
    else:
        checks.append(passed("calendar_dates_cover_resampling_window", len(required_calendar)))

    parsed_events, event_parse_errors, availability_errors, shifted_samples = parse_events(events, normalized)
    if event_parse_errors:
        checks.append(failed("events_parse_and_bucket", len(event_parse_errors), "valid timestamps and integer deltas", event_parse_errors[:10]))
    else:
        checks.append(passed("events_parse_and_bucket", len(parsed_events)))

    if shifted_samples:
        checks.append(
            passed(
                "timezone_normalized_business_date",
                len(shifted_samples),
                "UTC-date shifts are bucketed by business timezone",
                shifted_samples[:10],
            )
        )
    else:
        checks.append(passed("timezone_normalized_business_date", 0))

    if availability_errors:
        checks.append(
            failed(
                "complete_events_available_by_origin",
                len(availability_errors),
                "complete-period events available before forecast origin",
                availability_errors[:10],
            )
        )
    else:
        checks.append(passed("complete_events_available_by_origin", len(parsed_events)))

    daily_rows = build_daily_rows(parsed_events, normalized, observed_end)
    weekly_rows = build_weekly_rows(daily_rows)
    reconciliation_rows, reconciliation_failures = reconcile_daily(daily_rows, published_rows, normalized)
    if reconciliation_failures:
        checks.append(
            failed(
                "published_series_reconciles",
                len(reconciliation_failures),
                f"difference <= {normalized['reconciliation_tolerance']}",
                reconciliation_failures[:10],
            )
        )
    else:
        checks.append(passed("published_series_reconciles", len(reconciliation_rows)))

    partial_daily = [row for row in daily_rows if row["is_complete_period"] == "false"]
    if partial_daily:
        checks.append(
            failed(
                "partial_daily_rows_excluded_from_training",
                len(partial_daily),
                "partial daily rows are visible but not used for training",
                partial_daily[:10],
                severity="warning",
            )
        )
    else:
        checks.append(passed("partial_daily_rows_excluded_from_training", 0))

    incomplete_weeks = [row for row in weekly_rows if row["is_complete_week"] == "false"]
    if incomplete_weeks:
        checks.append(
            failed(
                "incomplete_weeks_excluded_from_training",
                len(incomplete_weeks),
                "incomplete weekly periods are visible but not used for training",
                incomplete_weeks[:10],
                severity="warning",
            )
        )
    else:
        checks.append(passed("incomplete_weeks_excluded_from_training", 0))

    report = build_report(spec, scenario, checks, daily_rows, weekly_rows, reconciliation_rows)
    return {
        "report": report,
        "daily_rows": daily_rows,
        "weekly_rows": weekly_rows,
        "reconciliation_rows": reconciliation_rows,
    }


def parse_calendar_dates(rows: list[dict[str, str]]) -> set[date]:
    dates: set[date] = set()
    for row in rows:
        dates.add(parse_date(row.get("date", ""), "calendar.date"))
    return dates


def parse_published_metrics(
    rows: list[dict[str, str]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    parsed: list[dict[str, Any]] = []
    target_segments = set(spec["target_segments"])
    parse_errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        if row.get("metric_id") != spec["target_metric"] or row.get("segment_id") not in target_segments:
            continue
        try:
            parsed.append(
                {
                    **row,
                    "_row": index,
                    "_observed_date": parse_date(row.get("observed_date", ""), "observed_date"),
                    "_value": parse_int(row.get("value", ""), "value"),
                    "_is_complete": parse_bool(row.get("is_complete_period", "")),
                }
            )
        except ResamplingError as error:
            parse_errors.append({"row": index, "error": str(error)})
    if parse_errors:
        checks.append(failed("published_metric_rows_parse", len(parse_errors), "valid dates, values, and complete flags", parse_errors[:10]))
    else:
        checks.append(passed("published_metric_rows_parse", len(parsed)))

    keys = [(row["segment_id"], row["_observed_date"]) for row in parsed]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        checks.append(
            failed(
                "published_metric_segment_date_unique",
                len(duplicates),
                "0 duplicate published metric keys",
                [{"segment_id": segment, "observed_date": day.isoformat()} for segment, day in duplicates[:10]],
            )
        )
    else:
        checks.append(passed("published_metric_segment_date_unique", len(parsed)))
    return parsed, checks


def parse_events(
    rows: list[dict[str, str]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    parsed_events: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    availability_errors: list[dict[str, Any]] = []
    shifted_samples: list[dict[str, Any]] = []
    target_segments = set(spec["target_segments"])
    for index, row in enumerate(rows, start=2):
        segment_id = row.get(spec["segment_column"], "")
        if segment_id not in target_segments:
            continue
        try:
            occurred_at = parse_timestamp(row.get(spec["source_time_column"], ""), spec["source_time_column"])
            available_at = parse_timestamp(row.get(spec["availability_column"], ""), spec["availability_column"])
            delta = parse_int(row.get(spec["value_column"], ""), spec["value_column"])
        except ResamplingError as error:
            parse_errors.append({"row": index, "event_id": row.get("event_id"), "error": str(error)})
            continue
        business_date = occurred_at.astimezone(spec["timezone"]).date()
        utc_date = occurred_at.date()
        if utc_date != business_date and len(shifted_samples) < 10:
            shifted_samples.append(
                {
                    "event_id": row["event_id"],
                    "utc_date": utc_date.isoformat(),
                    "business_date": business_date.isoformat(),
                }
            )
        if business_date <= spec["complete_through"] and available_at > spec["forecast_origin"]:
            availability_errors.append(
                {
                    "row": index,
                    "event_id": row["event_id"],
                    "business_date": business_date.isoformat(),
                    "available_at": available_at.isoformat(),
                }
            )
        parsed_events.append(
            {
                "row": index,
                "event_id": row["event_id"],
                "segment_id": segment_id,
                "business_date": business_date,
                "delta": delta,
                "ingestion_status": row.get("ingestion_status", ""),
            }
        )
    return parsed_events, parse_errors, availability_errors, shifted_samples


def build_daily_rows(events: list[dict[str, Any]], spec: dict[str, Any], observed_end: date) -> list[dict[str, Any]]:
    deltas: dict[tuple[str, date], int] = defaultdict(int)
    event_counts: Counter[tuple[str, date]] = Counter()
    for event in events:
        key = (event["segment_id"], event["business_date"])
        deltas[key] += event["delta"]
        event_counts[key] += 1

    rows: list[dict[str, Any]] = []
    for segment_id in spec["target_segments"]:
        balance = spec["opening_balances"][segment_id]
        for day in daterange(spec["expected_start"], observed_end):
            key = (segment_id, day)
            delta = deltas.get(key, 0)
            balance += delta
            is_complete = day <= spec["complete_through"]
            rows.append(
                {
                    "metric_id": spec["target_metric"],
                    "segment_id": segment_id,
                    "observed_date": day.isoformat(),
                    "frequency": "D",
                    "delta_active": delta,
                    "value": balance,
                    "source_event_count": event_counts.get(key, 0),
                    "is_complete_period": str(is_complete).lower(),
                    "include_in_training": str(is_complete).lower(),
                }
            )
    return rows


def build_weekly_rows(daily_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
    for row in daily_rows:
        day = parse_date(row["observed_date"], "observed_date")
        grouped[(row["segment_id"], monday_start(day))].append(row)

    rows: list[dict[str, Any]] = []
    for (segment_id, week_start), group_rows in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        ordered = sorted(group_rows, key=lambda row: row["observed_date"])
        complete_days = [row for row in ordered if row["is_complete_period"] == "true"]
        is_complete_week = len(ordered) == 7 and len(complete_days) == 7
        last_row = ordered[-1]
        rows.append(
            {
                "metric_id": last_row["metric_id"],
                "segment_id": segment_id,
                "week_start": week_start.isoformat(),
                "week_end": (week_start + timedelta(days=6)).isoformat(),
                "frequency": "W-MON",
                "weekly_label": "left",
                "weekly_closed": "left",
                "delta_active": sum(parse_int(str(row["delta_active"]), "delta_active") for row in ordered),
                "value": last_row["value"],
                "observed_days": len(ordered),
                "complete_days": len(complete_days),
                "is_complete_week": str(is_complete_week).lower(),
                "include_in_training": str(is_complete_week).lower(),
            }
        )
    return rows


def reconcile_daily(
    daily_rows: list[dict[str, Any]],
    published_rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    published = {
        (row["segment_id"], row["_observed_date"]): row
        for row in published_rows
    }
    reconciliation_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    tolerance = spec["reconciliation_tolerance"]
    for row in daily_rows:
        observed_date = parse_date(row["observed_date"], "observed_date")
        key = (row["segment_id"], observed_date)
        published_row = published.get(key)
        if published_row is None:
            if observed_date <= spec["complete_through"]:
                failures.append({"segment_id": row["segment_id"], "observed_date": row["observed_date"], "issue": "missing_published_metric"})
            continue
        difference = parse_int(str(row["value"]), "value") - published_row["_value"]
        status = "pass" if abs(difference) <= tolerance else "fail"
        if status == "fail" and observed_date <= spec["complete_through"]:
            failures.append(
                {
                    "segment_id": row["segment_id"],
                    "observed_date": row["observed_date"],
                    "computed_value": row["value"],
                    "published_value": published_row["_value"],
                    "difference": difference,
                }
            )
        reconciliation_rows.append(
            {
                "metric_id": row["metric_id"],
                "segment_id": row["segment_id"],
                "observed_date": row["observed_date"],
                "computed_value": row["value"],
                "published_value": published_row["_value"],
                "difference": difference,
                "status": status,
                "is_complete_period": row["is_complete_period"],
            }
        )
    return reconciliation_rows, failures


def build_report(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    checks: list[dict[str, Any]],
    daily_rows: list[dict[str, Any]],
    weekly_rows: list[dict[str, Any]],
    reconciliation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    error_failures = [check for check in checks if not check["valid"] and check["severity"] == "error"]
    warning_failures = [check for check in checks if not check["valid"] and check["severity"] == "warning"]
    series = summarize_series(daily_rows, weekly_rows)
    return {
        "audit_id": "resampling-audit",
        "resampling_id": spec.get("resampling_id"),
        "forecast_id": scenario.get("forecast_id"),
        "valid": not error_failures,
        "warning_count": len(warning_failures),
        "error_count": len(error_failures),
        "checks": checks,
        "series": series,
        "outputs": {
            "daily_rows": len(daily_rows),
            "weekly_rows": len(weekly_rows),
            "reconciliation_rows": len(reconciliation_rows),
            "training_daily_rows": sum(1 for row in daily_rows if row.get("include_in_training") == "true"),
            "training_weekly_rows": sum(1 for row in weekly_rows if row.get("include_in_training") == "true"),
        },
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(error_failures) + len(warning_failures),
            "blocking_errors": [check["id"] for check in error_failures],
            "warnings": [check["id"] for check in warning_failures],
        },
    }


def summarize_series(daily_rows: list[dict[str, Any]], weekly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments = sorted({row["segment_id"] for row in daily_rows} | {row["segment_id"] for row in weekly_rows})
    summaries: list[dict[str, Any]] = []
    for segment_id in segments:
        segment_daily = [row for row in daily_rows if row["segment_id"] == segment_id]
        segment_weekly = [row for row in weekly_rows if row["segment_id"] == segment_id]
        summaries.append(
            {
                "segment_id": segment_id,
                "daily_rows": len(segment_daily),
                "complete_daily_rows": sum(1 for row in segment_daily if row["is_complete_period"] == "true"),
                "partial_daily_rows": sum(1 for row in segment_daily if row["is_complete_period"] == "false"),
                "weekly_rows": len(segment_weekly),
                "complete_weekly_rows": sum(1 for row in segment_weekly if row["is_complete_week"] == "true"),
                "partial_weekly_rows": sum(1 for row in segment_weekly if row["is_complete_week"] == "false"),
            }
        )
    return summaries


def write_package(output_dir: Path, package: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "daily_resampled.csv",
        package["daily_rows"],
        [
            "metric_id",
            "segment_id",
            "observed_date",
            "frequency",
            "delta_active",
            "value",
            "source_event_count",
            "is_complete_period",
            "include_in_training",
        ],
    )
    write_csv(
        output_dir / "weekly_resampled.csv",
        package["weekly_rows"],
        [
            "metric_id",
            "segment_id",
            "week_start",
            "week_end",
            "frequency",
            "weekly_label",
            "weekly_closed",
            "delta_active",
            "value",
            "observed_days",
            "complete_days",
            "is_complete_week",
            "include_in_training",
        ],
    )
    write_csv(
        output_dir / "reconciliation.csv",
        package["reconciliation_rows"],
        [
            "metric_id",
            "segment_id",
            "observed_date",
            "computed_value",
            "published_value",
            "difference",
            "status",
            "is_complete_period",
        ],
    )
    (output_dir / "resampling_report.json").write_text(
        json.dumps(package["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Resample event-level subscription deltas into daily and weekly forecast series.")
    parser.add_argument("--events", type=Path, required=True, help="subscription_events.csv")
    parser.add_argument("--metrics", type=Path, required=True, help="metric_observations.csv for reconciliation")
    parser.add_argument("--calendar", type=Path, required=True, help="calendar.csv")
    parser.add_argument("--scenario", type=Path, required=True, help="forecast_scenario.json")
    parser.add_argument("--spec", type=Path, required=True, help="resampling_spec.json")
    parser.add_argument("--output-dir", type=Path, help="directory for daily/weekly/reconciliation outputs")
    parser.add_argument("--fail-on-warning", action="store_true", help="return non-zero when warning checks fail")
    args = parser.parse_args()
    try:
        package = build_resampling_package(
            events_path=args.events,
            metrics_path=args.metrics,
            calendar_path=args.calendar,
            scenario_path=args.scenario,
            spec_path=args.spec,
        )
    except (OSError, ResamplingError) as error:
        parser.error(str(error))

    if args.output_dir:
        write_package(args.output_dir, package)
    print(json.dumps(package["report"], ensure_ascii=False, indent=2))
    report = package["report"]
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
