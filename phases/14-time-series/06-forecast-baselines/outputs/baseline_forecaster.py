from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REQUIRED_SERIES_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "frequency",
    "value",
    "include_in_training",
}
REQUIRED_CALENDAR_COLUMNS = {"date", "day_of_week", "campaign_active", "known_before_date"}
REQUIRED_SCENARIO_FIELDS = {
    "forecast_id",
    "target_metric",
    "target_segments",
    "timezone",
    "frequency",
    "complete_through",
    "forecast_origin",
    "horizon_days",
}
REQUIRED_CUTOFF_FIELDS = {
    "leakage_audit_id",
    "forecast_id",
    "target_metric",
    "target_segments",
    "timezone",
    "frequency",
    "forecast_origin",
    "training_start",
    "training_end",
    "first_forecast_date",
    "horizon_end",
    "horizon_days",
    "embargo_dates",
    "split_type",
}
REQUIRED_SPEC_FIELDS = {
    "baseline_id",
    "forecast_id",
    "source_table",
    "cutoff_contract_id",
    "target_metric",
    "target_segments",
    "time_column",
    "value_column",
    "training_start",
    "training_end",
    "first_forecast_date",
    "horizon_end",
    "horizon_days",
    "timezone",
    "frequency",
    "seasonal_period_days",
    "embargo_dates",
    "primary_baseline_model",
    "baseline_policy",
    "models",
}
REQUIRED_MODEL_FIELDS = {"model_id", "kind", "minimum_training_points", "anchor_policy"}
REQUIRED_MODEL_KINDS = {"naive", "seasonal_naive", "drift", "moving_average"}
REQUIRED_MODEL_IDS = {"naive", "seasonal_naive_7", "drift", "moving_average_7"}


class BaselineForecastError(ValueError):
    """Raised when baseline forecast inputs cannot be interpreted."""


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
        raise BaselineForecastError(f"{path.name} must contain a JSON object")
    return value


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise BaselineForecastError(f"{field} must be ISO date: {value}") from error


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BaselineForecastError(f"{field} must be ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BaselineForecastError(f"{field} must be timezone-aware: {value}")
    return parsed


def parse_bool(value: str | bool, field: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise BaselineForecastError(f"{field} must be true or false: {value}")
    return normalized == "true"


def parse_number(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise BaselineForecastError(f"{field} must be numeric: {value}") from error


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def format_number(value: float) -> str:
    rounded = round(value, 6)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.6f}".rstrip("0").rstrip(".")


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


def has_blocking_errors(checks: list[dict[str, Any]]) -> bool:
    return any(not check["valid"] and check["severity"] == "error" for check in checks)


def normalize_inputs(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    cutoff_contract: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    missing_scenario = sorted(REQUIRED_SCENARIO_FIELDS - set(scenario))
    missing_cutoff = sorted(REQUIRED_CUTOFF_FIELDS - set(cutoff_contract))
    if missing_spec:
        checks.append(failed("baseline_spec_required_fields", missing_spec, "all required baseline fields"))
        return checks, None
    checks.append(passed("baseline_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))
    if missing_scenario:
        checks.append(failed("scenario_required_fields", missing_scenario, "all required scenario fields"))
        return checks, None
    checks.append(passed("scenario_required_fields", len(REQUIRED_SCENARIO_FIELDS)))
    if missing_cutoff:
        checks.append(failed("cutoff_contract_required_fields", missing_cutoff, "all required cutoff fields"))
        return checks, None
    checks.append(passed("cutoff_contract_required_fields", len(REQUIRED_CUTOFF_FIELDS)))

    try:
        timezone = ZoneInfo(str(spec["timezone"]))
        forecast_origin = parse_timestamp(str(scenario["forecast_origin"]), "forecast_origin")
    except (ZoneInfoNotFoundError, BaselineForecastError) as error:
        checks.append(failed("timezone_and_origin_valid", str(error), "valid timezone and forecast origin"))
        return checks, None
    checks.append(passed("timezone_and_origin_valid", spec["timezone"]))

    segments = spec.get("target_segments")
    if not isinstance(segments, list) or not segments or not all(isinstance(item, str) and item for item in segments):
        checks.append(failed("target_segments_declared", segments, "non-empty segment list"))
        return checks, None
    checks.append(passed("target_segments_declared", segments))

    models = spec.get("models")
    if not isinstance(models, list) or not models:
        checks.append(failed("baseline_models_declared", models, "non-empty baseline model list"))
        return checks, None

    model_errors: list[dict[str, Any]] = []
    model_ids: list[str] = []
    model_kinds: set[str] = set()
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            model_errors.append({"model_index": index, "error": "model must be an object"})
            continue
        missing_model_fields = sorted(REQUIRED_MODEL_FIELDS - set(model))
        if missing_model_fields:
            model_errors.append({"model_index": index, "missing": missing_model_fields})
        model_id = str(model.get("model_id", ""))
        model_kind = str(model.get("kind", ""))
        model_ids.append(model_id)
        model_kinds.add(model_kind)
        if model_kind not in REQUIRED_MODEL_KINDS:
            model_errors.append({"model_id": model_id, "kind": model_kind, "error": "unsupported model kind"})
        try:
            minimum = int(model.get("minimum_training_points", 0))
            if minimum <= 0:
                model_errors.append({"model_id": model_id, "error": "minimum_training_points must be positive"})
        except (TypeError, ValueError):
            model_errors.append({"model_id": model_id, "error": "minimum_training_points must be an integer"})

    duplicate_model_ids = [model_id for model_id, count in Counter(model_ids).items() if model_id and count > 1]
    for model_id in duplicate_model_ids:
        model_errors.append({"model_id": model_id, "error": "duplicate model id"})

    missing_required_model_ids = sorted(REQUIRED_MODEL_IDS - set(model_ids))
    if missing_required_model_ids:
        model_errors.append({"missing_required_model_ids": missing_required_model_ids})

    if model_errors:
        checks.append(failed("baseline_models_declared", len(model_errors), "valid naive, seasonal, drift, and moving-average models", model_errors))
    else:
        checks.append(passed("baseline_models_declared", model_ids))

    try:
        normalized = {
            "baseline_id": str(spec["baseline_id"]),
            "forecast_id": str(spec["forecast_id"]),
            "source_table": str(spec["source_table"]),
            "cutoff_contract_id": str(spec["cutoff_contract_id"]),
            "target_metric": str(spec["target_metric"]),
            "target_segments": [str(segment) for segment in segments],
            "time_column": str(spec["time_column"]),
            "value_column": str(spec["value_column"]),
            "training_start": parse_date(str(spec["training_start"]), "training_start"),
            "training_end": parse_date(str(spec["training_end"]), "training_end"),
            "first_forecast_date": parse_date(str(spec["first_forecast_date"]), "first_forecast_date"),
            "horizon_end": parse_date(str(spec["horizon_end"]), "horizon_end"),
            "horizon_days": int(spec["horizon_days"]),
            "timezone": timezone,
            "timezone_name": str(spec["timezone"]),
            "frequency": str(spec["frequency"]),
            "seasonal_period_days": int(spec["seasonal_period_days"]),
            "embargo_dates": [parse_date(str(day), "embargo_dates") for day in spec["embargo_dates"]],
            "primary_baseline_model": str(spec["primary_baseline_model"]),
            "baseline_policy": spec["baseline_policy"],
            "models": models,
            "forecast_origin": forecast_origin,
            "scenario": scenario,
            "cutoff_contract": cutoff_contract,
        }
    except (TypeError, ValueError, BaselineForecastError) as error:
        checks.append(failed("baseline_spec_values_parse", str(error), "parseable dates and numeric settings"))
        return checks, None
    checks.append(passed("baseline_spec_values_parse", normalized["baseline_id"]))

    alignment_errors: list[dict[str, Any]] = []
    for field in ("forecast_id", "target_metric", "target_segments", "timezone", "frequency", "horizon_days"):
        if spec[field] != scenario[field]:
            alignment_errors.append({"field": field, "baseline_spec": spec[field], "scenario": scenario[field]})
    if scenario["complete_through"] != spec["training_end"]:
        alignment_errors.append({"field": "complete_through/training_end", "baseline_spec": spec["training_end"], "scenario": scenario["complete_through"]})
    for field in (
        "forecast_id",
        "target_metric",
        "target_segments",
        "timezone",
        "frequency",
        "training_start",
        "training_end",
        "first_forecast_date",
        "horizon_end",
        "horizon_days",
        "embargo_dates",
    ):
        if spec[field] != cutoff_contract[field]:
            alignment_errors.append({"field": field, "baseline_spec": spec[field], "cutoff_contract": cutoff_contract[field]})
    if spec["cutoff_contract_id"] != cutoff_contract["leakage_audit_id"]:
        alignment_errors.append(
            {
                "field": "cutoff_contract_id",
                "baseline_spec": spec["cutoff_contract_id"],
                "cutoff_contract": cutoff_contract["leakage_audit_id"],
            }
        )
    if alignment_errors:
        checks.append(failed("scenario_cutoff_and_baseline_spec_align", len(alignment_errors), "matching scenario, cutoff, and baseline setup", alignment_errors))
    else:
        checks.append(passed("scenario_cutoff_and_baseline_spec_align", "scenario and cutoff aligned"))

    if cutoff_contract["split_type"] != "time_ordered_cutoff":
        checks.append(failed("cutoff_contract_is_time_ordered", cutoff_contract["split_type"], "time_ordered_cutoff"))
    else:
        checks.append(passed("cutoff_contract_is_time_ordered", cutoff_contract["split_type"]))

    expected_horizon_end = normalized["first_forecast_date"] + timedelta(days=normalized["horizon_days"] - 1)
    if normalized["horizon_end"] != expected_horizon_end:
        checks.append(failed("forecast_horizon_matches_contract", normalized["horizon_end"].isoformat(), expected_horizon_end.isoformat()))
    else:
        checks.append(passed("forecast_horizon_matches_contract", normalized["horizon_days"]))

    if normalized["seasonal_period_days"] != 7:
        checks.append(failed("seasonal_period_is_precommitted", normalized["seasonal_period_days"], 7))
    else:
        seasonal_model_errors = [
            model
            for model in models
            if model.get("kind") == "seasonal_naive" and int(model.get("seasonal_period_days", 0)) != normalized["seasonal_period_days"]
        ]
        if seasonal_model_errors:
            checks.append(failed("seasonal_period_is_precommitted", len(seasonal_model_errors), "seasonal model period matches spec", seasonal_model_errors))
        else:
            checks.append(passed("seasonal_period_is_precommitted", normalized["seasonal_period_days"]))

    primary_model = normalized["primary_baseline_model"]
    if primary_model not in set(model_ids):
        checks.append(failed("primary_baseline_declared", primary_model, "primary baseline model appears in models"))
    elif primary_model != "seasonal_naive_7":
        checks.append(failed("primary_baseline_declared", primary_model, "seasonal_naive_7"))
    else:
        checks.append(passed("primary_baseline_declared", primary_model))

    return checks, normalized


def build_baseline_forecast_package(
    *,
    series_path: Path,
    calendar_path: Path,
    scenario_path: Path,
    cutoff_contract_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    series_rows, series_columns = read_csv(series_path)
    calendar_rows, calendar_columns = read_csv(calendar_path)
    scenario = read_json(scenario_path)
    cutoff_contract = read_json(cutoff_contract_path)
    spec = read_json(spec_path)

    spec_checks, normalized = normalize_inputs(spec, scenario, cutoff_contract)
    checks = list(spec_checks)
    missing_series_columns = sorted(REQUIRED_SERIES_COLUMNS - set(series_columns))
    missing_calendar_columns = sorted(REQUIRED_CALENDAR_COLUMNS - set(calendar_columns))
    checks.append(
        failed("series_columns_present", missing_series_columns, "all required series columns")
        if missing_series_columns
        else passed("series_columns_present", len(series_columns))
    )
    checks.append(
        failed("calendar_columns_present", missing_calendar_columns, "all required calendar columns")
        if missing_calendar_columns
        else passed("calendar_columns_present", len(calendar_columns))
    )
    if normalized is None or missing_series_columns or missing_calendar_columns:
        return empty_package(spec, scenario, checks)

    parsed_series, series_checks = parse_series_rows(series_rows, normalized)
    parsed_calendar, calendar_checks = parse_calendar_rows(calendar_rows)
    checks.extend(series_checks)
    checks.extend(calendar_checks)
    checks.extend(audit_source_series(parsed_series, normalized))
    checks.extend(audit_calendar(parsed_calendar, normalized))

    if has_blocking_errors(checks):
        return empty_package(spec, scenario, checks)

    forecasts, trace_rows, forecast_checks = build_forecasts(parsed_series, normalized)
    checks.extend(forecast_checks)
    if not has_blocking_errors(checks):
        checks.extend(audit_forecast_outputs(forecasts, trace_rows, normalized))

    report = build_report(spec, scenario, checks, forecasts, trace_rows)
    return {"report": report, "forecast_rows": forecasts, "trace_rows": trace_rows}


def empty_package(spec: dict[str, Any], scenario: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    report = build_report(spec, scenario, checks, [], [])
    return {"report": report, "forecast_rows": [], "trace_rows": []}


def parse_series_rows(rows: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
                    "_date": parse_date(row.get("observed_date", ""), "observed_date"),
                    "_value": parse_number(row.get("value", ""), "value"),
                    "_include_in_training": parse_bool(row.get("include_in_training", ""), "include_in_training"),
                }
            )
        except BaselineForecastError as error:
            errors.append({"row": index, "error": str(error)})
    if errors:
        return parsed, [failed("series_rows_parse", len(errors), "valid date, value, and training flag", errors[:10])]
    return parsed, [passed("series_rows_parse", len(parsed))]


def parse_calendar_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        try:
            parsed.append(
                {
                    **row,
                    "_row": index,
                    "_date": parse_date(row.get("date", ""), "date"),
                    "_known_before_date": parse_date(row.get("known_before_date", ""), "known_before_date"),
                    "_campaign_active": parse_bool(row.get("campaign_active", ""), "campaign_active"),
                }
            )
        except BaselineForecastError as error:
            errors.append({"row": index, "error": str(error)})
    if errors:
        return parsed, [failed("calendar_rows_parse", len(errors), "valid calendar rows", errors[:10])]
    return parsed, [passed("calendar_rows_parse", len(parsed))]


def audit_source_series(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    key_counts = Counter((row["segment_id"], row["_date"]) for row in rows)
    duplicates = [
        {"segment_id": segment_id, "observed_date": observed_date.isoformat(), "count": count}
        for (segment_id, observed_date), count in key_counts.items()
        if count > 1
    ]
    if duplicates:
        checks.append(failed("source_segment_date_unique", len(duplicates), "one source row per segment and date", duplicates[:10]))
    else:
        checks.append(passed("source_segment_date_unique", len(key_counts)))

    rows_by_segment_date = {(row["segment_id"], row["_date"]): row for row in rows}
    missing_training_dates: list[dict[str, str]] = []
    bad_training_flags: list[dict[str, str]] = []
    for segment_id in spec["target_segments"]:
        for day in daterange(spec["training_start"], spec["training_end"]):
            row = rows_by_segment_date.get((segment_id, day))
            if row is None:
                missing_training_dates.append({"segment_id": segment_id, "observed_date": day.isoformat()})
            elif not row["_include_in_training"]:
                bad_training_flags.append({"segment_id": segment_id, "observed_date": day.isoformat()})
    if missing_training_dates or bad_training_flags:
        checks.append(
            failed(
                "training_rows_match_cutoff",
                len(missing_training_dates) + len(bad_training_flags),
                "all training dates exist and are included in training",
                [*missing_training_dates[:5], *bad_training_flags[:5]],
            )
        )
    else:
        checks.append(passed("training_rows_match_cutoff", spec["training_end"].isoformat()))

    training_after_cutoff = [
        {"segment_id": row["segment_id"], "observed_date": row["_date"].isoformat()}
        for row in rows
        if row["_include_in_training"] and row["_date"] > spec["training_end"]
    ]
    if training_after_cutoff:
        checks.append(failed("no_training_rows_after_cutoff", len(training_after_cutoff), "0 training rows after training_end", training_after_cutoff[:10]))
    else:
        checks.append(passed("no_training_rows_after_cutoff", spec["training_end"].isoformat()))

    embargo_training_rows = [
        {"segment_id": row["segment_id"], "observed_date": row["_date"].isoformat()}
        for row in rows
        if row["_include_in_training"] and row["_date"] in set(spec["embargo_dates"])
    ]
    if embargo_training_rows:
        checks.append(failed("embargo_dates_are_not_training_rows", len(embargo_training_rows), "embargo dates excluded from training", embargo_training_rows[:10]))
    else:
        checks.append(passed("embargo_dates_are_not_training_rows", [day.isoformat() for day in spec["embargo_dates"]]))
    return checks


def audit_calendar(rows: list[dict[str, Any]], spec: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    calendar_dates = {row["_date"] for row in rows}
    required_dates = daterange(spec["first_forecast_date"], spec["horizon_end"])
    missing_dates = [day.isoformat() for day in required_dates if day not in calendar_dates]
    if missing_dates:
        checks.append(failed("calendar_covers_forecast_horizon", len(missing_dates), "calendar rows for every forecast date", missing_dates[:10]))
    else:
        checks.append(passed("calendar_covers_forecast_horizon", len(required_dates)))

    campaign_days = [
        {"date": row["_date"].isoformat(), "day_of_week": row.get("day_of_week", "")}
        for row in rows
        if spec["first_forecast_date"] <= row["_date"] <= spec["horizon_end"] and row["_campaign_active"]
    ]
    if campaign_days and spec["baseline_policy"].get("simple_baselines_do_not_apply_calendar_uplift") is True:
        checks.append(
            failed(
                "known_future_calendar_effects_not_modeled",
                len(campaign_days),
                "simple baseline forecast intentionally ignores calendar uplift",
                campaign_days[:10],
                severity="warning",
            )
        )
    else:
        checks.append(passed("known_future_calendar_effects_not_modeled", 0))

    if spec["first_forecast_date"] > spec["training_end"] + timedelta(days=1):
        checks.append(
            failed(
                "embargo_gap_skipped_before_forecast",
                (spec["first_forecast_date"] - spec["training_end"]).days - 1,
                "forecast starts after explicit embargo gap",
                [day.isoformat() for day in spec["embargo_dates"]],
                severity="warning",
            )
        )
    else:
        checks.append(passed("embargo_gap_skipped_before_forecast", 0))
    return checks


def build_forecasts(
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    forecast_rows: list[dict[str, str]] = []
    trace_rows: list[dict[str, str]] = []
    forecast_dates = daterange(spec["first_forecast_date"], spec["horizon_end"])
    training_by_segment: dict[str, list[dict[str, Any]]] = {}
    for segment_id in spec["target_segments"]:
        training_rows = [
            row
            for row in rows
            if row["segment_id"] == segment_id
            and row["_include_in_training"]
            and spec["training_start"] <= row["_date"] <= spec["training_end"]
        ]
        training_by_segment[segment_id] = sorted(training_rows, key=lambda item: item["_date"])

    enough_history_failures: list[dict[str, Any]] = []
    seasonal_anchor_failures: list[dict[str, Any]] = []
    for segment_id, training_rows in training_by_segment.items():
        for model in spec["models"]:
            model_id = str(model["model_id"])
            minimum = int(model["minimum_training_points"])
            if len(training_rows) < minimum:
                enough_history_failures.append({"segment_id": segment_id, "model_id": model_id, "training_points": len(training_rows), "minimum": minimum})
        weekday_anchors = weekday_anchor_map(training_rows)
        for forecast_date in forecast_dates:
            if forecast_date.weekday() not in weekday_anchors:
                seasonal_anchor_failures.append({"segment_id": segment_id, "forecast_date": forecast_date.isoformat(), "weekday": forecast_date.strftime("%A")})

    if enough_history_failures or seasonal_anchor_failures:
        checks.append(
            failed(
                "enough_history_for_declared_models",
                len(enough_history_failures) + len(seasonal_anchor_failures),
                "enough history and same-weekday anchors for every baseline",
                [*enough_history_failures[:5], *seasonal_anchor_failures[:5]],
            )
        )
        return forecast_rows, trace_rows, checks
    checks.append(passed("enough_history_for_declared_models", "all declared models"))

    for segment_id, training_rows in training_by_segment.items():
        first_row = training_rows[0]
        last_row = training_rows[-1]
        last_seven = training_rows[-7:]
        weekday_anchors = weekday_anchor_map(training_rows)
        drift_per_day = (last_row["_value"] - first_row["_value"]) / max((last_row["_date"] - first_row["_date"]).days, 1)
        moving_average_7 = sum(row["_value"] for row in last_seven) / len(last_seven)

        for model in spec["models"]:
            model_id = str(model["model_id"])
            kind = str(model["kind"])
            anchor_dates: list[date]
            anchor_values: list[float]
            notes = ""
            if kind == "naive":
                anchor_dates = [last_row["_date"]]
                anchor_values = [last_row["_value"]]
            elif kind == "seasonal_naive":
                anchor_dates = sorted({weekday_anchors[forecast_date.weekday()]["_date"] for forecast_date in forecast_dates})
                anchor_values = [weekday_anchors[day.weekday()]["_value"] for day in anchor_dates]
            elif kind == "drift":
                anchor_dates = [first_row["_date"], last_row["_date"]]
                anchor_values = [first_row["_value"], last_row["_value"]]
                notes = f"drift_per_day={format_number(drift_per_day)}"
            elif kind == "moving_average":
                anchor_dates = [row["_date"] for row in last_seven]
                anchor_values = [row["_value"] for row in last_seven]
                notes = f"moving_average_7={format_number(moving_average_7)}"
            else:
                continue

            trace_rows.append(
                {
                    "forecast_id": spec["forecast_id"],
                    "baseline_id": spec["baseline_id"],
                    "segment_id": segment_id,
                    "model_id": model_id,
                    "status": "ready",
                    "training_points": str(len(training_rows)),
                    "training_start": spec["training_start"].isoformat(),
                    "training_end": spec["training_end"].isoformat(),
                    "first_forecast_date": spec["first_forecast_date"].isoformat(),
                    "horizon_end": spec["horizon_end"].isoformat(),
                    "anchor_policy": str(model["anchor_policy"]),
                    "primary_baseline": str(model_id == spec["primary_baseline_model"]).lower(),
                    "seasonal_period_days": str(model.get("seasonal_period_days", "")),
                    "moving_average_window": str(model.get("window_days", "")),
                    "drift_per_day": format_number(drift_per_day) if kind == "drift" else "",
                    "anchor_dates": ";".join(day.isoformat() for day in anchor_dates),
                    "anchor_values": ";".join(format_number(value) for value in anchor_values),
                    "notes": notes,
                }
            )

            for horizon_step, forecast_date in enumerate(forecast_dates, start=1):
                if kind == "naive":
                    forecast_value = last_row["_value"]
                    row_anchor_dates = [last_row["_date"]]
                    row_anchor_values = [last_row["_value"]]
                elif kind == "seasonal_naive":
                    anchor = weekday_anchors[forecast_date.weekday()]
                    forecast_value = anchor["_value"]
                    row_anchor_dates = [anchor["_date"]]
                    row_anchor_values = [anchor["_value"]]
                elif kind == "drift":
                    days_after_training_end = (forecast_date - spec["training_end"]).days
                    forecast_value = last_row["_value"] + days_after_training_end * drift_per_day
                    row_anchor_dates = [first_row["_date"], last_row["_date"]]
                    row_anchor_values = [first_row["_value"], last_row["_value"]]
                elif kind == "moving_average":
                    forecast_value = moving_average_7
                    row_anchor_dates = [row["_date"] for row in last_seven]
                    row_anchor_values = [row["_value"] for row in last_seven]
                forecast_rows.append(
                    {
                        "forecast_id": spec["forecast_id"],
                        "baseline_id": spec["baseline_id"],
                        "metric_id": spec["target_metric"],
                        "segment_id": segment_id,
                        "model_id": model_id,
                        "forecast_date": forecast_date.isoformat(),
                        "horizon_step": str(horizon_step),
                        "forecast_value": format_number(forecast_value),
                        "anchor_dates": ";".join(day.isoformat() for day in row_anchor_dates),
                        "anchor_values": ";".join(format_number(value) for value in row_anchor_values),
                        "trace_rule": str(model["anchor_policy"]),
                    }
                )

    return forecast_rows, trace_rows, checks


def weekday_anchor_map(training_rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    anchors: dict[int, dict[str, Any]] = {}
    for row in training_rows:
        anchors[row["_date"].weekday()] = row
    return anchors


def audit_forecast_outputs(
    forecast_rows: list[dict[str, str]],
    trace_rows: list[dict[str, str]],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    expected_count = len(spec["target_segments"]) * len(spec["models"]) * spec["horizon_days"]
    if len(forecast_rows) != expected_count:
        checks.append(failed("forecast_table_has_full_horizon", len(forecast_rows), expected_count))
    else:
        checks.append(passed("forecast_table_has_full_horizon", expected_count))

    key_counts = Counter((row["segment_id"], row["model_id"], row["forecast_date"]) for row in forecast_rows)
    duplicate_keys = [
        {"segment_id": segment_id, "model_id": model_id, "forecast_date": forecast_date, "count": count}
        for (segment_id, model_id, forecast_date), count in key_counts.items()
        if count > 1
    ]
    if duplicate_keys:
        checks.append(failed("one_forecast_per_segment_model_date", len(duplicate_keys), "unique forecast grain", duplicate_keys[:10]))
    else:
        checks.append(passed("one_forecast_per_segment_model_date", len(key_counts)))

    anchor_failures = []
    for row in forecast_rows:
        for anchor_date_value in row["anchor_dates"].split(";"):
            anchor_date = parse_date(anchor_date_value, "anchor_dates")
            if anchor_date > spec["training_end"] or anchor_date in set(spec["embargo_dates"]):
                anchor_failures.append(
                    {
                        "segment_id": row["segment_id"],
                        "model_id": row["model_id"],
                        "forecast_date": row["forecast_date"],
                        "anchor_date": anchor_date.isoformat(),
                    }
                )
    if anchor_failures:
        checks.append(failed("no_embargo_or_future_rows_used_as_anchors", len(anchor_failures), "anchors are training dates before or at cutoff", anchor_failures[:10]))
    else:
        checks.append(passed("no_embargo_or_future_rows_used_as_anchors", "all forecast anchors"))

    trace_anchor_failures = []
    for row in trace_rows:
        for anchor_date_value in row["anchor_dates"].split(";"):
            anchor_date = parse_date(anchor_date_value, "trace anchor_dates")
            if anchor_date < spec["training_start"] or anchor_date > spec["training_end"] or anchor_date in set(spec["embargo_dates"]):
                trace_anchor_failures.append(
                    {
                        "segment_id": row["segment_id"],
                        "model_id": row["model_id"],
                        "anchor_date": anchor_date.isoformat(),
                    }
                )
    if trace_anchor_failures:
        checks.append(failed("forecast_trace_anchors_are_training_rows", len(trace_anchor_failures), "trace anchors come from training rows", trace_anchor_failures[:10]))
    else:
        checks.append(passed("forecast_trace_anchors_are_training_rows", len(trace_rows)))
    return checks


def build_report(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    checks: list[dict[str, Any]],
    forecast_rows: list[dict[str, str]],
    trace_rows: list[dict[str, str]],
) -> dict[str, Any]:
    error_failures = [check for check in checks if not check["valid"] and check["severity"] == "error"]
    warning_failures = [check for check in checks if not check["valid"] and check["severity"] == "warning"]
    model_ids = sorted({row["model_id"] for row in forecast_rows})
    return {
        "audit_id": "baseline-forecast-report",
        "baseline_id": spec.get("baseline_id"),
        "forecast_id": scenario.get("forecast_id", spec.get("forecast_id")),
        "valid": not error_failures,
        "warning_count": len(warning_failures),
        "error_count": len(error_failures),
        "checks": checks,
        "outputs": {
            "forecast_rows": len(forecast_rows),
            "trace_rows": len(trace_rows),
            "segments": sorted({row["segment_id"] for row in forecast_rows}),
            "models": model_ids,
            "primary_baseline_model": spec.get("primary_baseline_model"),
        },
        "policy": spec.get("baseline_policy", {}),
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
        output_dir / "baseline_forecasts.csv",
        package["forecast_rows"],
        [
            "forecast_id",
            "baseline_id",
            "metric_id",
            "segment_id",
            "model_id",
            "forecast_date",
            "horizon_step",
            "forecast_value",
            "anchor_dates",
            "anchor_values",
            "trace_rule",
        ],
    )
    write_csv(
        output_dir / "baseline_trace.csv",
        package["trace_rows"],
        [
            "forecast_id",
            "baseline_id",
            "segment_id",
            "model_id",
            "status",
            "training_points",
            "training_start",
            "training_end",
            "first_forecast_date",
            "horizon_end",
            "anchor_policy",
            "primary_baseline",
            "seasonal_period_days",
            "moving_average_window",
            "drift_per_day",
            "anchor_dates",
            "anchor_values",
            "notes",
        ],
    )
    (output_dir / "baseline_report.json").write_text(
        json.dumps(package["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build naive, seasonal naive, drift, and moving-average baselines.")
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--cutoff-contract", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    package = build_baseline_forecast_package(
        series_path=args.series,
        calendar_path=args.calendar,
        scenario_path=args.scenario,
        cutoff_contract_path=args.cutoff_contract,
        spec_path=args.spec,
    )
    write_package(args.output_dir, package)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "forecast_rows": report["outputs"]["forecast_rows"],
                "models": report["outputs"]["models"],
                "primary_baseline_model": report["outputs"]["primary_baseline_model"],
            },
            ensure_ascii=False,
        )
    )
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
