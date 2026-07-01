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
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.holtwinters import ExponentialSmoothing


REQUIRED_SERIES_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "frequency",
    "value",
    "is_complete_period",
    "include_in_backtest",
}
REQUIRED_SCENARIO_FIELDS = {
    "forecast_id",
    "target_metric",
    "target_segments",
    "timezone",
    "frequency",
    "forecast_origin",
    "horizon_days",
}
REQUIRED_MODEL_REPORT_FIELDS = {"model_run_id", "forecast_id", "valid", "outputs", "summary"}
REQUIRED_MODEL_SPEC_FIELDS = {"model_run_id", "forecast_id", "target_metric", "target_segments", "candidate_models"}
REQUIRED_BACKTEST_SPEC_FIELDS = {
    "backtest_id",
    "forecast_id",
    "source_table",
    "upstream_model_run_id",
    "baseline_id",
    "target_metric",
    "target_segments",
    "time_column",
    "value_column",
    "timezone",
    "frequency",
    "seasonal_period_days",
    "primary_baseline_model",
    "candidate_model_ids",
    "baseline_model_ids",
    "final_forecast_horizon_days",
    "backtest_horizon_days",
    "gap_days",
    "minimum_origins_for_model_selection",
    "retraining_policy",
    "split_plan",
}
REQUIRED_SPLIT_FIELDS = {
    "split_id",
    "window_type",
    "forecast_origin",
    "training_start",
    "training_end",
    "embargo_dates",
    "first_forecast_date",
    "horizon_end",
}


class BacktestingError(ValueError):
    """Raised when backtest inputs cannot be interpreted."""


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
        raise BacktestingError(f"{path.name} must contain a JSON object")
    return value


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise BacktestingError(f"{field} must be ISO date: {value}") from error


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BacktestingError(f"{field} must be ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BacktestingError(f"{field} must be timezone-aware: {value}")
    return parsed


def parse_bool(value: str | bool, field: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise BacktestingError(f"{field} must be true or false: {value}")
    return normalized == "true"


def parse_number(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise BacktestingError(f"{field} must be numeric: {value}") from error


def parse_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise BacktestingError(f"{field} must be an integer: {value}")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise BacktestingError(f"{field} must be an integer: {value}") from error


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


def convergence_status(result: Any) -> str:
    retvals = getattr(result, "mle_retvals", None)
    if retvals is None:
        return "not_reported"
    if isinstance(retvals, dict):
        converged = retvals.get("converged", retvals.get("success"))
    else:
        converged = getattr(retvals, "converged", getattr(retvals, "success", None))
    if converged is True:
        return "converged"
    if converged is False:
        return "not_converged"
    return "not_reported"


def order_label(model: dict[str, Any], key: str) -> str:
    value = model.get(key)
    if value is None:
        return ""
    return ",".join(str(item) for item in value)


def normalize_model_definitions(
    model_spec: dict[str, Any],
    candidate_model_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    candidate_models = model_spec.get("candidate_models")
    if not isinstance(candidate_models, list):
        checks.append(failed("candidate_models_available_from_model_spec", candidate_models, "candidate model list"))
        return checks, []
    by_id = {str(model.get("model_id")): model for model in candidate_models if isinstance(model, dict)}
    missing = [model_id for model_id in candidate_model_ids if model_id not in by_id]
    if missing:
        checks.append(failed("candidate_models_available_from_model_spec", missing, "all candidate ids resolve"))
        return checks, []
    checks.append(passed("candidate_models_available_from_model_spec", candidate_model_ids))
    return checks, [dict(by_id[model_id]) for model_id in candidate_model_ids]


def parse_split(raw_split: dict[str, Any], backtest_horizon_days: int, gap_days: int) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPLIT_FIELDS - set(raw_split))
    if missing:
        return [failed("split_required_fields", missing, "all split fields")], None
    try:
        split = {
            "split_id": str(raw_split["split_id"]),
            "window_type": str(raw_split["window_type"]),
            "forecast_origin": parse_timestamp(str(raw_split["forecast_origin"]), "forecast_origin"),
            "training_start": parse_date(str(raw_split["training_start"]), "training_start"),
            "training_end": parse_date(str(raw_split["training_end"]), "training_end"),
            "first_forecast_date": parse_date(str(raw_split["first_forecast_date"]), "first_forecast_date"),
            "horizon_end": parse_date(str(raw_split["horizon_end"]), "horizon_end"),
            "embargo_dates": [parse_date(str(item), "embargo_dates") for item in raw_split["embargo_dates"]],
        }
    except (BacktestingError, TypeError) as error:
        return [failed("split_values_parse", str(error), "valid split dates and timestamp")], None

    if split["window_type"] not in {"expanding", "rolling"}:
        checks.append(failed("no_random_splits", split["window_type"], "expanding or rolling"))
    horizon_dates = daterange(split["first_forecast_date"], split["horizon_end"])
    if len(horizon_dates) != backtest_horizon_days:
        checks.append(failed("forecast_horizon_is_fixed", len(horizon_dates), backtest_horizon_days, [split["split_id"]]))
    expected_embargo = daterange(
        split["training_end"] + timedelta(days=1),
        split["first_forecast_date"] - timedelta(days=1),
    )
    if split["embargo_dates"] != expected_embargo or len(expected_embargo) != gap_days:
        checks.append(
            failed(
                "embargo_gap_is_respected",
                [day.isoformat() for day in split["embargo_dates"]],
                [day.isoformat() for day in expected_embargo],
                [split["split_id"]],
            )
        )
    if not (split["training_start"] <= split["training_end"] < split["first_forecast_date"] <= split["horizon_end"]):
        checks.append(
            failed(
                "training_windows_precede_origins",
                {
                    "split_id": split["split_id"],
                    "training_start": split["training_start"].isoformat(),
                    "training_end": split["training_end"].isoformat(),
                    "first_forecast_date": split["first_forecast_date"].isoformat(),
                    "horizon_end": split["horizon_end"].isoformat(),
                },
                "training_start <= training_end < first_forecast_date <= horizon_end",
            )
        )
    split["horizon_dates"] = horizon_dates
    split["training_points"] = len(daterange(split["training_start"], split["training_end"]))
    return checks, split


def normalize_inputs(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    model_spec: dict[str, Any],
    model_report: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_BACKTEST_SPEC_FIELDS - set(spec))
    missing_scenario = sorted(REQUIRED_SCENARIO_FIELDS - set(scenario))
    missing_model_spec = sorted(REQUIRED_MODEL_SPEC_FIELDS - set(model_spec))
    missing_model_report = sorted(REQUIRED_MODEL_REPORT_FIELDS - set(model_report))
    if missing_spec:
        checks.append(failed("backtesting_spec_required_fields", missing_spec, "all required backtesting fields"))
        return checks, None
    checks.append(passed("backtesting_spec_required_fields", len(REQUIRED_BACKTEST_SPEC_FIELDS)))
    if missing_scenario:
        checks.append(failed("scenario_required_fields", missing_scenario, "all required scenario fields"))
        return checks, None
    checks.append(passed("scenario_required_fields", len(REQUIRED_SCENARIO_FIELDS)))
    if missing_model_spec:
        checks.append(failed("model_spec_required_fields", missing_model_spec, "all required model spec fields"))
        return checks, None
    checks.append(passed("model_spec_required_fields", len(REQUIRED_MODEL_SPEC_FIELDS)))
    if missing_model_report:
        checks.append(failed("model_report_required_fields", missing_model_report, "all required model report fields"))
        return checks, None
    checks.append(passed("model_report_required_fields", len(REQUIRED_MODEL_REPORT_FIELDS)))

    try:
        timezone = ZoneInfo(str(spec["timezone"]))
        seasonal_period_days = parse_int(spec["seasonal_period_days"], "seasonal_period_days")
        final_forecast_horizon_days = parse_int(spec["final_forecast_horizon_days"], "final_forecast_horizon_days")
        backtest_horizon_days = parse_int(spec["backtest_horizon_days"], "backtest_horizon_days")
        gap_days = parse_int(spec["gap_days"], "gap_days")
        minimum_origins_for_model_selection = parse_int(
            spec["minimum_origins_for_model_selection"],
            "minimum_origins_for_model_selection",
        )
    except (ZoneInfoNotFoundError, BacktestingError) as error:
        checks.append(failed("backtesting_spec_values_parse", str(error), "valid timezone and numeric settings"))
        return checks, None
    checks.append(passed("backtesting_spec_values_parse", spec["backtest_id"]))

    align_errors: list[str] = []
    if spec["forecast_id"] != scenario["forecast_id"] or spec["forecast_id"] != model_spec["forecast_id"]:
        align_errors.append("forecast_id")
    if spec["target_metric"] != scenario["target_metric"] or spec["target_metric"] != model_spec["target_metric"]:
        align_errors.append("target_metric")
    if spec["target_segments"] != scenario["target_segments"] or spec["target_segments"] != model_spec["target_segments"]:
        align_errors.append("target_segments")
    if spec["timezone"] != scenario["timezone"]:
        align_errors.append("timezone")
    if spec["frequency"] != scenario["frequency"]:
        align_errors.append("frequency")
    if spec["upstream_model_run_id"] != model_spec["model_run_id"] or spec["upstream_model_run_id"] != model_report["model_run_id"]:
        align_errors.append("upstream_model_run_id")
    if model_report.get("valid") is not True:
        align_errors.append("model_report_valid")
    if final_forecast_horizon_days != parse_int(scenario["horizon_days"], "scenario.horizon_days"):
        align_errors.append("final_forecast_horizon_days")
    if align_errors:
        checks.append(failed("scenario_model_and_backtest_spec_align", sorted(set(align_errors)), "scenario, model run, and backtest spec agree"))
    else:
        checks.append(passed("scenario_model_and_backtest_spec_align", "all setup ids and scenario values aligned"))

    segments = spec.get("target_segments")
    candidate_model_ids = spec.get("candidate_model_ids")
    baseline_model_ids = spec.get("baseline_model_ids")
    if not isinstance(segments, list) or not segments:
        checks.append(failed("target_segments_declared", segments, "non-empty segment list"))
        return checks, None
    checks.append(passed("target_segments_declared", segments))
    if not isinstance(candidate_model_ids, list) or not all(isinstance(item, str) for item in candidate_model_ids):
        checks.append(failed("candidate_model_ids_declared", candidate_model_ids, "candidate model id list"))
        return checks, None
    checks.append(passed("candidate_model_ids_declared", candidate_model_ids))
    if baseline_model_ids != [spec["primary_baseline_model"]]:
        checks.append(failed("baseline_model_ids_declared", baseline_model_ids, [spec["primary_baseline_model"]]))
    else:
        checks.append(passed("baseline_model_ids_declared", baseline_model_ids))

    retraining_policy = spec.get("retraining_policy")
    if not (
        isinstance(retraining_policy, dict)
        and retraining_policy.get("refit_each_origin") is True
        and retraining_policy.get("reuse_final_forecast_fit") is False
    ):
        checks.append(failed("models_refit_each_origin", retraining_policy, "refit each origin and do not reuse final fit"))
    else:
        checks.append(passed("models_refit_each_origin", "refit_each_origin"))

    split_plan = spec.get("split_plan")
    if not isinstance(split_plan, list) or not split_plan:
        checks.append(failed("split_plan_declared", split_plan, "non-empty split plan"))
        return checks, None
    parsed_splits: list[dict[str, Any]] = []
    split_errors: list[dict[str, Any]] = []
    for raw_split in split_plan:
        if not isinstance(raw_split, dict):
            split_errors.append({"split": raw_split, "error": "split must be an object"})
            continue
        split_checks, parsed = parse_split(raw_split, backtest_horizon_days, gap_days)
        for check in split_checks:
            if not check["valid"]:
                checks.append(check)
                split_errors.append({"split_id": raw_split.get("split_id", ""), "check": check})
        if parsed is not None:
            parsed_splits.append(parsed)
    if split_errors:
        checks.append(failed("split_plan_valid", split_errors, "all splits parse and pass split-level gates"))
    else:
        checks.append(passed("split_plan_valid", len(parsed_splits)))

    split_ids = [split["split_id"] for split in parsed_splits]
    duplicate_split_ids = [split_id for split_id, count in Counter(split_ids).items() if count > 1]
    if duplicate_split_ids:
        checks.append(failed("split_ids_unique", duplicate_split_ids, "unique split ids"))
    else:
        checks.append(passed("split_ids_unique", split_ids))
    ordered_origins = [split["forecast_origin"] for split in parsed_splits]
    if ordered_origins != sorted(ordered_origins):
        checks.append(failed("origins_are_time_ordered", [item.isoformat() for item in ordered_origins], "ascending origins"))
    else:
        checks.append(passed("origins_are_time_ordered", [item.isoformat() for item in ordered_origins]))
    window_types = {split["window_type"] for split in parsed_splits}
    if window_types != {"expanding", "rolling"}:
        checks.append(failed("backtest_includes_expanding_and_rolling_windows", sorted(window_types), ["expanding", "rolling"]))
    else:
        checks.append(passed("backtest_includes_expanding_and_rolling_windows", sorted(window_types)))
    if len(parsed_splits) < minimum_origins_for_model_selection:
        checks.append(
            failed(
                "small_origin_count_blocks_model_selection_claim",
                len(parsed_splits),
                minimum_origins_for_model_selection,
                severity="warning",
            )
        )
    else:
        checks.append(passed("small_origin_count_blocks_model_selection_claim", len(parsed_splits)))
    if backtest_horizon_days < final_forecast_horizon_days:
        checks.append(
            failed(
                "backtest_horizon_shorter_than_final_forecast_horizon",
                backtest_horizon_days,
                final_forecast_horizon_days,
                severity="warning",
            )
        )
    else:
        checks.append(passed("backtest_horizon_shorter_than_final_forecast_horizon", backtest_horizon_days))

    model_checks, candidate_models = normalize_model_definitions(model_spec, candidate_model_ids)
    checks.extend(model_checks)
    if has_blocking_errors(checks):
        return checks, None
    context = {
        "timezone": timezone,
        "segments": segments,
        "candidate_models": candidate_models,
        "model_ids": [spec["primary_baseline_model"], *candidate_model_ids],
        "seasonal_period_days": seasonal_period_days,
        "backtest_horizon_days": backtest_horizon_days,
        "final_forecast_horizon_days": final_forecast_horizon_days,
        "splits": parsed_splits,
    }
    return checks, context


def parse_source_series(
    rows: list[dict[str, str]],
    fields: list[str],
    spec: dict[str, Any],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[tuple[str, date], dict[str, Any]] | None]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SERIES_COLUMNS - set(fields))
    if missing:
        checks.append(failed("series_columns_present", missing, "required backtest series columns"))
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
                    "is_complete_period": parse_bool(row["is_complete_period"], "is_complete_period"),
                    "include_in_backtest": parse_bool(row["include_in_backtest"], "include_in_backtest"),
                }
            )
        except BacktestingError as error:
            parse_errors.append({"date": row.get("observed_date", ""), "error": str(error)})
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
                "one row per metric, segment, and historical date",
                [":".join((key[0], key[1], key[2].isoformat())) for key in duplicate_keys[:5]],
            )
        )
    else:
        checks.append(passed("source_segment_date_unique", len(target_rows)))

    invalid_rows = [
        {"segment_id": row["segment_id"], "observed_date": row["observed_date"].isoformat()}
        for row in target_rows
        if row["frequency"] != spec["frequency"] or not row["is_complete_period"] or not row["include_in_backtest"]
    ]
    if invalid_rows:
        checks.append(failed("backtest_rows_are_complete_and_eligible", len(invalid_rows), "all target rows complete and eligible", invalid_rows[:5]))
    else:
        checks.append(passed("backtest_rows_are_complete_and_eligible", len(target_rows)))

    by_key = {(row["segment_id"], row["observed_date"]): row for row in target_rows}
    missing_samples: list[str] = []
    for split in context["splits"]:
        required_dates = daterange(split["training_start"], split["training_end"]) + split["horizon_dates"]
        for segment in context["segments"]:
            for day in required_dates:
                if (segment, day) not in by_key:
                    missing_samples.append(f"{split['split_id']}:{segment}:{day.isoformat()}")
    if missing_samples:
        checks.append(failed("actuals_available_for_every_origin_horizon", len(missing_samples), "all training and horizon dates available", missing_samples[:10]))
    else:
        checks.append(passed("actuals_available_for_every_origin_horizon", "all split training and horizon dates"))
    if has_blocking_errors(checks):
        return checks, None
    return checks, by_key


def fit_candidate_model(series: pd.Series, model: dict[str, Any], raw_steps_requested: int) -> dict[str, Any]:
    captured_warnings: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        family = model["family"]
        if family == "ETS":
            result = ExponentialSmoothing(
                series,
                trend=model.get("trend") or None,
                damped_trend=bool(model.get("damped_trend", False)),
                seasonal=model.get("seasonal") or None,
                seasonal_periods=parse_int(model.get("seasonal_periods"), f"{model['model_id']}.seasonal_periods"),
                initialization_method=str(model.get("initialization_method", "estimated")),
            ).fit(optimized=True, remove_bias=False)
        elif family == "ARIMA":
            result = ARIMA(
                series,
                order=tuple(model["order"]),
                seasonal_order=tuple(model["seasonal_order"]),
                trend=str(model.get("trend", "n")),
                enforce_stationarity=bool(model.get("enforce_stationarity", False)),
                enforce_invertibility=bool(model.get("enforce_invertibility", False)),
            ).fit()
        else:
            raise BacktestingError(f"unsupported candidate family: {family}")
        forecast = result.forecast(steps=raw_steps_requested)
        for warning in caught:
            captured_warnings.append(f"{warning.category.__name__}: {warning.message}")
    return {
        "forecast_values": [float(value) for value in forecast],
        "convergence_status": convergence_status(result),
        "warning_count": len(captured_warnings),
        "warnings": " | ".join(captured_warnings),
        "aic": getattr(result, "aic", None),
        "bic": getattr(result, "bic", None),
    }


def seasonal_naive_forecast(training_rows: list[dict[str, Any]], forecast_dates: list[date], seasonal_period_days: int) -> dict[date, tuple[float, date]]:
    values_by_date = {row["observed_date"]: row["value"] for row in training_rows}
    output: dict[date, tuple[float, date]] = {}
    for forecast_date in forecast_dates:
        anchor_date = forecast_date - timedelta(days=seasonal_period_days)
        if anchor_date not in values_by_date:
            raise BacktestingError(f"seasonal naive anchor is missing for {forecast_date.isoformat()}: {anchor_date.isoformat()}")
        output[forecast_date] = (values_by_date[anchor_date], anchor_date)
    return output


def split_manifest_rows(spec: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, split in enumerate(context["splits"], start=1):
        rows.append(
            {
                "backtest_id": spec["backtest_id"],
                "split_id": split["split_id"],
                "origin_index": index,
                "window_type": split["window_type"],
                "forecast_origin": split["forecast_origin"].isoformat(),
                "training_start": split["training_start"].isoformat(),
                "training_end": split["training_end"].isoformat(),
                "training_points": split["training_points"],
                "embargo_dates": ";".join(day.isoformat() for day in split["embargo_dates"]),
                "first_forecast_date": split["first_forecast_date"].isoformat(),
                "horizon_end": split["horizon_end"].isoformat(),
                "horizon_days": len(split["horizon_dates"]),
                "retraining_policy": "refit_each_origin",
            }
        )
    return rows


def build_forecasts(
    spec: dict[str, Any],
    context: dict[str, Any],
    series_by_key: dict[tuple[str, date], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    forecast_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    fit_errors: list[dict[str, str]] = []
    warning_samples: list[dict[str, Any]] = []

    for split in context["splits"]:
        raw_steps_requested = (split["horizon_end"] - split["training_end"]).days
        for segment in context["segments"]:
            training_dates = daterange(split["training_start"], split["training_end"])
            training_rows = [series_by_key[(segment, day)] for day in training_dates]
            index = pd.DatetimeIndex([pd.Timestamp(row["observed_date"].isoformat()) for row in training_rows])
            training_series = pd.Series([row["value"] for row in training_rows], index=index, dtype="float64").asfreq(spec["frequency"])
            if training_series.isna().any():
                fit_errors.append({"split_id": split["split_id"], "segment_id": segment, "model_id": "*", "error": "training series has missing dates"})
                continue

            try:
                baseline_forecast = seasonal_naive_forecast(training_rows, split["horizon_dates"], context["seasonal_period_days"])
            except BacktestingError as error:
                fit_errors.append({"split_id": split["split_id"], "segment_id": segment, "model_id": spec["primary_baseline_model"], "error": str(error)})
                continue
            for horizon_step, forecast_date in enumerate(split["horizon_dates"], start=1):
                forecast_value, anchor_date = baseline_forecast[forecast_date]
                actual_value = series_by_key[(segment, forecast_date)]["value"]
                forecast_row = {
                    "backtest_id": spec["backtest_id"],
                    "forecast_id": spec["forecast_id"],
                    "split_id": split["split_id"],
                    "window_type": split["window_type"],
                    "metric_id": spec["target_metric"],
                    "segment_id": segment,
                    "model_id": spec["primary_baseline_model"],
                    "model_role": "primary_baseline",
                    "family": "Baseline",
                    "forecast_date": forecast_date.isoformat(),
                    "horizon_step": horizon_step,
                    "forecast_value": format_number(forecast_value),
                    "training_start": split["training_start"].isoformat(),
                    "training_end": split["training_end"].isoformat(),
                    "raw_step": (forecast_date - split["training_end"]).days,
                    "anchor_dates": anchor_date.isoformat(),
                    "fit_status": "fit",
                    "convergence_status": "not_applicable",
                    "statsmodels_warning_count": 0,
                    "statsmodels_warnings": "",
                }
                forecast_rows.append(forecast_row)
                error_rows.append(error_row_from_forecast(forecast_row, actual_value))

            for model in context["candidate_models"]:
                try:
                    fit_result = fit_candidate_model(training_series, model, raw_steps_requested)
                except Exception as error:  # noqa: BLE001 - report fit failure as backtest diagnostics.
                    fit_errors.append({"split_id": split["split_id"], "segment_id": segment, "model_id": model["model_id"], "error": str(error)})
                    continue
                if fit_result["warning_count"]:
                    warning_samples.append(
                        {
                            "split_id": split["split_id"],
                            "segment_id": segment,
                            "model_id": model["model_id"],
                            "warnings": fit_result["warnings"],
                        }
                    )
                for raw_step, forecast_value in enumerate(fit_result["forecast_values"], start=1):
                    forecast_date = split["training_end"] + timedelta(days=raw_step)
                    if forecast_date not in split["horizon_dates"]:
                        continue
                    horizon_step = (forecast_date - split["first_forecast_date"]).days + 1
                    actual_value = series_by_key[(segment, forecast_date)]["value"]
                    forecast_row = {
                        "backtest_id": spec["backtest_id"],
                        "forecast_id": spec["forecast_id"],
                        "split_id": split["split_id"],
                        "window_type": split["window_type"],
                        "metric_id": spec["target_metric"],
                        "segment_id": segment,
                        "model_id": model["model_id"],
                        "model_role": "candidate",
                        "family": model["family"],
                        "forecast_date": forecast_date.isoformat(),
                        "horizon_step": horizon_step,
                        "forecast_value": format_number(forecast_value),
                        "training_start": split["training_start"].isoformat(),
                        "training_end": split["training_end"].isoformat(),
                        "raw_step": raw_step,
                        "anchor_dates": "",
                        "fit_status": "fit",
                        "convergence_status": fit_result["convergence_status"],
                        "statsmodels_warning_count": fit_result["warning_count"],
                        "statsmodels_warnings": fit_result["warnings"],
                    }
                    forecast_rows.append(forecast_row)
                    error_rows.append(error_row_from_forecast(forecast_row, actual_value))

    if fit_errors:
        checks.append(failed("all_models_fit_each_origin", fit_errors, "all baseline and candidate models fit"))
    else:
        checks.append(passed("all_models_fit_each_origin", "all models fit"))
    if warning_samples:
        checks.append(failed("statsmodels_warnings_propagated", warning_samples, "warnings captured in forecast rows", severity="warning"))
    else:
        checks.append(passed("statsmodels_warnings_propagated", 0))

    expected_rows = len(context["splits"]) * len(context["segments"]) * len(context["model_ids"]) * context["backtest_horizon_days"]
    if len(forecast_rows) != expected_rows:
        checks.append(failed("forecast_table_has_full_horizon", len(forecast_rows), expected_rows))
    else:
        checks.append(passed("forecast_table_has_full_horizon", len(forecast_rows)))
    keys = [
        (row["split_id"], row["metric_id"], row["segment_id"], row["model_id"], row["forecast_date"])
        for row in forecast_rows
    ]
    duplicate_keys = [key for key, count in Counter(keys).items() if count > 1]
    if duplicate_keys:
        checks.append(failed("one_forecast_per_origin_segment_model_date", len(duplicate_keys), "unique backtest forecast grain"))
    else:
        checks.append(passed("one_forecast_per_origin_segment_model_date", len(forecast_rows)))
    if len(error_rows) != len(forecast_rows):
        checks.append(failed("raw_errors_emitted_for_every_forecast", len(error_rows), len(forecast_rows)))
    else:
        checks.append(passed("raw_errors_emitted_for_every_forecast", len(error_rows)))
    return checks, forecast_rows, error_rows


def error_row_from_forecast(forecast_row: dict[str, Any], actual_value: float) -> dict[str, Any]:
    forecast_value = float(forecast_row["forecast_value"])
    error = actual_value - forecast_value
    return {
        "backtest_id": forecast_row["backtest_id"],
        "forecast_id": forecast_row["forecast_id"],
        "split_id": forecast_row["split_id"],
        "window_type": forecast_row["window_type"],
        "metric_id": forecast_row["metric_id"],
        "segment_id": forecast_row["segment_id"],
        "model_id": forecast_row["model_id"],
        "model_role": forecast_row["model_role"],
        "family": forecast_row["family"],
        "forecast_date": forecast_row["forecast_date"],
        "horizon_step": forecast_row["horizon_step"],
        "forecast_value": forecast_row["forecast_value"],
        "actual_value": format_number(actual_value),
        "error": format_number(error),
        "absolute_error": format_number(abs(error)),
        "squared_error": format_number(error * error),
    }


def empty_report(spec: dict[str, Any] | None, checks: list[dict[str, Any]]) -> dict[str, Any]:
    warning_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "warning")
    error_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "error")
    return {
        "audit_id": "rolling-origin-backtest-report",
        "backtest_id": spec.get("backtest_id") if spec else None,
        "forecast_id": spec.get("forecast_id") if spec else None,
        "valid": error_count == 0,
        "warning_count": warning_count,
        "error_count": error_count,
        "checks": checks,
        "outputs": {
            "split_rows": 0,
            "forecast_rows": 0,
            "error_rows": 0,
            "origins": 0,
            "models": [],
        },
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
    split_rows: list[dict[str, Any]],
    forecast_rows: list[dict[str, Any]],
    error_rows: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    warning_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "warning")
    error_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "error")
    return {
        "audit_id": "rolling-origin-backtest-report",
        "backtest_id": spec["backtest_id"],
        "forecast_id": spec["forecast_id"],
        "valid": error_count == 0,
        "warning_count": warning_count,
        "error_count": error_count,
        "checks": checks,
        "outputs": {
            "split_rows": len(split_rows),
            "forecast_rows": len(forecast_rows),
            "error_rows": len(error_rows),
            "origins": len(context["splits"]),
            "segments": context["segments"],
            "models": context["model_ids"],
            "backtest_horizon_days": context["backtest_horizon_days"],
            "final_forecast_horizon_days": context["final_forecast_horizon_days"],
        },
        "retraining_policy": spec["retraining_policy"],
        "summary": {
            "checks_total": len(checks),
            "checks_failed": warning_count + error_count,
            "blocking_errors": [check["id"] for check in checks if not check["valid"] and check["severity"] == "error"],
            "warnings": [check["id"] for check in checks if not check["valid"] and check["severity"] == "warning"],
        },
    }


def build_backtest_package(
    *,
    series_path: Path,
    scenario_path: Path,
    model_spec_path: Path,
    model_report_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    spec = read_json(spec_path)
    scenario = read_json(scenario_path)
    model_spec = read_json(model_spec_path)
    model_report = read_json(model_report_path)
    checks, context = normalize_inputs(spec, scenario, model_spec, model_report)
    if context is None:
        return {"split_rows": [], "forecast_rows": [], "error_rows": [], "report": empty_report(spec, checks)}
    source_rows, source_fields = read_csv(series_path)
    source_checks, series_by_key = parse_source_series(source_rows, source_fields, spec, context)
    checks.extend(source_checks)
    if has_blocking_errors(checks) or series_by_key is None:
        return {"split_rows": [], "forecast_rows": [], "error_rows": [], "report": empty_report(spec, checks)}
    split_rows = split_manifest_rows(spec, context)
    forecast_checks, forecast_rows, error_rows = build_forecasts(spec, context, series_by_key)
    checks.extend(forecast_checks)
    report = build_report(spec, checks, split_rows, forecast_rows, error_rows, context)
    return {"split_rows": split_rows, "forecast_rows": forecast_rows, "error_rows": error_rows, "report": report}


def write_package(package: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "split_manifest.csv",
        package["split_rows"],
        [
            "backtest_id",
            "split_id",
            "origin_index",
            "window_type",
            "forecast_origin",
            "training_start",
            "training_end",
            "training_points",
            "embargo_dates",
            "first_forecast_date",
            "horizon_end",
            "horizon_days",
            "retraining_policy",
        ],
    )
    write_csv(
        output_dir / "backtest_forecasts.csv",
        package["forecast_rows"],
        [
            "backtest_id",
            "forecast_id",
            "split_id",
            "window_type",
            "metric_id",
            "segment_id",
            "model_id",
            "model_role",
            "family",
            "forecast_date",
            "horizon_step",
            "forecast_value",
            "training_start",
            "training_end",
            "raw_step",
            "anchor_dates",
            "fit_status",
            "convergence_status",
            "statsmodels_warning_count",
            "statsmodels_warnings",
        ],
    )
    write_csv(
        output_dir / "backtest_errors.csv",
        package["error_rows"],
        [
            "backtest_id",
            "forecast_id",
            "split_id",
            "window_type",
            "metric_id",
            "segment_id",
            "model_id",
            "model_role",
            "family",
            "forecast_date",
            "horizon_step",
            "forecast_value",
            "actual_value",
            "error",
            "absolute_error",
            "squared_error",
        ],
    )
    (output_dir / "backtest_report.json").write_text(
        json.dumps(package["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run predeclared rolling-origin backtests for time-series candidates.")
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--model-spec", type=Path, required=True)
    parser.add_argument("--model-report", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    package = build_backtest_package(
        series_path=args.series,
        scenario_path=args.scenario,
        model_spec_path=args.model_spec,
        model_report_path=args.model_report,
        spec_path=args.spec,
    )
    write_package(package, args.output_dir)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "split_rows": report["outputs"]["split_rows"],
                "forecast_rows": report["outputs"]["forecast_rows"],
                "error_rows": report["outputs"]["error_rows"],
                "models": report["outputs"]["models"],
            },
            ensure_ascii=False,
        )
    )
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
