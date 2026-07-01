from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REQUIRED_METRIC_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "period_start_at",
    "published_at",
    "value",
    "denominator",
    "is_complete_period",
    "revision_number",
    "source_status",
}
REQUIRED_CALENDAR_COLUMNS = {"date", "week_start", "day_of_week", "known_before_date"}
REQUIRED_SCENARIO_FIELDS = {
    "forecast_id",
    "target_metric",
    "target_segments",
    "time_column",
    "timestamp_column",
    "timezone",
    "frequency",
    "expected_start",
    "complete_through",
    "forecast_origin",
    "horizon_days",
    "calendar_start",
    "calendar_end",
    "revision_policy",
}


class TimeIndexAuditError(ValueError):
    """Raised when the audit cannot read or interpret its inputs."""


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TimeIndexAuditError("scenario must be a JSON object")
    return value


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise TimeIndexAuditError(f"{field} must be ISO date: {value}") from error


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise TimeIndexAuditError(f"{field} must be ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TimeIndexAuditError(f"{field} must be timezone-aware: {value}")
    return parsed


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise TimeIndexAuditError(f"is_complete_period must be true or false: {value}")
    return normalized == "true"


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": "error",
        "valid": True,
        "observed": observed,
        "expected": expected,
        "sample": [],
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


def validate_scenario(scenario: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SCENARIO_FIELDS - set(scenario))
    if missing:
        checks.append(failed("scenario_required_fields", missing, "all required scenario fields"))
        return checks, None
    checks.append(passed("scenario_required_fields", len(REQUIRED_SCENARIO_FIELDS)))

    segments = scenario.get("target_segments")
    if not isinstance(segments, list) or not segments or not all(isinstance(item, str) and item for item in segments):
        checks.append(failed("target_segments_declared", segments, "non-empty list of segment ids"))
        return checks, None
    checks.append(passed("target_segments_declared", segments))

    try:
        timezone = ZoneInfo(str(scenario["timezone"]))
    except ZoneInfoNotFoundError:
        checks.append(failed("timezone_valid", scenario["timezone"], "IANA timezone"))
        return checks, None
    checks.append(passed("timezone_valid", scenario["timezone"]))

    if scenario["frequency"] != "D":
        checks.append(failed("frequency_declared_daily", scenario["frequency"], "D"))
        return checks, None
    checks.append(passed("frequency_declared_daily", "D"))

    normalized = {
        "forecast_id": str(scenario["forecast_id"]),
        "target_metric": str(scenario["target_metric"]),
        "target_segments": segments,
        "time_column": str(scenario["time_column"]),
        "timestamp_column": str(scenario["timestamp_column"]),
        "timezone": timezone,
        "timezone_name": str(scenario["timezone"]),
        "expected_start": parse_date(str(scenario["expected_start"]), "expected_start"),
        "complete_through": parse_date(str(scenario["complete_through"]), "complete_through"),
        "forecast_origin": parse_timestamp(str(scenario["forecast_origin"]), "forecast_origin"),
        "horizon_days": int(scenario["horizon_days"]),
        "calendar_start": parse_date(str(scenario["calendar_start"]), "calendar_start"),
        "calendar_end": parse_date(str(scenario["calendar_end"]), "calendar_end"),
        "revision_policy": str(scenario["revision_policy"]),
    }
    return checks, normalized


def audit_time_index(
    *,
    metrics_path: Path,
    calendar_path: Path,
    scenario_path: Path,
    revisions_path: Path | None = None,
) -> dict[str, Any]:
    scenario = read_json(scenario_path)
    scenario_checks, spec = validate_scenario(scenario)
    checks = list(scenario_checks)
    metric_rows, metric_columns = read_csv(metrics_path)
    calendar_rows, calendar_columns = read_csv(calendar_path)

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

    if spec is None or missing_metric_columns or missing_calendar_columns:
        return build_report(scenario, checks, [])

    time_column = spec["time_column"]
    timestamp_column = spec["timestamp_column"]
    target_segments = set(spec["target_segments"])
    target_rows = [
        row
        for row in metric_rows
        if row.get("metric_id") == spec["target_metric"] and row.get("segment_id") in target_segments
    ]
    if target_rows:
        checks.append(passed("target_rows_present", len(target_rows), "rows for target metric and segments"))
    else:
        checks.append(failed("target_rows_present", 0, "rows for target metric and segments"))

    keys = [
        (row.get("metric_id", ""), row.get("segment_id", ""), row.get(time_column, ""))
        for row in target_rows
    ]
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        checks.append(
            failed(
                "metric_segment_date_unique",
                len(duplicates),
                "0 duplicate metric/segment/date keys",
                ["/".join(key) for key in duplicates[:10]],
            )
        )
    else:
        checks.append(passed("metric_segment_date_unique", len(keys), "0 duplicate keys"))

    calendar_dates: set[date] = set()
    calendar_errors: list[dict[str, Any]] = []
    for index, row in enumerate(calendar_rows, start=2):
        try:
            calendar_dates.add(parse_date(row.get("date", ""), "calendar.date"))
        except TimeIndexAuditError as error:
            calendar_errors.append({"row": index, "error": str(error)})
    if calendar_errors:
        checks.append(failed("calendar_dates_parse", len(calendar_errors), "valid ISO dates", calendar_errors[:10]))
    else:
        checks.append(passed("calendar_dates_parse", len(calendar_dates), "valid ISO dates"))

    required_calendar = set(daterange(spec["calendar_start"], spec["calendar_end"]))
    missing_calendar = sorted(required_calendar - calendar_dates)
    if missing_calendar:
        checks.append(
            failed(
                "calendar_covers_history_and_horizon",
                len(missing_calendar),
                "no missing calendar dates",
                [day.isoformat() for day in missing_calendar[:10]],
            )
        )
    else:
        checks.append(passed("calendar_covers_history_and_horizon", len(required_calendar)))

    by_segment: dict[str, set[date]] = defaultdict(set)
    parsed_target_rows: list[dict[str, Any]] = []
    date_parse_errors: list[dict[str, Any]] = []
    timezone_mismatches: list[dict[str, Any]] = []
    publication_errors: list[dict[str, Any]] = []
    complete_flag_errors: list[dict[str, Any]] = []
    incomplete_future_rows: list[dict[str, Any]] = []
    observed_not_in_calendar: list[dict[str, Any]] = []
    for index, row in enumerate(target_rows, start=2):
        try:
            observed_date = parse_date(row.get(time_column, ""), time_column)
            period_start = parse_timestamp(row.get(timestamp_column, ""), timestamp_column)
            published_at = parse_timestamp(row.get("published_at", ""), "published_at")
            is_complete = parse_bool(row.get("is_complete_period", ""))
        except TimeIndexAuditError as error:
            date_parse_errors.append({"row": index, "error": str(error), "metric_id": row.get("metric_id"), "segment_id": row.get("segment_id")})
            continue
        by_segment[row["segment_id"]].add(observed_date)
        parsed_target_rows.append({**row, "_observed_date": observed_date, "_published_at": published_at})
        if period_start.astimezone(spec["timezone"]).date() != observed_date:
            timezone_mismatches.append(
                {
                    "row": index,
                    "metric_id": row["metric_id"],
                    "segment_id": row["segment_id"],
                    "observed_date": observed_date.isoformat(),
                    "local_date": period_start.astimezone(spec["timezone"]).date().isoformat(),
                }
            )
        if observed_date not in calendar_dates:
            observed_not_in_calendar.append(
                {"row": index, "segment_id": row["segment_id"], "observed_date": observed_date.isoformat()}
            )
        if observed_date <= spec["complete_through"] and not is_complete:
            complete_flag_errors.append(
                {"row": index, "segment_id": row["segment_id"], "observed_date": observed_date.isoformat()}
            )
        if observed_date > spec["complete_through"] and not is_complete:
            incomplete_future_rows.append(
                {"row": index, "segment_id": row["segment_id"], "observed_date": observed_date.isoformat()}
            )
        if observed_date <= spec["complete_through"] and published_at > spec["forecast_origin"]:
            publication_errors.append(
                {
                    "row": index,
                    "segment_id": row["segment_id"],
                    "observed_date": observed_date.isoformat(),
                    "published_at": published_at.isoformat(),
                }
            )

    if date_parse_errors:
        checks.append(failed("target_dates_and_timestamps_parse", len(date_parse_errors), "valid timezone-aware dates/timestamps", date_parse_errors[:10]))
    else:
        checks.append(passed("target_dates_and_timestamps_parse", len(target_rows)))

    if timezone_mismatches:
        checks.append(failed("timezone_bucket_matches_observed_date", len(timezone_mismatches), "period_start_at local date equals observed_date", timezone_mismatches[:10]))
    else:
        checks.append(passed("timezone_bucket_matches_observed_date", len(parsed_target_rows)))

    if observed_not_in_calendar:
        checks.append(failed("observed_dates_exist_in_calendar", len(observed_not_in_calendar), "all observed dates in calendar", observed_not_in_calendar[:10]))
    else:
        checks.append(passed("observed_dates_exist_in_calendar", len(parsed_target_rows)))

    required_complete_dates = set(daterange(spec["expected_start"], spec["complete_through"]))
    missing_complete: list[dict[str, Any]] = []
    for segment in spec["target_segments"]:
        missing = sorted(required_complete_dates - by_segment.get(segment, set()))
        if missing:
            missing_complete.append({"segment_id": segment, "missing_dates": [day.isoformat() for day in missing]})
    if missing_complete:
        checks.append(failed("complete_history_has_no_missing_dates", len(missing_complete), "all complete dates exist for each target segment", missing_complete))
    else:
        checks.append(passed("complete_history_has_no_missing_dates", len(required_complete_dates) * len(spec["target_segments"])))

    if complete_flag_errors:
        checks.append(failed("complete_dates_marked_complete", len(complete_flag_errors), "complete history rows have is_complete_period=true", complete_flag_errors[:10]))
    else:
        checks.append(passed("complete_dates_marked_complete", len(parsed_target_rows)))

    if publication_errors:
        checks.append(failed("complete_history_available_by_origin", len(publication_errors), "complete history published before forecast origin", publication_errors[:10]))
    else:
        checks.append(passed("complete_history_available_by_origin", len(parsed_target_rows)))

    if incomplete_future_rows:
        checks.append(
            failed(
                "incomplete_rows_after_complete_through",
                len(incomplete_future_rows),
                "review incomplete rows before training",
                incomplete_future_rows[:10],
                severity="warning",
            )
        )
    else:
        checks.append(passed("incomplete_rows_after_complete_through", 0))

    revision_warnings = audit_revisions(revisions_path, spec) if revisions_path is not None else []
    if revision_warnings:
        checks.append(
            failed(
                "revisions_after_forecast_origin",
                len(revision_warnings),
                "no historical target revisions after forecast origin",
                revision_warnings[:10],
                severity="warning",
            )
        )
    else:
        checks.append(passed("revisions_after_forecast_origin", 0))

    series = summarize_series(spec, by_segment, parsed_target_rows)
    return build_report(scenario, checks, series)


def audit_revisions(path: Path, spec: dict[str, Any]) -> list[dict[str, Any]]:
    rows, columns = read_csv(path)
    required = {"metric_id", "segment_id", "observed_date", "revision_number", "revised_at"}
    if required - set(columns):
        return [{"error": f"revision columns missing: {sorted(required - set(columns))}"}]
    warnings: list[dict[str, Any]] = []
    target_segments = set(spec["target_segments"])
    for index, row in enumerate(rows, start=2):
        if row.get("metric_id") != spec["target_metric"] or row.get("segment_id") not in target_segments:
            continue
        observed_date = parse_date(row.get("observed_date", ""), "observed_date")
        revised_at = parse_timestamp(row.get("revised_at", ""), "revised_at")
        if observed_date <= spec["complete_through"] and revised_at > spec["forecast_origin"]:
            warnings.append(
                {
                    "row": index,
                    "segment_id": row["segment_id"],
                    "observed_date": observed_date.isoformat(),
                    "revision_number": row.get("revision_number"),
                    "revised_at": revised_at.isoformat(),
                }
            )
    return warnings


def summarize_series(
    spec: dict[str, Any],
    by_segment: dict[str, set[date]],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts_by_segment = Counter(row["segment_id"] for row in rows)
    incomplete_by_segment = Counter(
        row["segment_id"]
        for row in rows
        if row["_observed_date"] > spec["complete_through"] and not parse_bool(row["is_complete_period"])
    )
    summaries: list[dict[str, Any]] = []
    expected_complete = set(daterange(spec["expected_start"], spec["complete_through"]))
    for segment in spec["target_segments"]:
        dates = sorted(by_segment.get(segment, set()))
        missing = sorted(expected_complete - set(dates))
        summaries.append(
            {
                "metric_id": spec["target_metric"],
                "segment_id": segment,
                "frequency": "D",
                "date_start": dates[0].isoformat() if dates else None,
                "date_end": dates[-1].isoformat() if dates else None,
                "observed_points": counts_by_segment[segment],
                "expected_complete_points": len(expected_complete),
                "missing_complete_dates": [day.isoformat() for day in missing],
                "incomplete_rows_after_complete_through": incomplete_by_segment[segment],
            }
        )
    return summaries


def build_report(
    scenario: dict[str, Any],
    checks: list[dict[str, Any]],
    series: list[dict[str, Any]],
) -> dict[str, Any]:
    error_failures = [check for check in checks if not check["valid"] and check["severity"] == "error"]
    warning_failures = [check for check in checks if not check["valid"] and check["severity"] == "warning"]
    return {
        "audit_id": "time-index-audit",
        "forecast_id": scenario.get("forecast_id"),
        "valid": not error_failures,
        "warning_count": len(warning_failures),
        "error_count": len(error_failures),
        "checks": checks,
        "series": series,
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(error_failures) + len(warning_failures),
            "blocking_errors": [check["id"] for check in error_failures],
            "warnings": [check["id"] for check in warning_failures],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit time index, calendar coverage, and data availability for a forecast scenario.")
    parser.add_argument("--metrics", type=Path, required=True, help="metric_observations.csv")
    parser.add_argument("--calendar", type=Path, required=True, help="calendar.csv")
    parser.add_argument("--scenario", type=Path, required=True, help="forecast_scenario.json")
    parser.add_argument("--revisions", type=Path, help="optional data_revisions.csv")
    parser.add_argument("--output", type=Path, help="write JSON report to this path")
    parser.add_argument("--fail-on-warning", action="store_true", help="return non-zero when warning checks fail")
    args = parser.parse_args()
    try:
        report = audit_time_index(
            metrics_path=args.metrics,
            calendar_path=args.calendar,
            scenario_path=args.scenario,
            revisions_path=args.revisions,
        )
    except (OSError, TimeIndexAuditError) as error:
        parser.error(str(error))

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
