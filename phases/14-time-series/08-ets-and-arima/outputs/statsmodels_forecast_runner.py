from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import statsmodels
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing


REQUIRED_SERIES_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "frequency",
    "value",
    "include_in_training",
}
REQUIRED_CALENDAR_COLUMNS = {"date", "day_of_week", "campaign_active", "release_active", "known_before_date"}
REQUIRED_BASELINE_FORECAST_COLUMNS = {
    "forecast_id",
    "baseline_id",
    "metric_id",
    "segment_id",
    "model_id",
    "forecast_date",
    "horizon_step",
    "forecast_value",
}
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
REQUIRED_REPORT_FIELDS = {"forecast_id", "valid", "outputs", "summary"}
REQUIRED_SPEC_FIELDS = {
    "model_run_id",
    "forecast_id",
    "source_table",
    "cutoff_contract_id",
    "baseline_id",
    "decomposition_id",
    "target_metric",
    "target_segments",
    "time_column",
    "value_column",
    "complete_flag_column",
    "training_start",
    "training_end",
    "forecast_origin",
    "first_forecast_date",
    "horizon_end",
    "horizon_days",
    "timezone",
    "frequency",
    "seasonal_period_days",
    "embargo_dates",
    "primary_baseline_model",
    "uses_exogenous_calendar_features",
    "minimum_cycles_for_model_selection",
    "selection_policy",
    "candidate_models",
    "residual_diagnostics",
}
REQUIRED_MODEL_FIELDS = {
    "model_id",
    "family",
    "statsmodels_class",
    "minimum_training_points",
    "minimum_training_cycles",
}
REQUIRED_ETS_FIELDS = {"trend", "seasonal", "seasonal_periods", "initialization_method"}
REQUIRED_ARIMA_FIELDS = {"order", "seasonal_order", "trend"}
SUPPORTED_FAMILIES = {"ETS", "ARIMA"}


class StatsmodelsForecastError(ValueError):
    """Raised when a statsmodels forecast input cannot be interpreted."""


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
        raise StatsmodelsForecastError(f"{path.name} must contain a JSON object")
    return value


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise StatsmodelsForecastError(f"{field} must be ISO date: {value}") from error


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise StatsmodelsForecastError(f"{field} must be ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StatsmodelsForecastError(f"{field} must be timezone-aware: {value}")
    return parsed


def parse_bool(value: str | bool, field: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise StatsmodelsForecastError(f"{field} must be true or false: {value}")
    return normalized == "true"


def parse_number(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise StatsmodelsForecastError(f"{field} must be numeric: {value}") from error


def parse_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise StatsmodelsForecastError(f"{field} must be an integer: {value}")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise StatsmodelsForecastError(f"{field} must be an integer: {value}") from error


def parse_int_list(value: Any, field: str, length: int) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise StatsmodelsForecastError(f"{field} must be a list with {length} integers")
    parsed = tuple(parse_int(item, field) for item in value)
    if any(item < 0 for item in parsed):
        raise StatsmodelsForecastError(f"{field} cannot contain negative integers: {value}")
    return parsed


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def format_number(value: float | int | None) -> str:
    if value is None:
        return ""
    number = float(value)
    if math.isnan(number) or math.isinf(number):
        return ""
    rounded = round(number, 6)
    if rounded == 0:
        return "0"
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
    baseline_report: dict[str, Any],
    decomposition_report: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    missing_scenario = sorted(REQUIRED_SCENARIO_FIELDS - set(scenario))
    missing_cutoff = sorted(REQUIRED_CUTOFF_FIELDS - set(cutoff_contract))
    missing_baseline_report = sorted(REQUIRED_REPORT_FIELDS - set(baseline_report))
    missing_decomposition_report = sorted(REQUIRED_REPORT_FIELDS - set(decomposition_report))

    if missing_spec:
        checks.append(failed("model_spec_required_fields", missing_spec, "all required model spec fields"))
        return checks, None
    checks.append(passed("model_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))
    if missing_scenario:
        checks.append(failed("scenario_required_fields", missing_scenario, "all required scenario fields"))
        return checks, None
    checks.append(passed("scenario_required_fields", len(REQUIRED_SCENARIO_FIELDS)))
    if missing_cutoff:
        checks.append(failed("cutoff_contract_required_fields", missing_cutoff, "all required cutoff fields"))
        return checks, None
    checks.append(passed("cutoff_contract_required_fields", len(REQUIRED_CUTOFF_FIELDS)))
    if missing_baseline_report:
        checks.append(failed("baseline_report_required_fields", missing_baseline_report, "all required baseline report fields"))
        return checks, None
    checks.append(passed("baseline_report_required_fields", len(REQUIRED_REPORT_FIELDS)))
    if missing_decomposition_report:
        checks.append(
            failed("decomposition_report_required_fields", missing_decomposition_report, "all required decomposition report fields")
        )
        return checks, None
    checks.append(passed("decomposition_report_required_fields", len(REQUIRED_REPORT_FIELDS)))

    try:
        timezone = ZoneInfo(str(spec["timezone"]))
        forecast_origin = parse_timestamp(str(spec["forecast_origin"]), "forecast_origin")
        training_start = parse_date(str(spec["training_start"]), "training_start")
        training_end = parse_date(str(spec["training_end"]), "training_end")
        first_forecast_date = parse_date(str(spec["first_forecast_date"]), "first_forecast_date")
        horizon_end = parse_date(str(spec["horizon_end"]), "horizon_end")
        horizon_days = parse_int(spec["horizon_days"], "horizon_days")
        seasonal_period_days = parse_int(spec["seasonal_period_days"], "seasonal_period_days")
        minimum_cycles_for_model_selection = float(spec["minimum_cycles_for_model_selection"])
    except (ZoneInfoNotFoundError, StatsmodelsForecastError, TypeError, ValueError) as error:
        checks.append(failed("model_spec_values_parse", str(error), "valid dates, timezone, horizon, and cycle settings"))
        return checks, None
    checks.append(passed("model_spec_values_parse", spec["model_run_id"]))

    segments = spec.get("target_segments")
    if not isinstance(segments, list) or not segments or not all(isinstance(item, str) and item for item in segments):
        checks.append(failed("target_segments_declared", segments, "non-empty segment list"))
        return checks, None
    checks.append(passed("target_segments_declared", segments))

    align_errors: list[str] = []
    if spec["forecast_id"] != scenario["forecast_id"] or spec["forecast_id"] != cutoff_contract["forecast_id"]:
        align_errors.append("forecast_id")
    if spec["target_metric"] != scenario["target_metric"] or spec["target_metric"] != cutoff_contract["target_metric"]:
        align_errors.append("target_metric")
    if spec["target_segments"] != scenario["target_segments"] or spec["target_segments"] != cutoff_contract["target_segments"]:
        align_errors.append("target_segments")
    if spec["timezone"] != scenario["timezone"] or spec["timezone"] != cutoff_contract["timezone"]:
        align_errors.append("timezone")
    if spec["frequency"] != scenario["frequency"] or spec["frequency"] != cutoff_contract["frequency"]:
        align_errors.append("frequency")
    if str(spec["forecast_origin"]) != str(scenario["forecast_origin"]) or str(spec["forecast_origin"]) != str(cutoff_contract["forecast_origin"]):
        align_errors.append("forecast_origin")
    for field in ("training_start", "training_end", "first_forecast_date", "horizon_end", "horizon_days", "embargo_dates"):
        if spec[field] != cutoff_contract[field]:
            align_errors.append(field)
    if spec["cutoff_contract_id"] != cutoff_contract["leakage_audit_id"]:
        align_errors.append("cutoff_contract_id")
    if spec["baseline_id"] != baseline_report.get("baseline_id"):
        align_errors.append("baseline_id")
    if spec["decomposition_id"] != decomposition_report.get("decomposition_id"):
        align_errors.append("decomposition_id")
    if spec["forecast_id"] != baseline_report.get("forecast_id") or spec["forecast_id"] != decomposition_report.get("forecast_id"):
        align_errors.append("upstream_forecast_id")
    if cutoff_contract["split_type"] != "time_ordered_cutoff":
        align_errors.append("split_type")

    if align_errors:
        checks.append(
            failed(
                "scenario_cutoff_baseline_decomposition_and_model_spec_align",
                sorted(set(align_errors)),
                "scenario, cutoff, baseline, decomposition, and model spec agree",
            )
        )
    else:
        checks.append(passed("scenario_cutoff_baseline_decomposition_and_model_spec_align", "all setup ids and dates aligned"))

    primary_baseline = spec["primary_baseline_model"]
    baseline_primary = baseline_report.get("outputs", {}).get("primary_baseline_model")
    if baseline_report.get("valid") is not True or decomposition_report.get("valid") is not True or primary_baseline != baseline_primary:
        checks.append(
            failed(
                "baseline_and_decomposition_reports_are_valid",
                {
                    "baseline_valid": baseline_report.get("valid"),
                    "decomposition_valid": decomposition_report.get("valid"),
                    "baseline_primary": baseline_primary,
                },
                "valid upstream reports and matching primary baseline",
            )
        )
    else:
        checks.append(passed("baseline_and_decomposition_reports_are_valid", primary_baseline))

    if horizon_days != len(daterange(first_forecast_date, horizon_end)):
        checks.append(failed("forecast_horizon_matches_contract", horizon_days, len(daterange(first_forecast_date, horizon_end))))
    else:
        checks.append(passed("forecast_horizon_matches_contract", horizon_days))
    if first_forecast_date <= training_end or training_start > training_end or horizon_end < first_forecast_date:
        checks.append(
            failed(
                "cutoff_contract_is_time_ordered",
                {
                    "training_start": training_start.isoformat(),
                    "training_end": training_end.isoformat(),
                    "first_forecast_date": first_forecast_date.isoformat(),
                    "horizon_end": horizon_end.isoformat(),
                },
                "training_start <= training_end < first_forecast_date <= horizon_end",
            )
        )
    else:
        checks.append(passed("cutoff_contract_is_time_ordered", cutoff_contract["split_type"]))

    policy = spec.get("selection_policy")
    no_auto_policy = isinstance(policy, dict) and policy.get("no_auto_model_search") is True
    no_in_sample_choice = isinstance(policy, dict) and policy.get("do_not_select_on_in_sample_fit") is True
    declared_before_eval = isinstance(policy, dict) and policy.get("candidate_models_declared_before_evaluation") is True
    baseline_policy = isinstance(policy, dict) and policy.get("candidate_model_must_beat") == primary_baseline
    if not (no_auto_policy and no_in_sample_choice and declared_before_eval and baseline_policy):
        checks.append(failed("no_auto_model_search", policy, "predeclared candidates, no auto-search, no in-sample selection"))
    else:
        checks.append(passed("no_auto_model_search", "predeclared candidates only"))

    models = spec.get("candidate_models")
    if not isinstance(models, list) or not models:
        checks.append(failed("candidate_models_declared", models, "non-empty candidate model list"))
        return checks, None

    model_ids: list[str] = []
    families: set[str] = set()
    declaration_errors: list[dict[str, Any]] = []
    explicit_errors: list[dict[str, Any]] = []
    auto_errors: list[str] = []
    normalized_models: list[dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            declaration_errors.append({"model": model, "error": "model definition must be an object"})
            continue
        model_id = str(model.get("model_id", ""))
        model_ids.append(model_id)
        family = str(model.get("family", ""))
        families.add(family)
        missing = sorted(REQUIRED_MODEL_FIELDS - set(model))
        if missing:
            declaration_errors.append({"model_id": model_id, "missing": missing})
        if family not in SUPPORTED_FAMILIES:
            declaration_errors.append({"model_id": model_id, "family": family})
        if model.get("auto") is True or model.get("auto_model_search") is True or "auto" in model_id.lower():
            auto_errors.append(model_id)
        try:
            normalized = dict(model)
            normalized["minimum_training_points"] = parse_int(model.get("minimum_training_points"), f"{model_id}.minimum_training_points")
            normalized["minimum_training_cycles"] = float(model.get("minimum_training_cycles"))
            if family == "ETS":
                missing_ets = sorted(REQUIRED_ETS_FIELDS - set(model))
                if missing_ets:
                    explicit_errors.append({"model_id": model_id, "missing": missing_ets})
                if parse_int(model.get("seasonal_periods"), f"{model_id}.seasonal_periods") != seasonal_period_days:
                    explicit_errors.append({"model_id": model_id, "seasonal_periods": model.get("seasonal_periods")})
            if family == "ARIMA":
                missing_arima = sorted(REQUIRED_ARIMA_FIELDS - set(model))
                if missing_arima:
                    explicit_errors.append({"model_id": model_id, "missing": missing_arima})
                normalized["order"] = parse_int_list(model.get("order"), f"{model_id}.order", 3)
                normalized["seasonal_order"] = parse_int_list(model.get("seasonal_order"), f"{model_id}.seasonal_order", 4)
            normalized_models.append(normalized)
        except (StatsmodelsForecastError, TypeError, ValueError) as error:
            explicit_errors.append({"model_id": model_id, "error": str(error)})

    duplicate_ids = sorted(model_id for model_id, count in Counter(model_ids).items() if count > 1)
    if declaration_errors or duplicate_ids:
        checks.append(
            failed(
                "candidate_models_declared",
                {"declaration_errors": declaration_errors, "duplicate_ids": duplicate_ids},
                "unique candidate model ids with required fields and supported families",
            )
        )
    else:
        checks.append(passed("candidate_models_declared", model_ids))
    if {"ETS", "ARIMA"}.issubset(families):
        checks.append(passed("ets_and_arima_families_present", sorted(families)))
    else:
        checks.append(failed("ets_and_arima_families_present", sorted(families), "at least one ETS and one ARIMA candidate"))
    if auto_errors:
        checks.append(failed("no_auto_model_search", auto_errors, "no candidate may request auto-model search"))
    if explicit_errors:
        checks.append(failed("orders_and_initialization_are_explicit", explicit_errors, "explicit ETS initialization and ARIMA orders"))
    else:
        checks.append(passed("orders_and_initialization_are_explicit", model_ids))

    if has_blocking_errors(checks):
        return checks, None

    context = {
        "timezone": timezone,
        "forecast_origin": forecast_origin,
        "segments": segments,
        "training_start": training_start,
        "training_end": training_end,
        "first_forecast_date": first_forecast_date,
        "horizon_end": horizon_end,
        "horizon_days": horizon_days,
        "seasonal_period_days": seasonal_period_days,
        "embargo_dates": [parse_date(str(item), "embargo_dates") for item in spec["embargo_dates"]],
        "minimum_cycles_for_model_selection": minimum_cycles_for_model_selection,
        "candidate_models": normalized_models,
        "primary_baseline_model": primary_baseline,
    }
    return checks, context


def parse_source_series(
    rows: list[dict[str, str]],
    fields: list[str],
    spec: dict[str, Any],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]] | None]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SERIES_COLUMNS - set(fields))
    if missing:
        checks.append(failed("series_columns_present", missing, "required series columns"))
        return checks, None
    checks.append(passed("series_columns_present", len(fields)))

    parsed_rows: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    for row in rows:
        try:
            parsed_rows.append(
                {
                    "metric_id": row["metric_id"],
                    "segment_id": row["segment_id"],
                    "observed_date": parse_date(row["observed_date"], "observed_date"),
                    "frequency": row["frequency"],
                    "value": parse_number(row["value"], "value"),
                    "include_in_training": parse_bool(row["include_in_training"], "include_in_training"),
                }
            )
        except StatsmodelsForecastError as error:
            parse_errors.append({"row": row.get("observed_date", ""), "error": str(error)})
    if parse_errors:
        checks.append(failed("series_rows_parse", len(parse_errors), "all series rows parse", parse_errors[:5]))
        return checks, None
    checks.append(passed("series_rows_parse", len(parsed_rows)))

    target_rows = [
        row
        for row in parsed_rows
        if row["metric_id"] == spec["target_metric"] and row["segment_id"] in context["segments"]
    ]
    key_counts = Counter((row["metric_id"], row["segment_id"], row["observed_date"]) for row in target_rows)
    duplicate_keys = [key for key, count in key_counts.items() if count > 1]
    if duplicate_keys:
        checks.append(
            failed(
                "source_segment_date_unique",
                len(duplicate_keys),
                "one row per metric, segment, and date",
                [":".join((key[0], key[1], key[2].isoformat())) for key in duplicate_keys[:5]],
            )
        )
    else:
        checks.append(passed("source_segment_date_unique", len(target_rows)))

    expected_training_dates = daterange(context["training_start"], context["training_end"])
    training_by_segment: dict[str, list[dict[str, Any]]] = {}
    training_window_errors: list[dict[str, Any]] = []
    outside_training_rows: list[dict[str, str]] = []
    for segment in context["segments"]:
        segment_rows = [row for row in target_rows if row["segment_id"] == segment]
        if any(row["frequency"] != spec["frequency"] for row in segment_rows):
            training_window_errors.append({"segment_id": segment, "error": "frequency_mismatch"})
        training_rows = sorted((row for row in segment_rows if row["include_in_training"]), key=lambda row: row["observed_date"])
        training_by_segment[segment] = training_rows
        observed_training_dates = [row["observed_date"] for row in training_rows]
        if observed_training_dates != expected_training_dates:
            training_window_errors.append(
                {
                    "segment_id": segment,
                    "observed": [item.isoformat() for item in observed_training_dates],
                    "expected": [item.isoformat() for item in expected_training_dates],
                }
            )
        for row in training_rows:
            if row["observed_date"] < context["training_start"] or row["observed_date"] > context["training_end"]:
                outside_training_rows.append({"segment_id": segment, "observed_date": row["observed_date"].isoformat()})
            if row["observed_date"] in context["embargo_dates"]:
                outside_training_rows.append({"segment_id": segment, "observed_date": row["observed_date"].isoformat()})
    if training_window_errors:
        checks.append(failed("training_rows_match_cutoff", len(training_window_errors), "exact complete training window", training_window_errors[:3]))
    else:
        checks.append(passed("training_rows_match_cutoff", context["training_end"].isoformat()))
    if outside_training_rows:
        checks.append(
            failed(
                "model_uses_training_window_only",
                len(outside_training_rows),
                "no training rows outside cutoff window or inside embargo",
                outside_training_rows[:5],
            )
        )
    else:
        checks.append(passed("model_uses_training_window_only", context["training_end"].isoformat()))

    history_errors: list[dict[str, Any]] = []
    short_history_samples: list[dict[str, str]] = []
    for segment, training_rows in training_by_segment.items():
        points = len(training_rows)
        cycles = points / context["seasonal_period_days"]
        if cycles < context["minimum_cycles_for_model_selection"]:
            short_history_samples.append(
                {
                    "segment_id": segment,
                    "training_cycles": format_number(cycles),
                    "minimum_cycles_for_model_selection": format_number(context["minimum_cycles_for_model_selection"]),
                }
            )
        for model in context["candidate_models"]:
            if points < model["minimum_training_points"] or cycles < model["minimum_training_cycles"]:
                history_errors.append(
                    {
                        "segment_id": segment,
                        "model_id": model["model_id"],
                        "training_points": points,
                        "training_cycles": format_number(cycles),
                    }
                )
    if history_errors:
        checks.append(failed("enough_history_for_declared_candidates", history_errors, "minimum history per candidate and segment"))
    else:
        checks.append(passed("enough_history_for_declared_candidates", "all declared candidates"))
    if short_history_samples:
        checks.append(
            failed(
                "short_history_blocks_model_selection_claim",
                len(short_history_samples),
                "enough cycles for model selection claim",
                short_history_samples,
                severity="warning",
            )
        )
    else:
        checks.append(passed("short_history_blocks_model_selection_claim", "enough cycles for model selection"))

    if has_blocking_errors(checks):
        return checks, None
    return checks, training_by_segment


def audit_calendar(
    rows: list[dict[str, str]],
    fields: list[str],
    spec: dict[str, Any],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_CALENDAR_COLUMNS - set(fields))
    if missing:
        checks.append(failed("calendar_columns_present", missing, "required calendar columns"))
        return checks
    checks.append(passed("calendar_columns_present", len(fields)))

    horizon_dates = daterange(context["first_forecast_date"], context["horizon_end"])
    parse_errors: list[dict[str, str]] = []
    parsed_rows: list[dict[str, Any]] = []
    for row in rows:
        try:
            parsed_rows.append(
                {
                    "date": parse_date(row["date"], "date"),
                    "day_of_week": row["day_of_week"],
                    "campaign_active": parse_bool(row["campaign_active"], "campaign_active"),
                    "release_active": parse_bool(row["release_active"], "release_active"),
                    "known_before_date": parse_date(row["known_before_date"], "known_before_date"),
                }
            )
        except StatsmodelsForecastError as error:
            parse_errors.append({"date": row.get("date", ""), "error": str(error)})
    if parse_errors:
        checks.append(failed("calendar_rows_parse", len(parse_errors), "all calendar rows parse", parse_errors[:5]))
        return checks
    checks.append(passed("calendar_rows_parse", len(parsed_rows)))

    calendar_by_date = {row["date"]: row for row in parsed_rows}
    missing_horizon = [day.isoformat() for day in horizon_dates if day not in calendar_by_date]
    if missing_horizon:
        checks.append(failed("calendar_covers_forecast_horizon", len(missing_horizon), "calendar covers full horizon", missing_horizon[:5]))
        return checks
    checks.append(passed("calendar_covers_forecast_horizon", len(horizon_dates)))

    known_future_effects = [
        {
            "date": row["date"].isoformat(),
            "day_of_week": row["day_of_week"],
            "effect": "campaign_active" if row["campaign_active"] else "release_active",
        }
        for row in (calendar_by_date[day] for day in horizon_dates)
        if (row["campaign_active"] or row["release_active"]) and row["known_before_date"] <= context["forecast_origin"].date()
    ]
    if known_future_effects and spec["uses_exogenous_calendar_features"] is False:
        checks.append(
            failed(
                "known_future_calendar_effects_not_modeled_by_candidates",
                len(known_future_effects),
                "candidate models intentionally do not use exogenous calendar regressors",
                known_future_effects[:8],
                severity="warning",
            )
        )
    else:
        checks.append(passed("known_future_calendar_effects_not_modeled_by_candidates", 0))
    return checks


def read_primary_baseline_forecasts(
    rows: list[dict[str, str]],
    fields: list[str],
    spec: dict[str, Any],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[tuple[str, date], dict[str, Any]] | None]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_BASELINE_FORECAST_COLUMNS - set(fields))
    if missing:
        checks.append(failed("baseline_forecast_columns_present", missing, "required baseline forecast columns"))
        return checks, None
    checks.append(passed("baseline_forecast_columns_present", len(fields)))

    primary_rows: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    for row in rows:
        if (
            row["forecast_id"] != spec["forecast_id"]
            or row["baseline_id"] != spec["baseline_id"]
            or row["metric_id"] != spec["target_metric"]
            or row["model_id"] != context["primary_baseline_model"]
            or row["segment_id"] not in context["segments"]
        ):
            continue
        try:
            primary_rows.append(
                {
                    "forecast_id": row["forecast_id"],
                    "baseline_id": row["baseline_id"],
                    "metric_id": row["metric_id"],
                    "segment_id": row["segment_id"],
                    "model_id": row["model_id"],
                    "forecast_date": parse_date(row["forecast_date"], "forecast_date"),
                    "horizon_step": parse_int(row["horizon_step"], "horizon_step"),
                    "forecast_value": parse_number(row["forecast_value"], "forecast_value"),
                }
            )
        except StatsmodelsForecastError as error:
            parse_errors.append({"forecast_date": row.get("forecast_date", ""), "error": str(error)})
    if parse_errors:
        checks.append(failed("baseline_forecast_rows_parse", len(parse_errors), "all baseline forecast rows parse", parse_errors[:5]))
        return checks, None
    checks.append(passed("baseline_forecast_rows_parse", len(primary_rows)))

    horizon_dates = daterange(context["first_forecast_date"], context["horizon_end"])
    expected_keys = {(segment, day) for segment in context["segments"] for day in horizon_dates}
    key_counts = Counter((row["segment_id"], row["forecast_date"]) for row in primary_rows)
    duplicate_keys = [key for key, count in key_counts.items() if count > 1]
    observed_keys = set(key_counts)
    missing_keys = sorted(expected_keys - observed_keys)
    extra_keys = sorted(observed_keys - expected_keys)
    if duplicate_keys or missing_keys or extra_keys:
        checks.append(
            failed(
                "baseline_forecasts_have_primary_shape",
                {
                    "duplicates": len(duplicate_keys),
                    "missing": len(missing_keys),
                    "extra": len(extra_keys),
                },
                "one primary baseline forecast per segment and horizon date",
                [f"{segment}:{day.isoformat()}" for segment, day in (missing_keys[:5] or duplicate_keys[:5] or extra_keys[:5])],
            )
        )
        return checks, None
    checks.append(passed("baseline_forecasts_have_primary_shape", len(primary_rows)))

    baseline_map = {(row["segment_id"], row["forecast_date"]): row for row in primary_rows}
    return checks, baseline_map


def convergence_status(result: Any) -> str:
    retvals = getattr(result, "mle_retvals", None)
    if retvals is None:
        return "not_reported"
    converged = None
    if isinstance(retvals, dict):
        converged = retvals.get("converged", retvals.get("success"))
    else:
        converged = getattr(retvals, "converged", getattr(retvals, "success", None))
    if converged is True:
        return "converged"
    if converged is False:
        return "not_converged"
    return "not_reported"


def residual_burn_in(model: dict[str, Any]) -> int:
    if model["family"] != "ARIMA":
        return 0
    order = tuple(model["order"])
    seasonal_order = tuple(model["seasonal_order"])
    return order[1] + seasonal_order[1] * seasonal_order[3]


def residual_stats(residuals: Any, burn_in: int) -> dict[str, float | None]:
    series = pd.Series(residuals, dtype="float64").dropna()
    if burn_in:
        series = series.iloc[min(burn_in, len(series)) :]
    if series.empty:
        return {"mean": None, "std": None, "max_abs": None, "lag1": None}
    lag1 = None if len(series) < 2 else float(series.autocorr(lag=1))
    if lag1 is not None and math.isnan(lag1):
        lag1 = None
    return {
        "mean": float(series.mean()),
        "std": float(series.std(ddof=0)),
        "max_abs": float(series.abs().max()),
        "lag1": lag1,
    }


def fit_candidate_model(series: pd.Series, model: dict[str, Any], raw_steps_requested: int) -> dict[str, Any]:
    captured_warnings: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if model["family"] == "ETS":
            estimator = ExponentialSmoothing(
                series,
                trend=model.get("trend") or None,
                damped_trend=bool(model.get("damped_trend", False)),
                seasonal=model.get("seasonal") or None,
                seasonal_periods=parse_int(model.get("seasonal_periods"), f"{model['model_id']}.seasonal_periods"),
                initialization_method=str(model.get("initialization_method", "estimated")),
            )
            result = estimator.fit(optimized=True, remove_bias=False)
        elif model["family"] == "ARIMA":
            result = ARIMA(
                series,
                order=tuple(model["order"]),
                seasonal_order=tuple(model["seasonal_order"]),
                trend=str(model.get("trend", "n")),
                enforce_stationarity=bool(model.get("enforce_stationarity", False)),
                enforce_invertibility=bool(model.get("enforce_invertibility", False)),
            ).fit()
        else:
            raise StatsmodelsForecastError(f"unsupported model family: {model['family']}")

        forecast = result.forecast(steps=raw_steps_requested)
        for warning in caught:
            captured_warnings.append(f"{warning.category.__name__}: {warning.message}")

    burn_in = residual_burn_in(model)
    stats = residual_stats(getattr(result, "resid", []), burn_in)
    return {
        "forecast_values": [float(value) for value in forecast],
        "aic": getattr(result, "aic", None),
        "bic": getattr(result, "bic", None),
        "convergence_status": convergence_status(result),
        "warnings": captured_warnings,
        "residual_burn_in_rows": burn_in,
        "residual_stats": stats,
    }


def order_label(model: dict[str, Any], key: str) -> str:
    value = model.get(key)
    if value is None:
        return ""
    return ",".join(str(item) for item in value)


def build_model_outputs(
    spec: dict[str, Any],
    context: dict[str, Any],
    training_by_segment: dict[str, list[dict[str, Any]]],
    baseline_map: dict[tuple[str, date], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    forecast_rows: list[dict[str, Any]] = []
    diagnostics_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    fit_errors: list[dict[str, str]] = []
    warning_samples: list[dict[str, Any]] = []
    non_converged: list[dict[str, str]] = []
    residual_threshold_samples: list[dict[str, str]] = []

    horizon_dates = daterange(context["first_forecast_date"], context["horizon_end"])
    raw_steps_requested = (context["horizon_end"] - context["training_end"]).days
    skipped_embargo_dates = [
        day for day in context["embargo_dates"] if context["training_end"] < day < context["first_forecast_date"]
    ]
    if skipped_embargo_dates:
        checks.append(
            failed(
                "embargo_gap_skipped_before_forecast",
                len(skipped_embargo_dates),
                "statsmodels raw forecast includes gap dates but emitted forecast skips embargo",
                [day.isoformat() for day in skipped_embargo_dates],
                severity="warning",
            )
        )
    else:
        checks.append(passed("embargo_gap_skipped_before_forecast", 0))

    for segment, training_rows in training_by_segment.items():
        index = pd.DatetimeIndex([pd.Timestamp(row["observed_date"].isoformat()) for row in training_rows])
        values = [row["value"] for row in training_rows]
        series = pd.Series(values, index=index, dtype="float64").asfreq(spec["frequency"])
        if series.isna().any():
            fit_errors.append({"segment_id": segment, "model_id": "*", "error": "training series has missing dates"})
            continue

        for model in context["candidate_models"]:
            try:
                fit_result = fit_candidate_model(series, model, raw_steps_requested)
            except Exception as error:  # noqa: BLE001 - report model failure as artifact diagnostics.
                fit_errors.append({"segment_id": segment, "model_id": model["model_id"], "error": str(error)})
                continue

            model_warnings = fit_result["warnings"]
            if model_warnings:
                warning_samples.append({"segment_id": segment, "model_id": model["model_id"], "warnings": model_warnings[:3]})
            if fit_result["convergence_status"] not in {"converged", "not_reported"}:
                non_converged.append({"segment_id": segment, "model_id": model["model_id"], "status": fit_result["convergence_status"]})

            stats = fit_result["residual_stats"]
            residual_mean_abs_warn = float(spec["residual_diagnostics"]["residual_mean_abs_warn"])
            lag1_abs_warn = float(spec["residual_diagnostics"]["lag1_autocorrelation_abs_warn"])
            if stats["mean"] is not None and abs(stats["mean"]) > residual_mean_abs_warn:
                residual_threshold_samples.append(
                    {
                        "segment_id": segment,
                        "model_id": model["model_id"],
                        "metric": "residual_mean",
                        "value": format_number(stats["mean"]),
                    }
                )
            if stats["lag1"] is not None and abs(stats["lag1"]) > lag1_abs_warn:
                residual_threshold_samples.append(
                    {
                        "segment_id": segment,
                        "model_id": model["model_id"],
                        "metric": "lag1_autocorrelation",
                        "value": format_number(stats["lag1"]),
                    }
                )

            training_points = len(training_rows)
            training_cycles = training_points / context["seasonal_period_days"]
            decision_status = (
                "diagnostic_only_short_history"
                if training_cycles < context["minimum_cycles_for_model_selection"]
                else "ready_for_rolling_backtest"
            )
            diagnostics_rows.append(
                {
                    "forecast_id": spec["forecast_id"],
                    "model_run_id": spec["model_run_id"],
                    "metric_id": spec["target_metric"],
                    "segment_id": segment,
                    "model_id": model["model_id"],
                    "family": model["family"],
                    "statsmodels_class": model["statsmodels_class"],
                    "training_points": training_points,
                    "training_cycles": format_number(training_cycles),
                    "raw_steps_requested": raw_steps_requested,
                    "output_horizon_days": context["horizon_days"],
                    "fit_status": "fit",
                    "convergence_status": fit_result["convergence_status"],
                    "statsmodels_warning_count": len(model_warnings),
                    "statsmodels_warnings": " | ".join(model_warnings),
                    "residual_burn_in_rows": fit_result["residual_burn_in_rows"],
                    "residual_mean": format_number(stats["mean"]),
                    "residual_std": format_number(stats["std"]),
                    "residual_max_abs": format_number(stats["max_abs"]),
                    "lag1_autocorrelation": format_number(stats["lag1"]),
                    "aic": format_number(fit_result["aic"]),
                    "bic": format_number(fit_result["bic"]),
                    "order": order_label(model, "order"),
                    "seasonal_order": order_label(model, "seasonal_order"),
                    "trend": str(model.get("trend", "")),
                    "seasonal": str(model.get("seasonal", "")),
                    "seasonal_periods": str(model.get("seasonal_periods", "")),
                    "initialization_method": str(model.get("initialization_method", "")),
                    "decision_status": decision_status,
                }
            )

            raw_forecasts = fit_result["forecast_values"]
            for raw_step, forecast_value in enumerate(raw_forecasts, start=1):
                forecast_date = context["training_end"] + timedelta(days=raw_step)
                if forecast_date not in horizon_dates:
                    continue
                horizon_step = (forecast_date - context["first_forecast_date"]).days + 1
                forecast_row = {
                    "forecast_id": spec["forecast_id"],
                    "model_run_id": spec["model_run_id"],
                    "metric_id": spec["target_metric"],
                    "segment_id": segment,
                    "model_id": model["model_id"],
                    "family": model["family"],
                    "forecast_date": forecast_date.isoformat(),
                    "horizon_step": horizon_step,
                    "forecast_value": format_number(forecast_value),
                    "training_end": context["training_end"].isoformat(),
                    "raw_step": raw_step,
                    "skipped_embargo_dates": ";".join(day.isoformat() for day in skipped_embargo_dates),
                }
                forecast_rows.append(forecast_row)
                baseline = baseline_map.get((segment, forecast_date))
                if baseline is not None:
                    comparison_rows.append(
                        {
                            "forecast_id": spec["forecast_id"],
                            "model_run_id": spec["model_run_id"],
                            "metric_id": spec["target_metric"],
                            "segment_id": segment,
                            "candidate_model_id": model["model_id"],
                            "baseline_model_id": context["primary_baseline_model"],
                            "forecast_date": forecast_date.isoformat(),
                            "horizon_step": horizon_step,
                            "candidate_forecast": format_number(forecast_value),
                            "baseline_forecast": format_number(baseline["forecast_value"]),
                            "candidate_minus_baseline": format_number(forecast_value - baseline["forecast_value"]),
                            "comparison_status": "shape_only_pending_backtest_metrics",
                        }
                    )

    if fit_errors:
        checks.append(failed("statsmodels_candidate_fit", fit_errors, "all declared candidate models fit"))
    else:
        checks.append(passed("statsmodels_candidate_fit", "all declared candidates fit"))
    if warning_samples:
        checks.append(
            failed(
                "statsmodels_warnings_propagated",
                sum(len(sample["warnings"]) for sample in warning_samples),
                "library warnings are captured in diagnostics instead of hidden",
                warning_samples,
                severity="warning",
            )
        )
    else:
        checks.append(passed("statsmodels_warnings_propagated", 0))
    if non_converged:
        checks.append(
            failed(
                "statsmodels_convergence_reported",
                non_converged,
                "convergence status is visible for every fitted model",
                severity="warning",
            )
        )
    else:
        checks.append(passed("statsmodels_convergence_reported", "all converged or not reported"))
    if residual_threshold_samples:
        checks.append(
            failed(
                "residual_diagnostics_within_warning_thresholds",
                residual_threshold_samples,
                "residual diagnostics below warning thresholds",
                severity="warning",
            )
        )
    else:
        checks.append(passed("residual_diagnostics_within_warning_thresholds", "all residual diagnostics below warning thresholds"))

    expected_forecast_rows = len(context["segments"]) * len(context["candidate_models"]) * context["horizon_days"]
    expected_diagnostics_rows = len(context["segments"]) * len(context["candidate_models"])
    if len(diagnostics_rows) != expected_diagnostics_rows:
        checks.append(failed("model_diagnostics_emitted", len(diagnostics_rows), expected_diagnostics_rows))
    else:
        checks.append(passed("model_diagnostics_emitted", len(diagnostics_rows)))
    if len(forecast_rows) != expected_forecast_rows:
        checks.append(failed("forecast_table_has_full_horizon", len(forecast_rows), expected_forecast_rows))
    else:
        checks.append(passed("forecast_table_has_full_horizon", len(forecast_rows)))
    forecast_keys = [
        (row["metric_id"], row["segment_id"], row["model_id"], row["forecast_date"]) for row in forecast_rows
    ]
    duplicate_forecasts = [key for key, count in Counter(forecast_keys).items() if count > 1]
    if duplicate_forecasts:
        checks.append(failed("one_forecast_per_segment_model_date", len(duplicate_forecasts), "unique candidate forecast grain"))
    else:
        checks.append(passed("one_forecast_per_segment_model_date", len(forecast_rows)))
    if len(comparison_rows) != expected_forecast_rows:
        checks.append(failed("library_forecasts_match_baseline_shape", len(comparison_rows), expected_forecast_rows))
    else:
        checks.append(passed("library_forecasts_match_baseline_shape", len(comparison_rows)))

    return checks, forecast_rows, diagnostics_rows, comparison_rows


def empty_report(spec: dict[str, Any] | None, checks: list[dict[str, Any]]) -> dict[str, Any]:
    warning_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "warning")
    error_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "error")
    return {
        "audit_id": "statsmodels-forecast-report",
        "model_run_id": spec.get("model_run_id") if spec else None,
        "forecast_id": spec.get("forecast_id") if spec else None,
        "valid": error_count == 0,
        "warning_count": warning_count,
        "error_count": error_count,
        "checks": checks,
        "outputs": {
            "forecast_rows": 0,
            "diagnostics_rows": 0,
            "comparison_rows": 0,
            "candidate_models": [],
            "primary_baseline_model": None,
        },
        "selection_policy": spec.get("selection_policy", {}) if spec else {},
        "summary": {
            "checks_total": len(checks),
            "checks_failed": warning_count + error_count,
            "blocking_errors": [check["id"] for check in checks if not check["valid"] and check["severity"] == "error"],
            "warnings": [check["id"] for check in checks if not check["valid"] and check["severity"] == "warning"],
        },
    }


def build_report(
    spec: dict[str, Any],
    checks: list[dict[str, Any]],
    forecast_rows: list[dict[str, Any]],
    diagnostics_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    warning_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "warning")
    error_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "error")
    return {
        "audit_id": "statsmodels-forecast-report",
        "model_run_id": spec["model_run_id"],
        "forecast_id": spec["forecast_id"],
        "valid": error_count == 0,
        "warning_count": warning_count,
        "error_count": error_count,
        "checks": checks,
        "outputs": {
            "forecast_rows": len(forecast_rows),
            "diagnostics_rows": len(diagnostics_rows),
            "comparison_rows": len(comparison_rows),
            "candidate_models": [model["model_id"] for model in context["candidate_models"]],
            "primary_baseline_model": context["primary_baseline_model"],
            "training_start": context["training_start"].isoformat(),
            "training_end": context["training_end"].isoformat(),
            "first_forecast_date": context["first_forecast_date"].isoformat(),
            "horizon_end": context["horizon_end"].isoformat(),
            "statsmodels_version": statsmodels.__version__,
        },
        "selection_policy": spec["selection_policy"],
        "summary": {
            "checks_total": len(checks),
            "checks_failed": warning_count + error_count,
            "blocking_errors": [check["id"] for check in checks if not check["valid"] and check["severity"] == "error"],
            "warnings": [check["id"] for check in checks if not check["valid"] and check["severity"] == "warning"],
        },
    }


def build_statsmodels_forecast_package(
    *,
    series_path: Path,
    calendar_path: Path,
    scenario_path: Path,
    cutoff_contract_path: Path,
    baseline_report_path: Path,
    baseline_forecasts_path: Path,
    decomposition_report_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    spec = read_json(spec_path)
    scenario = read_json(scenario_path)
    cutoff_contract = read_json(cutoff_contract_path)
    baseline_report = read_json(baseline_report_path)
    decomposition_report = read_json(decomposition_report_path)
    checks, context = normalize_inputs(spec, scenario, cutoff_contract, baseline_report, decomposition_report)
    if context is None:
        return {"forecast_rows": [], "diagnostics_rows": [], "comparison_rows": [], "report": empty_report(spec, checks)}

    series_rows, series_fields = read_csv(series_path)
    source_checks, training_by_segment = parse_source_series(series_rows, series_fields, spec, context)
    checks.extend(source_checks)

    calendar_rows, calendar_fields = read_csv(calendar_path)
    checks.extend(audit_calendar(calendar_rows, calendar_fields, spec, context))

    baseline_rows, baseline_fields = read_csv(baseline_forecasts_path)
    baseline_checks, baseline_map = read_primary_baseline_forecasts(baseline_rows, baseline_fields, spec, context)
    checks.extend(baseline_checks)

    if has_blocking_errors(checks) or training_by_segment is None or baseline_map is None:
        return {"forecast_rows": [], "diagnostics_rows": [], "comparison_rows": [], "report": empty_report(spec, checks)}

    model_checks, forecast_rows, diagnostics_rows, comparison_rows = build_model_outputs(spec, context, training_by_segment, baseline_map)
    checks.extend(model_checks)
    report = build_report(spec, checks, forecast_rows, diagnostics_rows, comparison_rows, context)
    return {
        "forecast_rows": forecast_rows,
        "diagnostics_rows": diagnostics_rows,
        "comparison_rows": comparison_rows,
        "report": report,
    }


def write_package(package: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "candidate_forecasts.csv",
        package["forecast_rows"],
        [
            "forecast_id",
            "model_run_id",
            "metric_id",
            "segment_id",
            "model_id",
            "family",
            "forecast_date",
            "horizon_step",
            "forecast_value",
            "training_end",
            "raw_step",
            "skipped_embargo_dates",
        ],
    )
    write_csv(
        output_dir / "model_diagnostics.csv",
        package["diagnostics_rows"],
        [
            "forecast_id",
            "model_run_id",
            "metric_id",
            "segment_id",
            "model_id",
            "family",
            "statsmodels_class",
            "training_points",
            "training_cycles",
            "raw_steps_requested",
            "output_horizon_days",
            "fit_status",
            "convergence_status",
            "statsmodels_warning_count",
            "statsmodels_warnings",
            "residual_burn_in_rows",
            "residual_mean",
            "residual_std",
            "residual_max_abs",
            "lag1_autocorrelation",
            "aic",
            "bic",
            "order",
            "seasonal_order",
            "trend",
            "seasonal",
            "seasonal_periods",
            "initialization_method",
            "decision_status",
        ],
    )
    write_csv(
        output_dir / "library_vs_baseline.csv",
        package["comparison_rows"],
        [
            "forecast_id",
            "model_run_id",
            "metric_id",
            "segment_id",
            "candidate_model_id",
            "baseline_model_id",
            "forecast_date",
            "horizon_step",
            "candidate_forecast",
            "baseline_forecast",
            "candidate_minus_baseline",
            "comparison_status",
        ],
    )
    (output_dir / "model_report.json").write_text(
        json.dumps(package["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit predeclared ETS and ARIMA statsmodels candidates.")
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--cutoff-contract", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--baseline-forecasts", type=Path, required=True)
    parser.add_argument("--decomposition-report", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    package = build_statsmodels_forecast_package(
        series_path=args.series,
        calendar_path=args.calendar,
        scenario_path=args.scenario,
        cutoff_contract_path=args.cutoff_contract,
        baseline_report_path=args.baseline_report,
        baseline_forecasts_path=args.baseline_forecasts,
        decomposition_report_path=args.decomposition_report,
        spec_path=args.spec,
    )
    write_package(package, args.output_dir)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "forecast_rows": report["outputs"]["forecast_rows"],
                "diagnostics_rows": report["outputs"]["diagnostics_rows"],
                "comparison_rows": report["outputs"]["comparison_rows"],
                "candidate_models": report["outputs"]["candidate_models"],
                "primary_baseline_model": report["outputs"]["primary_baseline_model"],
            },
            ensure_ascii=False,
        )
    )
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
