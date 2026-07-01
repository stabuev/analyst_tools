from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REQUIRED_SOURCE_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "frequency",
    "delta_active",
    "value",
    "is_complete_period",
    "include_in_training",
}
REQUIRED_CALENDAR_COLUMNS = {
    "date",
    "week_start",
    "day_of_week",
    "is_weekend",
    "is_holiday",
    "holiday_name",
    "campaign_active",
    "release_active",
    "known_before_date",
}
REQUIRED_CAMPAIGN_COLUMNS = {"campaign_id", "start_date", "end_date", "known_before_date", "target_segment"}
REQUIRED_RELEASE_COLUMNS = {
    "release_id",
    "platform",
    "start_date",
    "end_date",
    "known_before_date",
    "expected_metric_impact",
}
REQUIRED_SCENARIO_FIELDS = {
    "forecast_id",
    "target_metric",
    "target_segments",
    "timezone",
    "frequency",
    "expected_start",
    "complete_through",
    "forecast_origin",
    "horizon_days",
    "calendar_start",
    "calendar_end",
}
REQUIRED_SPEC_FIELDS = {
    "profile_id",
    "source_table",
    "calendar_table",
    "campaign_table",
    "release_table",
    "target_metric",
    "target_segments",
    "time_column",
    "value_column",
    "delta_column",
    "complete_flag_column",
    "calendar_date_column",
    "timezone",
    "frequency",
    "expected_start",
    "complete_through",
    "forecast_origin",
    "seasonal_period_days",
    "trend_policy",
    "seasonality_policy",
    "calendar_effect_policy",
    "minimum_observations_per_weekday",
    "minimum_month_cycles",
    "profile_dimensions",
    "calendar_effect_columns",
}
WEEKDAY_ORDER = {
    "Monday": 1,
    "Tuesday": 2,
    "Wednesday": 3,
    "Thursday": 4,
    "Friday": 5,
    "Saturday": 6,
    "Sunday": 7,
}


class SeasonalityProfileError(ValueError):
    """Raised when seasonality profiling inputs cannot be interpreted."""


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
        raise SeasonalityProfileError(f"{path.name} must contain a JSON object")
    return value


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise SeasonalityProfileError(f"{field} must be ISO date: {value}") from error


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SeasonalityProfileError(f"{field} must be ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SeasonalityProfileError(f"{field} must be timezone-aware: {value}")
    return parsed


def parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise SeasonalityProfileError(f"{field} must be true or false: {value}")
    return normalized == "true"


def parse_number(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise SeasonalityProfileError(f"{field} must be numeric: {value}") from error


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def format_value(value: float | int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


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
        checks.append(failed("seasonality_spec_required_fields", missing_spec, "all required seasonality profile fields"))
        return checks, None
    checks.append(passed("seasonality_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))

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

    effect_columns = spec.get("calendar_effect_columns")
    if not isinstance(effect_columns, list) or not effect_columns:
        checks.append(failed("calendar_effect_columns_declared", effect_columns, "non-empty list of calendar boolean columns"))
        return checks, None
    checks.append(passed("calendar_effect_columns_declared", effect_columns))

    expected_policies = {
        "trend_policy": "fit_linear_trend_on_complete_training_rows",
        "seasonality_policy": "profile_complete_history_by_calendar_keys",
        "calendar_effect_policy": "known_before_forecast_origin_only",
    }
    policy_errors = []
    for field, expected in expected_policies.items():
        if spec[field] != expected:
            policy_errors.append({"field": field, "observed": spec[field], "expected": expected})
    if policy_errors:
        checks.append(failed("seasonality_policies_supported", len(policy_errors), "supported profile policies", policy_errors))
    else:
        checks.append(passed("seasonality_policies_supported", expected_policies))

    if int(spec["seasonal_period_days"]) != 7:
        checks.append(failed("seasonal_period_declared_weekly", spec["seasonal_period_days"], 7))
    else:
        checks.append(passed("seasonal_period_declared_weekly", 7))

    alignment_errors = []
    for field in ("target_metric", "target_segments", "timezone", "frequency", "expected_start", "complete_through", "forecast_origin"):
        if spec[field] != scenario[field]:
            alignment_errors.append({"field": field, "spec": spec[field], "scenario": scenario[field]})
    if alignment_errors:
        checks.append(failed("scenario_and_seasonality_spec_align", len(alignment_errors), "matching forecast setup fields", alignment_errors))
    else:
        checks.append(passed("scenario_and_seasonality_spec_align", 7))

    normalized = {
        "profile_id": str(spec["profile_id"]),
        "forecast_id": str(scenario["forecast_id"]),
        "target_metric": str(spec["target_metric"]),
        "target_segments": [str(segment) for segment in segments],
        "time_column": str(spec["time_column"]),
        "value_column": str(spec["value_column"]),
        "delta_column": str(spec["delta_column"]),
        "complete_flag_column": str(spec["complete_flag_column"]),
        "calendar_date_column": str(spec["calendar_date_column"]),
        "timezone": timezone,
        "timezone_name": str(spec["timezone"]),
        "frequency": str(spec["frequency"]),
        "expected_start": parse_date(str(spec["expected_start"]), "expected_start"),
        "complete_through": parse_date(str(spec["complete_through"]), "complete_through"),
        "forecast_origin": parse_timestamp(str(spec["forecast_origin"]), "forecast_origin"),
        "horizon_days": int(scenario["horizon_days"]),
        "calendar_start": parse_date(str(scenario["calendar_start"]), "calendar_start"),
        "calendar_end": parse_date(str(scenario["calendar_end"]), "calendar_end"),
        "minimum_observations_per_weekday": int(spec["minimum_observations_per_weekday"]),
        "minimum_month_cycles": int(spec["minimum_month_cycles"]),
        "profile_dimensions": [str(item) for item in spec["profile_dimensions"]],
        "calendar_effect_columns": [str(item) for item in effect_columns],
    }
    return checks, normalized


def build_seasonality_profile_package(
    *,
    series_path: Path,
    calendar_path: Path,
    campaign_path: Path,
    release_path: Path,
    scenario_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    source_rows, source_columns = read_csv(series_path)
    calendar_rows, calendar_columns = read_csv(calendar_path)
    campaign_rows, campaign_columns = read_csv(campaign_path)
    release_rows, release_columns = read_csv(release_path)
    scenario = read_json(scenario_path)
    spec = read_json(spec_path)

    spec_checks, normalized = normalize_spec(spec, scenario)
    checks = list(spec_checks)

    missing_source_columns = sorted(REQUIRED_SOURCE_COLUMNS - set(source_columns))
    missing_calendar_columns = sorted(REQUIRED_CALENDAR_COLUMNS - set(calendar_columns))
    missing_campaign_columns = sorted(REQUIRED_CAMPAIGN_COLUMNS - set(campaign_columns))
    missing_release_columns = sorted(REQUIRED_RELEASE_COLUMNS - set(release_columns))

    if missing_source_columns:
        checks.append(failed("source_columns_present", missing_source_columns, "all required daily source columns"))
    else:
        checks.append(passed("source_columns_present", len(source_columns)))
    if missing_calendar_columns:
        checks.append(failed("calendar_columns_present", missing_calendar_columns, "all required calendar columns"))
    else:
        checks.append(passed("calendar_columns_present", len(calendar_columns)))
    if missing_campaign_columns:
        checks.append(failed("campaign_columns_present", missing_campaign_columns, "all required campaign columns"))
    else:
        checks.append(passed("campaign_columns_present", len(campaign_columns)))
    if missing_release_columns:
        checks.append(failed("release_columns_present", missing_release_columns, "all required release columns"))
    else:
        checks.append(passed("release_columns_present", len(release_columns)))

    if normalized is None or missing_source_columns or missing_calendar_columns or missing_campaign_columns or missing_release_columns:
        report = build_report(spec, scenario, checks, [], [], [])
        return {"report": report, "trend_rows": [], "seasonality_rows": [], "calendar_effect_rows": []}

    missing_effect_columns = sorted(set(normalized["calendar_effect_columns"]) - set(calendar_columns))
    if missing_effect_columns:
        checks.append(failed("calendar_effect_columns_present", missing_effect_columns, "declared effect columns exist in calendar"))
    else:
        checks.append(passed("calendar_effect_columns_present", normalized["calendar_effect_columns"]))

    parsed_source, source_parse_checks = parse_source_rows(source_rows, normalized)
    parsed_calendar, calendar_parse_checks = parse_calendar_rows(calendar_rows, normalized)
    parsed_campaigns, campaign_parse_checks = parse_event_rows(campaign_rows, "campaign", normalized)
    parsed_releases, release_parse_checks = parse_event_rows(release_rows, "release", normalized)
    checks.extend(source_parse_checks)
    checks.extend(calendar_parse_checks)
    checks.extend(campaign_parse_checks)
    checks.extend(release_parse_checks)

    source_duplicates = [
        {"segment_id": segment, "observed_date": day.isoformat()}
        for (segment, day), count in Counter((row["segment_id"], row["_date"]) for row in parsed_source).items()
        if count > 1
    ]
    if source_duplicates:
        checks.append(failed("source_segment_date_unique", len(source_duplicates), "0 duplicate segment/date keys", source_duplicates[:10]))
    else:
        checks.append(passed("source_segment_date_unique", len(parsed_source)))

    calendar_duplicates = [
        day.isoformat()
        for day, count in Counter(row["_date"] for row in parsed_calendar).items()
        if count > 1
    ]
    if calendar_duplicates:
        checks.append(failed("calendar_date_unique", len(calendar_duplicates), "0 duplicate calendar dates", calendar_duplicates[:10]))
    else:
        checks.append(passed("calendar_date_unique", len(parsed_calendar)))

    calendar_by_date = {row["_date"]: row for row in parsed_calendar}
    horizon_end = normalized["forecast_origin"].astimezone(normalized["timezone"]).date() + timedelta(days=normalized["horizon_days"] - 1)
    required_calendar = set(daterange(normalized["expected_start"], horizon_end))
    missing_calendar = sorted(required_calendar - set(calendar_by_date))
    if missing_calendar:
        checks.append(
            failed(
                "calendar_covers_history_and_horizon",
                len(missing_calendar),
                "calendar covers complete history and forecast horizon",
                [day.isoformat() for day in missing_calendar[:10]],
            )
        )
    else:
        checks.append(passed("calendar_covers_history_and_horizon", len(required_calendar)))

    missing_complete = find_missing_complete_dates(parsed_source, normalized)
    if missing_complete:
        checks.append(
            failed(
                "complete_history_has_no_missing_dates",
                len(missing_complete),
                "every target segment has every complete date",
                missing_complete,
            )
        )
    else:
        expected_points = len(daterange(normalized["expected_start"], normalized["complete_through"])) * len(normalized["target_segments"])
        checks.append(passed("complete_history_has_no_missing_dates", expected_points))

    source_dates_missing_calendar = sorted({row["_date"] for row in parsed_source} - set(calendar_by_date))
    if source_dates_missing_calendar:
        checks.append(
            failed(
                "source_dates_have_calendar_rows",
                len(source_dates_missing_calendar),
                "every source date joins to calendar",
                [day.isoformat() for day in source_dates_missing_calendar[:10]],
            )
        )
    else:
        checks.append(passed("source_dates_have_calendar_rows", len({row["_date"] for row in parsed_source})))

    origin_date = normalized["forecast_origin"].astimezone(normalized["timezone"]).date()
    late_known_effects = find_effect_rows_known_after_origin(calendar_by_date, normalized, horizon_end, origin_date)
    if late_known_effects:
        checks.append(
            failed(
                "calendar_effects_known_before_origin",
                len(late_known_effects),
                "declared calendar effects are known before forecast origin",
                late_known_effects[:10],
            )
        )
    else:
        checks.append(passed("calendar_effects_known_before_origin", normalized["calendar_effect_columns"]))

    flag_mismatches = find_event_flag_mismatches(parsed_campaigns, parsed_releases, calendar_by_date)
    if flag_mismatches:
        checks.append(
            failed(
                "calendar_flags_cover_declared_events",
                len(flag_mismatches),
                "campaign and release date ranges match calendar flags",
                flag_mismatches[:10],
            )
        )
    else:
        checks.append(passed("calendar_flags_cover_declared_events", len(parsed_campaigns) + len(parsed_releases)))

    blocking = [check for check in checks if not check["valid"] and check["severity"] == "error"]
    if blocking:
        report = build_report(spec, scenario, checks, [], [], [])
        return {"report": report, "trend_rows": [], "seasonality_rows": [], "calendar_effect_rows": []}

    training_rows = [
        row
        for row in parsed_source
        if row["_include_flag"] and normalized["expected_start"] <= row["_date"] <= normalized["complete_through"]
    ]
    partial_rows = [
        row
        for row in parsed_source
        if not row["_include_flag"] or row["_date"] > normalized["complete_through"]
    ]
    if partial_rows:
        checks.append(
            failed(
                "partial_rows_excluded_from_profiles",
                len(partial_rows),
                "partial or incomplete rows are emitted upstream but excluded from trend and seasonality profiles",
                [{"segment_id": row["segment_id"], "observed_date": row["_date"].isoformat()} for row in partial_rows[:10]],
                severity="warning",
            )
        )
    else:
        checks.append(passed("partial_rows_excluded_from_profiles", 0))

    trend_rows = build_trend_rows(training_rows, normalized)
    seasonality_rows = build_seasonality_rows(training_rows, calendar_by_date, normalized)
    calendar_effect_rows = build_calendar_effect_rows(
        training_rows,
        calendar_by_date,
        parsed_campaigns,
        parsed_releases,
        normalized,
        origin_date,
        horizon_end,
    )

    future_no_history = [
        row
        for row in calendar_effect_rows
        if row["status"] == "known_future_effect_without_training_examples"
    ]
    if future_no_history:
        checks.append(
            failed(
                "future_calendar_effect_has_no_training_examples",
                len(future_no_history),
                "known future calendar effects without historical examples are reviewed explicitly",
                future_no_history[:10],
                severity="warning",
            )
        )
    else:
        checks.append(passed("future_calendar_effect_has_no_training_examples", 0))

    month_count = len({row["_date"].strftime("%Y-%m") for row in training_rows})
    if month_count < normalized["minimum_month_cycles"]:
        checks.append(
            failed(
                "monthly_profile_has_single_cycle",
                month_count,
                f">= {normalized['minimum_month_cycles']} calendar months",
                severity="warning",
            )
        )
    else:
        checks.append(passed("monthly_profile_has_single_cycle", month_count))

    report = build_report(spec, scenario, checks, trend_rows, seasonality_rows, calendar_effect_rows)
    return {
        "report": report,
        "trend_rows": trend_rows,
        "seasonality_rows": seasonality_rows,
        "calendar_effect_rows": calendar_effect_rows,
    }


def parse_source_rows(rows: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    target_segments = set(spec["target_segments"])
    for index, row in enumerate(rows, start=2):
        if row.get("metric_id") != spec["target_metric"] or row.get("segment_id") not in target_segments:
            continue
        try:
            parsed.append(
                {
                    **row,
                    "_row": index,
                    "_date": parse_date(row.get(spec["time_column"], ""), spec["time_column"]),
                    "_value": parse_number(row.get(spec["value_column"], ""), spec["value_column"]),
                    "_delta": parse_number(row.get(spec["delta_column"], ""), spec["delta_column"]),
                    "_include_flag": parse_bool(row.get(spec["complete_flag_column"], ""), spec["complete_flag_column"]),
                    "_is_complete_period": parse_bool(row.get("is_complete_period", ""), "is_complete_period"),
                }
            )
        except SeasonalityProfileError as error:
            errors.append({"row": index, "segment_id": row.get("segment_id"), "error": str(error)})
    if errors:
        return parsed, [failed("source_rows_parse", len(errors), "valid source dates, booleans, and numeric values", errors[:10])]
    return parsed, [passed("source_rows_parse", len(parsed))]


def parse_calendar_rows(rows: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    bool_fields = {"is_weekend", "is_holiday", "campaign_active", "release_active"}
    for index, row in enumerate(rows, start=2):
        try:
            parsed_row = {
                **row,
                "_row": index,
                "_date": parse_date(row.get(spec["calendar_date_column"], ""), spec["calendar_date_column"]),
                "_known_before_date": parse_date(row.get("known_before_date", ""), "known_before_date"),
            }
            for field in bool_fields:
                parsed_row[f"_{field}"] = parse_bool(row.get(field, ""), field)
            parsed.append(parsed_row)
        except SeasonalityProfileError as error:
            errors.append({"row": index, "date": row.get("date"), "error": str(error)})
    if errors:
        return parsed, [failed("calendar_rows_parse", len(errors), "valid calendar dates and booleans", errors[:10])]
    return parsed, [passed("calendar_rows_parse", len(parsed))]


def parse_event_rows(rows: list[dict[str, str]], event_type: str, spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    id_field = "campaign_id" if event_type == "campaign" else "release_id"
    for index, row in enumerate(rows, start=2):
        try:
            start_date = parse_date(row.get("start_date", ""), "start_date")
            end_date = parse_date(row.get("end_date", ""), "end_date")
            if end_date < start_date:
                raise SeasonalityProfileError(f"end_date must be >= start_date for {row.get(id_field)}")
            parsed.append(
                {
                    **row,
                    "_row": index,
                    "_event_type": event_type,
                    "_event_id": row.get(id_field, ""),
                    "_start_date": start_date,
                    "_end_date": end_date,
                    "_known_before_date": parse_date(row.get("known_before_date", ""), "known_before_date"),
                }
            )
        except SeasonalityProfileError as error:
            errors.append({"row": index, "event_type": event_type, "error": str(error)})
    check_id = f"{event_type}_rows_parse"
    if errors:
        return parsed, [failed(check_id, len(errors), "valid event date ranges", errors[:10])]
    return parsed, [passed(check_id, len(parsed))]


def find_missing_complete_dates(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    by_segment: dict[str, set[date]] = defaultdict(set)
    for row in rows:
        if spec["expected_start"] <= row["_date"] <= spec["complete_through"] and row["_include_flag"]:
            by_segment[row["segment_id"]].add(row["_date"])
    expected = set(daterange(spec["expected_start"], spec["complete_through"]))
    missing: list[dict[str, Any]] = []
    for segment_id in spec["target_segments"]:
        segment_missing = sorted(expected - by_segment.get(segment_id, set()))
        if segment_missing:
            missing.append({"segment_id": segment_id, "missing_dates": [day.isoformat() for day in segment_missing]})
    return missing


def find_effect_rows_known_after_origin(
    calendar_by_date: dict[date, dict[str, Any]],
    spec: dict[str, Any],
    horizon_end: date,
    origin_date: date,
) -> list[dict[str, Any]]:
    late_rows: list[dict[str, Any]] = []
    for day, row in sorted(calendar_by_date.items()):
        if day < spec["expected_start"] or day > horizon_end:
            continue
        for column in spec["calendar_effect_columns"]:
            if row.get(f"_{column}") is True and row["_known_before_date"] > origin_date:
                late_rows.append(
                    {
                        "date": day.isoformat(),
                        "effect_column": column,
                        "known_before_date": row["_known_before_date"].isoformat(),
                        "forecast_origin_date": origin_date.isoformat(),
                    }
                )
    return late_rows


def find_event_flag_mismatches(
    campaigns: list[dict[str, Any]],
    releases: list[dict[str, Any]],
    calendar_by_date: dict[date, dict[str, Any]],
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for campaign in campaigns:
        for day in daterange(campaign["_start_date"], campaign["_end_date"]):
            row = calendar_by_date.get(day)
            if row is None or row.get("_campaign_active") is not True:
                mismatches.append({"event_type": "campaign", "event_id": campaign["_event_id"], "date": day.isoformat()})
    for release in releases:
        for day in daterange(release["_start_date"], release["_end_date"]):
            row = calendar_by_date.get(day)
            if row is None or row.get("_release_active") is not True:
                mismatches.append({"event_type": "release", "event_id": release["_event_id"], "date": day.isoformat()})
    return mismatches


def linear_slope(rows: list[dict[str, Any]]) -> float | None:
    if len(rows) < 2:
        return None
    first_date = rows[0]["_date"]
    x_values = [(row["_date"] - first_date).days for row in rows]
    y_values = [row["_value"] for row in rows]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(y_values) / len(y_values)
    denominator = sum((x_value - x_mean) ** 2 for x_value in x_values)
    if denominator == 0:
        return None
    numerator = sum((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x_values, y_values))
    return numerator / denominator


def build_trend_rows(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    trend_rows: list[dict[str, Any]] = []
    for segment_id in spec["target_segments"]:
        segment_rows = sorted([row for row in rows if row["segment_id"] == segment_id], key=lambda row: row["_date"])
        first = segment_rows[0]
        last = segment_rows[-1]
        elapsed_days = (last["_date"] - first["_date"]).days
        first_last_slope = (last["_value"] - first["_value"]) / elapsed_days if elapsed_days else None
        slope = linear_slope(segment_rows)
        trend_rows.append(
            {
                "profile_id": spec["profile_id"],
                "segment_id": segment_id,
                "observations": len(segment_rows),
                "first_observed_date": first["_date"].isoformat(),
                "last_observed_date": last["_date"].isoformat(),
                "first_value": format_value(first["_value"]),
                "last_value": format_value(last["_value"]),
                "absolute_change": format_value(last["_value"] - first["_value"]),
                "first_last_change_per_day": format_value(first_last_slope),
                "linear_slope_per_day": format_value(slope),
                "trend_direction": "up" if (slope or 0) > 0 else "down" if (slope or 0) < 0 else "flat",
            }
        )
    return trend_rows


def build_seasonality_rows(
    rows: list[dict[str, Any]],
    calendar_by_date: dict[date, dict[str, Any]],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    profile_rows: list[dict[str, Any]] = []
    for segment_id in spec["target_segments"]:
        segment_rows = [row for row in rows if row["segment_id"] == segment_id]
        segment_mean = mean([row["_value"] for row in segment_rows])
        by_weekday: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in segment_rows:
            calendar_row = calendar_by_date[row["_date"]]
            by_weekday[calendar_row["day_of_week"]].append(row)
            by_month[row["_date"].strftime("%Y-%m")].append(row)

        for weekday in sorted(by_weekday, key=lambda item: WEEKDAY_ORDER[item]):
            group = sorted(by_weekday[weekday], key=lambda row: row["_date"])
            append_profile_row(
                profile_rows,
                spec,
                segment_id,
                "day_of_week",
                weekday,
                WEEKDAY_ORDER[weekday],
                group,
                segment_mean,
                len(group) >= spec["minimum_observations_per_weekday"],
            )

        enough_months = len(by_month) >= spec["minimum_month_cycles"]
        for month_key in sorted(by_month):
            group = sorted(by_month[month_key], key=lambda row: row["_date"])
            append_profile_row(
                profile_rows,
                spec,
                segment_id,
                "month",
                month_key,
                int(month_key[-2:]),
                group,
                segment_mean,
                enough_months,
            )
    return profile_rows


def append_profile_row(
    output: list[dict[str, Any]],
    spec: dict[str, Any],
    segment_id: str,
    seasonality_type: str,
    seasonal_key: str,
    seasonal_order: int,
    rows: list[dict[str, Any]],
    segment_mean: float | None,
    enough_history: bool,
) -> None:
    mean_value = mean([row["_value"] for row in rows])
    mean_delta = mean([row["_delta"] for row in rows])
    output.append(
        {
            "profile_id": spec["profile_id"],
            "segment_id": segment_id,
            "seasonality_type": seasonality_type,
            "seasonal_key": seasonal_key,
            "seasonal_order": seasonal_order,
            "observations": len(rows),
            "mean_value": format_value(mean_value),
            "mean_delta": format_value(mean_delta),
            "segment_mean_value": format_value(segment_mean),
            "seasonal_index": format_value(None if mean_value is None or segment_mean is None else mean_value - segment_mean),
            "relative_index": format_value(None if mean_value is None or not segment_mean else mean_value / segment_mean),
            "first_observed_date": rows[0]["_date"].isoformat(),
            "last_observed_date": rows[-1]["_date"].isoformat(),
            "enough_history": str(enough_history).lower(),
        }
    )


def build_calendar_effect_rows(
    training_rows: list[dict[str, Any]],
    calendar_by_date: dict[date, dict[str, Any]],
    campaigns: list[dict[str, Any]],
    releases: list[dict[str, Any]],
    spec: dict[str, Any],
    origin_date: date,
    horizon_end: date,
) -> list[dict[str, Any]]:
    rows_by_segment_date = {(row["segment_id"], row["_date"]): row for row in training_rows}
    definitions = build_effect_definitions(calendar_by_date, campaigns, releases, spec, origin_date, horizon_end)
    inventory_rows: list[dict[str, Any]] = []
    for definition in definitions:
        for segment_id in definition["segments"]:
            effect_dates = daterange(definition["start_date"], definition["end_date"])
            observed_dates = [day for day in effect_dates if (segment_id, day) in rows_by_segment_date]
            future_dates = [day for day in effect_dates if origin_date <= day <= horizon_end]
            observed_values = [rows_by_segment_date[(segment_id, day)]["_value"] for day in observed_dates]
            observed_mean = mean(observed_values)
            baseline_values = [
                seasonal_baseline_for_date(day, segment_id, training_rows, calendar_by_date, set(effect_dates))
                for day in observed_dates
            ]
            baseline_values = [value for value in baseline_values if value is not None]
            baseline_mean = mean(baseline_values)
            known_before_origin = definition["known_before_date"] <= origin_date
            if not known_before_origin:
                status = "not_known_before_origin"
            elif observed_dates:
                status = "observed_calendar_effect"
            elif future_dates:
                status = "known_future_effect_without_training_examples"
            else:
                status = "not_in_training_or_forecast_horizon"
            inventory_rows.append(
                {
                    "profile_id": spec["profile_id"],
                    "effect_type": definition["effect_type"],
                    "effect_id": definition["effect_id"],
                    "segment_id": segment_id,
                    "start_date": definition["start_date"].isoformat(),
                    "end_date": definition["end_date"].isoformat(),
                    "known_before_date": definition["known_before_date"].isoformat(),
                    "known_before_origin": str(known_before_origin).lower(),
                    "observed_training_days": len(observed_dates),
                    "future_horizon_days": len(future_dates),
                    "baseline_mean": format_value(baseline_mean),
                    "observed_mean": format_value(observed_mean),
                    "effect_lift_vs_seasonal_profile": format_value(
                        None if observed_mean is None or baseline_mean is None else observed_mean - baseline_mean
                    ),
                    "status": status,
                }
            )
    return sorted(inventory_rows, key=lambda row: (row["effect_type"], row["effect_id"], row["segment_id"]))


def build_effect_definitions(
    calendar_by_date: dict[date, dict[str, Any]],
    campaigns: list[dict[str, Any]],
    releases: list[dict[str, Any]],
    spec: dict[str, Any],
    origin_date: date,
    horizon_end: date,
) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    holiday_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for day, row in calendar_by_date.items():
        if spec["expected_start"] <= day <= horizon_end and row.get("_is_holiday") is True:
            holiday_groups[row.get("holiday_name") or "unnamed_holiday"].append(row)
    for holiday_name, rows in holiday_groups.items():
        days = sorted(row["_date"] for row in rows)
        definitions.append(
            {
                "effect_type": "holiday",
                "effect_id": holiday_name,
                "segments": spec["target_segments"],
                "start_date": days[0],
                "end_date": days[-1],
                "known_before_date": max(row["_known_before_date"] for row in rows),
            }
        )

    for campaign in campaigns:
        if campaign["_end_date"] < spec["expected_start"] or campaign["_start_date"] > horizon_end:
            continue
        target_segment = campaign.get("target_segment", "")
        segments = [target_segment] if target_segment in spec["target_segments"] else spec["target_segments"]
        definitions.append(
            {
                "effect_type": "campaign",
                "effect_id": campaign["_event_id"],
                "segments": segments,
                "start_date": campaign["_start_date"],
                "end_date": campaign["_end_date"],
                "known_before_date": campaign["_known_before_date"],
            }
        )

    for release in releases:
        if release["_end_date"] < spec["expected_start"] or release["_start_date"] > horizon_end:
            continue
        platform = release.get("platform", "")
        segments = [platform] if platform in spec["target_segments"] else []
        if not segments and "all" in spec["target_segments"]:
            segments = ["all"]
        definitions.append(
            {
                "effect_type": "release",
                "effect_id": release["_event_id"],
                "segments": segments,
                "start_date": release["_start_date"],
                "end_date": release["_end_date"],
                "known_before_date": release["_known_before_date"],
            }
        )
    return definitions


def seasonal_baseline_for_date(
    day: date,
    segment_id: str,
    training_rows: list[dict[str, Any]],
    calendar_by_date: dict[date, dict[str, Any]],
    excluded_dates: set[date],
) -> float | None:
    weekday = calendar_by_date[day]["day_of_week"]
    same_weekday_values = [
        row["_value"]
        for row in training_rows
        if row["segment_id"] == segment_id
        and row["_date"] not in excluded_dates
        and calendar_by_date[row["_date"]]["day_of_week"] == weekday
    ]
    if same_weekday_values:
        return mean(same_weekday_values)
    segment_values = [
        row["_value"]
        for row in training_rows
        if row["segment_id"] == segment_id and row["_date"] not in excluded_dates
    ]
    return mean(segment_values)


def build_report(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    checks: list[dict[str, Any]],
    trend_rows: list[dict[str, Any]],
    seasonality_rows: list[dict[str, Any]],
    calendar_effect_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    error_failures = [check for check in checks if not check["valid"] and check["severity"] == "error"]
    warning_failures = [check for check in checks if not check["valid"] and check["severity"] == "warning"]
    return {
        "audit_id": "seasonality-profile-audit",
        "profile_id": spec.get("profile_id"),
        "forecast_id": scenario.get("forecast_id"),
        "valid": not error_failures,
        "warning_count": len(warning_failures),
        "error_count": len(error_failures),
        "checks": checks,
        "outputs": {
            "trend_rows": len(trend_rows),
            "seasonality_rows": len(seasonality_rows),
            "calendar_effect_rows": len(calendar_effect_rows),
            "known_future_effect_rows": sum(
                1 for row in calendar_effect_rows if row.get("status") == "known_future_effect_without_training_examples"
            ),
        },
        "series": [
            {
                "segment_id": row["segment_id"],
                "observations": row["observations"],
                "first_observed_date": row["first_observed_date"],
                "last_observed_date": row["last_observed_date"],
                "trend_direction": row["trend_direction"],
                "linear_slope_per_day": row["linear_slope_per_day"],
            }
            for row in trend_rows
        ],
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(error_failures) + len(warning_failures),
            "blocking_errors": [check["id"] for check in error_failures],
            "warnings": [check["id"] for check in warning_failures],
        },
    }


def write_package(output_dir: Path, package: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "trend_summary.csv",
        package["trend_rows"],
        [
            "profile_id",
            "segment_id",
            "observations",
            "first_observed_date",
            "last_observed_date",
            "first_value",
            "last_value",
            "absolute_change",
            "first_last_change_per_day",
            "linear_slope_per_day",
            "trend_direction",
        ],
    )
    write_csv(
        output_dir / "seasonality_profile.csv",
        package["seasonality_rows"],
        [
            "profile_id",
            "segment_id",
            "seasonality_type",
            "seasonal_key",
            "seasonal_order",
            "observations",
            "mean_value",
            "mean_delta",
            "segment_mean_value",
            "seasonal_index",
            "relative_index",
            "first_observed_date",
            "last_observed_date",
            "enough_history",
        ],
    )
    write_csv(
        output_dir / "calendar_effect_inventory.csv",
        package["calendar_effect_rows"],
        [
            "profile_id",
            "effect_type",
            "effect_id",
            "segment_id",
            "start_date",
            "end_date",
            "known_before_date",
            "known_before_origin",
            "observed_training_days",
            "future_horizon_days",
            "baseline_mean",
            "observed_mean",
            "effect_lift_vs_seasonal_profile",
            "status",
        ],
    )
    (output_dir / "seasonality_report.json").write_text(
        json.dumps(package["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Profile trend, seasonality, and known calendar effects.")
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--campaign-calendar", type=Path, required=True)
    parser.add_argument("--release-calendar", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    package = build_seasonality_profile_package(
        series_path=args.series,
        calendar_path=args.calendar,
        campaign_path=args.campaign_calendar,
        release_path=args.release_calendar,
        scenario_path=args.scenario,
        spec_path=args.spec,
    )
    write_package(args.output_dir, package)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "trend_rows": report["outputs"]["trend_rows"],
                "seasonality_rows": report["outputs"]["seasonality_rows"],
                "calendar_effect_rows": report["outputs"]["calendar_effect_rows"],
            },
            ensure_ascii=False,
        )
    )
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
