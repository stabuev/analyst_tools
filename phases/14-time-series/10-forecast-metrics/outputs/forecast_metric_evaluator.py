from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any


REQUIRED_SPEC_FIELDS = {
    "metric_evaluation_id",
    "forecast_id",
    "backtest_id",
    "target_metric",
    "target_segments",
    "primary_baseline_model",
    "candidate_model_ids",
    "required_metrics",
    "primary_metric",
    "seasonal_period_days",
    "segment_weights",
    "horizon_weighting",
    "percentage_metric_policy",
    "leaderboard_policy",
}
REQUIRED_ERROR_COLUMNS = {
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
}
REQUIRED_SPLIT_COLUMNS = {
    "split_id",
    "training_start",
    "training_end",
}
REQUIRED_SOURCE_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "frequency",
    "value",
    "is_complete_period",
    "include_in_backtest",
}
REQUIRED_METRICS = ["mae", "rmse", "mape", "smape", "wape", "mase"]


class ForecastMetricError(ValueError):
    """Raised when forecast metric inputs cannot be interpreted."""


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
        raise ForecastMetricError(f"{path.name} must contain a JSON object")
    return value


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ForecastMetricError(f"{field} must be ISO date: {value}") from error


def parse_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ForecastMetricError(f"{field} must be numeric: {value}") from error


def parse_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ForecastMetricError(f"{field} must be an integer: {value}")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise ForecastMetricError(f"{field} must be an integer: {value}") from error


def parse_bool(value: str | bool, field: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ForecastMetricError(f"{field} must be true or false: {value}")
    return normalized == "true"


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


def mean(values: list[float]) -> float:
    if not values:
        raise ForecastMetricError("mean requires at least one value")
    return sum(values) / len(values)


def normalize_spec_and_report(spec: dict[str, Any], backtest_report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing_spec:
        checks.append(failed("forecast_metric_spec_required_fields", missing_spec, "all forecast metric spec fields"))
        return checks, None
    checks.append(passed("forecast_metric_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))

    if backtest_report.get("valid") is not True:
        checks.append(failed("backtest_report_is_valid", backtest_report.get("valid"), True))
    else:
        checks.append(passed("backtest_report_is_valid", True))

    align_errors: list[str] = []
    if spec["forecast_id"] != backtest_report.get("forecast_id"):
        align_errors.append("forecast_id")
    if spec["backtest_id"] != backtest_report.get("backtest_id"):
        align_errors.append("backtest_id")
    report_outputs = backtest_report.get("outputs", {})
    if sorted(spec["target_segments"]) != sorted(report_outputs.get("segments", [])):
        align_errors.append("target_segments")
    expected_models = [spec["primary_baseline_model"], *spec["candidate_model_ids"]]
    if expected_models != report_outputs.get("models"):
        align_errors.append("model_ids")
    if align_errors:
        checks.append(failed("metric_spec_and_backtest_align", sorted(set(align_errors)), "spec and backtest report agree"))
    else:
        checks.append(passed("metric_spec_and_backtest_align", "forecast, backtest, segments, and models aligned"))

    required_metrics = spec.get("required_metrics")
    if required_metrics != REQUIRED_METRICS:
        checks.append(failed("required_metrics_declared", required_metrics, REQUIRED_METRICS))
    else:
        checks.append(passed("required_metrics_declared", required_metrics))
    if spec.get("primary_metric") in {"mape", "smape"}:
        checks.append(failed("percentage_metrics_not_primary_decision_metric", spec.get("primary_metric"), "non-percentage primary metric"))
    else:
        checks.append(passed("percentage_metrics_not_primary_decision_metric", spec.get("primary_metric")))

    segment_weights = spec.get("segment_weights")
    segments = spec.get("target_segments")
    if not isinstance(segment_weights, dict) or not isinstance(segments, list):
        checks.append(failed("segment_weights_cover_targets_and_sum_to_one", segment_weights, "weights for every target segment"))
        return checks, None
    try:
        weights = {str(segment): parse_float(weight, f"segment_weights.{segment}") for segment, weight in segment_weights.items()}
        weight_sum = sum(weights.values())
    except ForecastMetricError as error:
        checks.append(failed("segment_weights_cover_targets_and_sum_to_one", str(error), "numeric weights"))
        return checks, None
    if set(weights) != set(segments) or not math.isclose(weight_sum, 1.0, abs_tol=0.000001):
        checks.append(failed("segment_weights_cover_targets_and_sum_to_one", {"segments": sorted(weights), "sum": weight_sum}, "target segments and sum=1"))
    else:
        checks.append(passed("segment_weights_cover_targets_and_sum_to_one", weights))

    horizon_policy = spec.get("horizon_weighting", {})
    required_horizon_steps = horizon_policy.get("required_horizon_steps")
    if not isinstance(required_horizon_steps, list) or not required_horizon_steps:
        checks.append(failed("horizon_steps_match_policy", required_horizon_steps, "non-empty required horizon steps"))
        return checks, None
    try:
        horizon_steps = [parse_int(step, "horizon_weighting.required_horizon_steps") for step in required_horizon_steps]
        seasonal_period_days = parse_int(spec["seasonal_period_days"], "seasonal_period_days")
        minimum_abs_actual = parse_float(
            spec["percentage_metric_policy"]["minimum_abs_actual_for_mape"],
            "percentage_metric_policy.minimum_abs_actual_for_mape",
        )
        minimum_smape_denominator = parse_float(
            spec["percentage_metric_policy"]["minimum_abs_actual_plus_forecast_for_smape"],
            "percentage_metric_policy.minimum_abs_actual_plus_forecast_for_smape",
        )
        improvement_threshold = parse_float(
            spec["leaderboard_policy"]["candidate_must_beat_baseline_by_relative"],
            "leaderboard_policy.candidate_must_beat_baseline_by_relative",
        )
    except (ForecastMetricError, KeyError) as error:
        checks.append(failed("forecast_metric_spec_values_parse", str(error), "valid numeric metric policy settings"))
        return checks, None
    checks.append(passed("forecast_metric_spec_values_parse", spec["metric_evaluation_id"]))

    backtest_warning_ids = list(backtest_report.get("summary", {}).get("warnings", []))
    if backtest_warning_ids:
        checks.append(
            failed(
                "backtest_warnings_limit_model_selection",
                backtest_warning_ids,
                "no upstream warnings for production model selection",
                severity="warning",
            )
        )
    else:
        checks.append(passed("backtest_warnings_limit_model_selection", []))

    if has_blocking_errors(checks):
        return checks, None
    return checks, {
        "segments": list(segments),
        "model_ids": expected_models,
        "candidate_model_ids": list(spec["candidate_model_ids"]),
        "segment_weights": weights,
        "horizon_steps": horizon_steps,
        "seasonal_period_days": seasonal_period_days,
        "minimum_abs_actual": minimum_abs_actual,
        "minimum_smape_denominator": minimum_smape_denominator,
        "improvement_threshold": improvement_threshold,
        "backtest_warning_ids": backtest_warning_ids,
        "expected_error_rows": report_outputs.get("error_rows"),
    }


def parse_error_rows(
    rows: list[dict[str, str]],
    fields: list[str],
    spec: dict[str, Any],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_ERROR_COLUMNS - set(fields))
    if missing:
        checks.append(failed("backtest_errors_required_columns", missing, "required backtest error columns"))
        return checks, None
    checks.append(passed("backtest_errors_required_columns", len(fields)))
    parsed_rows: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    for row in rows:
        try:
            parsed_rows.append(
                {
                    "backtest_id": row["backtest_id"],
                    "forecast_id": row["forecast_id"],
                    "split_id": row["split_id"],
                    "window_type": row["window_type"],
                    "metric_id": row["metric_id"],
                    "segment_id": row["segment_id"],
                    "model_id": row["model_id"],
                    "model_role": row["model_role"],
                    "family": row["family"],
                    "forecast_date": parse_date(row["forecast_date"], "forecast_date"),
                    "horizon_step": parse_int(row["horizon_step"], "horizon_step"),
                    "forecast_value": parse_float(row["forecast_value"], "forecast_value"),
                    "actual_value": parse_float(row["actual_value"], "actual_value"),
                    "error": parse_float(row["error"], "error"),
                    "absolute_error": parse_float(row["absolute_error"], "absolute_error"),
                    "squared_error": parse_float(row["squared_error"], "squared_error"),
                }
            )
        except ForecastMetricError as error:
            parse_errors.append({"split_id": row.get("split_id", ""), "model_id": row.get("model_id", ""), "error": str(error)})
    if parse_errors:
        checks.append(failed("backtest_errors_parse", len(parse_errors), "all error rows parse", parse_errors[:5]))
        return checks, None
    checks.append(passed("backtest_errors_parse", len(parsed_rows)))

    target_rows = [
        row
        for row in parsed_rows
        if row["backtest_id"] == spec["backtest_id"]
        and row["forecast_id"] == spec["forecast_id"]
        and row["metric_id"] == spec["target_metric"]
        and row["segment_id"] in context["segments"]
        and row["model_id"] in context["model_ids"]
    ]
    expected_error_rows = context.get("expected_error_rows")
    if expected_error_rows is not None and len(target_rows) != expected_error_rows:
        checks.append(failed("backtest_error_rows_match_report", len(target_rows), expected_error_rows))
    else:
        checks.append(passed("backtest_error_rows_match_report", len(target_rows)))

    keys = [
        (row["split_id"], row["metric_id"], row["segment_id"], row["model_id"], row["forecast_date"])
        for row in target_rows
    ]
    duplicate_keys = [key for key, count in Counter(keys).items() if count > 1]
    if duplicate_keys:
        checks.append(failed("backtest_error_grain_unique", len(duplicate_keys), "unique split/segment/model/date errors"))
    else:
        checks.append(passed("backtest_error_grain_unique", len(target_rows)))

    observed_horizon_steps = sorted({row["horizon_step"] for row in target_rows})
    if observed_horizon_steps != context["horizon_steps"]:
        checks.append(failed("horizon_steps_match_policy", observed_horizon_steps, context["horizon_steps"]))
    else:
        checks.append(passed("horizon_steps_match_policy", observed_horizon_steps))
    if has_blocking_errors(checks):
        return checks, None
    return checks, target_rows


def parse_split_rows(rows: list[dict[str, str]], fields: list[str]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]] | None]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPLIT_COLUMNS - set(fields))
    if missing:
        checks.append(failed("split_manifest_required_columns", missing, "split manifest training columns"))
        return checks, None
    splits: dict[str, dict[str, Any]] = {}
    parse_errors: list[dict[str, str]] = []
    for row in rows:
        try:
            splits[row["split_id"]] = {
                "split_id": row["split_id"],
                "training_start": parse_date(row["training_start"], "training_start"),
                "training_end": parse_date(row["training_end"], "training_end"),
            }
        except ForecastMetricError as error:
            parse_errors.append({"split_id": row.get("split_id", ""), "error": str(error)})
    if parse_errors:
        checks.append(failed("split_manifest_parse", len(parse_errors), "all split manifest rows parse", parse_errors[:5]))
        return checks, None
    checks.append(passed("split_manifest_parse", len(splits)))
    return checks, splits


def parse_source_series(
    rows: list[dict[str, str]],
    fields: list[str],
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[tuple[str, date], float] | None]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SOURCE_COLUMNS - set(fields))
    if missing:
        checks.append(failed("history_series_required_columns", missing, "history series columns"))
        return checks, None
    by_key: dict[tuple[str, date], float] = {}
    duplicate_keys: list[str] = []
    parse_errors: list[dict[str, str]] = []
    for row in rows:
        try:
            if row["metric_id"] != spec["target_metric"] or row["segment_id"] not in spec["target_segments"]:
                continue
            if row["frequency"] != "D" or not parse_bool(row["is_complete_period"], "is_complete_period") or not parse_bool(row["include_in_backtest"], "include_in_backtest"):
                continue
            key = (row["segment_id"], parse_date(row["observed_date"], "observed_date"))
            if key in by_key:
                duplicate_keys.append(f"{key[0]}:{key[1].isoformat()}")
            by_key[key] = parse_float(row["value"], "value")
        except ForecastMetricError as error:
            parse_errors.append({"date": row.get("observed_date", ""), "error": str(error)})
    if parse_errors:
        checks.append(failed("history_series_parse", len(parse_errors), "all history rows parse", parse_errors[:5]))
        return checks, None
    if duplicate_keys:
        checks.append(failed("history_series_grain_unique", duplicate_keys[:5], "unique segment/date history"))
    else:
        checks.append(passed("history_series_grain_unique", len(by_key)))
    if has_blocking_errors(checks):
        return checks, None
    return checks, by_key


def build_mase_denominators(
    spec: dict[str, Any],
    context: dict[str, Any],
    splits_by_id: dict[str, dict[str, Any]],
    series_by_key: dict[tuple[str, date], float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str], float] | None]:
    checks: list[dict[str, Any]] = []
    denominator_rows: list[dict[str, Any]] = []
    denominators: dict[tuple[str, str], float] = {}
    denominator_errors: list[str] = []
    seasonal_period_days = context["seasonal_period_days"]
    for split in splits_by_id.values():
        for segment in context["segments"]:
            diffs: list[float] = []
            for day in daterange(split["training_start"], split["training_end"]):
                previous = day - timedelta(days=seasonal_period_days)
                if previous < split["training_start"]:
                    continue
                key = (segment, day)
                previous_key = (segment, previous)
                if key not in series_by_key or previous_key not in series_by_key:
                    denominator_errors.append(f"{split['split_id']}:{segment}:{day.isoformat()}")
                    continue
                diffs.append(abs(series_by_key[key] - series_by_key[previous_key]))
            denominator = mean(diffs) if diffs else 0.0
            denominators[(split["split_id"], segment)] = denominator
            denominator_rows.append(
                {
                    "metric_evaluation_id": spec["metric_evaluation_id"],
                    "backtest_id": spec["backtest_id"],
                    "split_id": split["split_id"],
                    "segment_id": segment,
                    "training_start": split["training_start"].isoformat(),
                    "training_end": split["training_end"].isoformat(),
                    "seasonal_period_days": seasonal_period_days,
                    "scale_type": "seasonal_naive_in_sample_mae",
                    "denominator_rows": len(diffs),
                    "mase_denominator": format_number(denominator),
                }
            )
            if denominator <= 0:
                denominator_errors.append(f"{split['split_id']}:{segment}:non_positive")
    if denominator_errors:
        checks.append(failed("mase_denominator_positive", len(denominator_errors), "positive MASE denominator for every split and segment", denominator_errors[:10]))
    else:
        checks.append(passed("mase_denominator_positive", len(denominator_rows)))
    if has_blocking_errors(checks):
        return checks, denominator_rows, None
    return checks, denominator_rows, denominators


def attach_mase_denominators(
    rows: list[dict[str, Any]],
    denominators: dict[tuple[str, str], float],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    missing: list[str] = []
    for row in rows:
        key = (row["split_id"], row["segment_id"])
        if key not in denominators:
            missing.append(f"{key[0]}:{key[1]}")
            continue
        row["mase_denominator"] = denominators[key]
        row["scaled_absolute_error"] = row["absolute_error"] / denominators[key]
    if missing:
        checks.append(failed("mase_denominator_attached_to_every_error", sorted(set(missing)), "every error row has a scale"))
    else:
        checks.append(passed("mase_denominator_attached_to_every_error", len(rows)))
    return checks, rows


def metric_values_for_group(
    rows: list[dict[str, Any]],
    context: dict[str, Any],
) -> dict[str, Any]:
    absolute_errors = [row["absolute_error"] for row in rows]
    squared_errors = [row["squared_error"] for row in rows]
    actual_values = [row["actual_value"] for row in rows]
    forecast_values = [row["forecast_value"] for row in rows]
    mape_blocked = any(abs(actual) < context["minimum_abs_actual"] for actual in actual_values)
    smape_blocked = any(
        abs(actual) + abs(forecast) < context["minimum_smape_denominator"]
        for actual, forecast in zip(actual_values, forecast_values, strict=True)
    )
    wape_denominator = sum(abs(actual) for actual in actual_values)
    return {
        "n_errors": len(rows),
        "mae": mean(absolute_errors),
        "rmse": math.sqrt(mean(squared_errors)),
        "mape": None if mape_blocked else mean([absolute / abs(actual) * 100 for absolute, actual in zip(absolute_errors, actual_values, strict=True)]),
        "smape": None
        if smape_blocked
        else mean(
            [
                2 * absolute / (abs(actual) + abs(forecast)) * 100
                for absolute, actual, forecast in zip(absolute_errors, actual_values, forecast_values, strict=True)
            ]
        ),
        "wape": None if wape_denominator == 0 else sum(absolute_errors) / wape_denominator * 100,
        "mase": mean([row["scaled_absolute_error"] for row in rows]),
        "mape_status": "blocked" if mape_blocked else "reported",
        "smape_status": "blocked" if smape_blocked else "reported",
    }


def metric_row(
    *,
    spec: dict[str, Any],
    aggregation_level: str,
    target_metric: str,
    segment_id: str,
    horizon_step: str,
    model_row: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "metric_evaluation_id": spec["metric_evaluation_id"],
        "forecast_id": spec["forecast_id"],
        "backtest_id": spec["backtest_id"],
        "aggregation_level": aggregation_level,
        "target_metric": target_metric,
        "segment_id": segment_id,
        "horizon_step": horizon_step,
        "model_id": model_row["model_id"],
        "model_role": model_row["model_role"],
        "family": model_row["family"],
        "n_errors": metrics["n_errors"],
        "mae": format_number(metrics["mae"]),
        "rmse": format_number(metrics["rmse"]),
        "mape": format_number(metrics["mape"]),
        "smape": format_number(metrics["smape"]),
        "wape": format_number(metrics["wape"]),
        "mase": format_number(metrics["mase"]),
        "mape_status": metrics["mape_status"],
        "smape_status": metrics["smape_status"],
    }


def build_metric_rows(spec: dict[str, Any], context: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_model_segment: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_model_horizon: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_model[row["model_id"]].append(row)
        by_model_segment[(row["model_id"], row["segment_id"])].append(row)
        by_model_horizon[(row["model_id"], row["horizon_step"])].append(row)

    first_row_by_model = {model_id: model_rows[0] for model_id, model_rows in by_model.items()}
    for model_id in context["model_ids"]:
        model_rows = by_model.get(model_id, [])
        if model_rows:
            metric_rows.append(
                metric_row(
                    spec=spec,
                    aggregation_level="overall",
                    target_metric=spec["target_metric"],
                    segment_id="*",
                    horizon_step="*",
                    model_row=first_row_by_model[model_id],
                    metrics=metric_values_for_group(model_rows, context),
                )
            )
        for segment in context["segments"]:
            group = by_model_segment.get((model_id, segment), [])
            if group:
                metric_rows.append(
                    metric_row(
                        spec=spec,
                        aggregation_level="segment",
                        target_metric=spec["target_metric"],
                        segment_id=segment,
                        horizon_step="*",
                        model_row=first_row_by_model[model_id],
                        metrics=metric_values_for_group(group, context),
                    )
                )
        for horizon_step in context["horizon_steps"]:
            group = by_model_horizon.get((model_id, horizon_step), [])
            if group:
                metric_rows.append(
                    metric_row(
                        spec=spec,
                        aggregation_level="horizon",
                        target_metric=spec["target_metric"],
                        segment_id="*",
                        horizon_step=str(horizon_step),
                        model_row=first_row_by_model[model_id],
                        metrics=metric_values_for_group(group, context),
                    )
                )

    expected_rows = len(context["model_ids"]) * (1 + len(context["segments"]) + len(context["horizon_steps"]))
    observed_levels = sorted({row["aggregation_level"] for row in metric_rows})
    if len(metric_rows) != expected_rows or observed_levels != ["horizon", "overall", "segment"]:
        checks.append(failed("metric_table_contains_overall_segment_and_horizon_rows", {"rows": len(metric_rows), "levels": observed_levels}, expected_rows))
    else:
        checks.append(passed("metric_table_contains_overall_segment_and_horizon_rows", len(metric_rows)))
    return checks, metric_rows


def build_suitability_rows(spec: dict[str, Any], context: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    actual_values = [row["actual_value"] for row in rows]
    forecast_values = [row["forecast_value"] for row in rows]
    min_actual = min(abs(value) for value in actual_values)
    zero_actual_count = sum(1 for value in actual_values if value == 0)
    small_actual_count = sum(1 for value in actual_values if abs(value) < context["minimum_abs_actual"])
    smape_small_count = sum(
        1
        for actual, forecast in zip(actual_values, forecast_values, strict=True)
        if abs(actual) + abs(forecast) < context["minimum_smape_denominator"]
    )
    percentage_blocked = small_actual_count > 0 or smape_small_count > 0
    rows_out: list[dict[str, Any]] = []
    definitions = [
        ("mae", "support", "false", "scale_sensitive", "absolute error in target units", "allowed", "easy to explain but not scale-comparable across segments"),
        ("rmse", "support", "false", "outlier_sensitive", "squared error in target units", "allowed", "penalizes large misses and complements MAE"),
        ("mape", "diagnostic_only", "true", "zero_sensitive", "absolute actual value", "blocked" if small_actual_count else "diagnostic_only", "blocked by zero/small actuals" if small_actual_count else "percentage metric is not the decision metric"),
        ("smape", "diagnostic_only", "true", "zero_sensitive", "actual plus forecast magnitude", "blocked" if smape_small_count else "diagnostic_only", "blocked by zero/small actual+forecast denominators" if smape_small_count else "bounded percentage diagnostic, still not primary"),
        ("wape", "support", "false", "volume_weighted", "sum absolute actual value", "allowed", "useful business-volume normalized aggregate"),
        ("mase", "primary", "true", "scale_denominator_sensitive", "in-sample seasonal naive MAE", "allowed", "scale-comparable and aligned with the seasonal baseline policy"),
    ]
    for metric_name, decision_role, scale_comparable, sensitivity, denominator_basis, status, reason in definitions:
        rows_out.append(
            {
                "metric_evaluation_id": spec["metric_evaluation_id"],
                "metric_name": metric_name,
                "decision_role": decision_role,
                "lower_is_better": "true",
                "scale_comparable": scale_comparable,
                "zero_or_scale_sensitive": sensitivity,
                "denominator_basis": denominator_basis,
                "observed_min_actual": format_number(min_actual),
                "observed_zero_actual_count": zero_actual_count,
                "observed_small_actual_count": small_actual_count,
                "status": status,
                "reason": reason,
            }
        )
    if percentage_blocked:
        checks.append(
            failed(
                "percentage_denominators_are_safe_or_blocked",
                {"small_actual_count": small_actual_count, "small_smape_count": smape_small_count},
                "percentage metrics blocked when denominators are unsafe",
                severity="warning",
            )
        )
    else:
        checks.append(passed("percentage_denominators_are_safe_or_blocked", "percentage metrics reported as diagnostic-only"))
    return checks, rows_out


def build_leaderboard_rows(
    spec: dict[str, Any],
    context: dict[str, Any],
    metric_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    segment_mase: dict[tuple[str, str], float] = {}
    model_roles: dict[str, str] = {}
    for row in metric_rows:
        if row["aggregation_level"] == "segment":
            segment_mase[(row["model_id"], row["segment_id"])] = parse_float(row["mase"], "mase")
            model_roles[row["model_id"]] = row["model_role"]
    weighted_scores: dict[str, float] = {}
    for model_id in context["model_ids"]:
        weighted_scores[model_id] = sum(
            context["segment_weights"][segment] * segment_mase[(model_id, segment)]
            for segment in context["segments"]
        )
    baseline_id = spec["primary_baseline_model"]
    baseline_score = weighted_scores[baseline_id]
    ranked_model_ids = sorted(context["model_ids"], key=lambda model_id: (weighted_scores[model_id], model_id))
    rows_out: list[dict[str, Any]] = []
    for rank, model_id in enumerate(ranked_model_ids, start=1):
        score = weighted_scores[model_id]
        relative_improvement = 0.0 if model_id == baseline_id else (baseline_score - score) / baseline_score
        clears_threshold = model_id != baseline_id and relative_improvement >= context["improvement_threshold"]
        all_segments_clear = model_id != baseline_id and all(
            segment_mase[(model_id, segment)] < segment_mase[(baseline_id, segment)] * (1 - context["improvement_threshold"])
            for segment in context["segments"]
        )
        eligible = clears_threshold and all_segments_clear and not context["backtest_warning_ids"]
        if model_id == baseline_id:
            decision_status = "primary_baseline"
        elif clears_threshold and all_segments_clear and context["backtest_warning_ids"]:
            decision_status = spec["leaderboard_policy"]["tiny_profile_decision_status"]
        elif eligible:
            decision_status = "candidate_clears_policy"
        else:
            decision_status = "does_not_clear_baseline_policy"
        rows_out.append(
            {
                "metric_evaluation_id": spec["metric_evaluation_id"],
                "forecast_id": spec["forecast_id"],
                "backtest_id": spec["backtest_id"],
                "rank": rank,
                "model_id": model_id,
                "model_role": model_roles.get(model_id, "candidate"),
                "primary_metric": spec["primary_metric"],
                "primary_metric_value": format_number(score),
                "baseline_metric_value": format_number(baseline_score),
                "relative_improvement_vs_baseline": format_number(relative_improvement),
                "clears_baseline_threshold": str(clears_threshold).lower(),
                "all_segments_clear_baseline": str(all_segments_clear).lower(),
                "eligible_for_model_selection": str(eligible).lower(),
                "decision_status": decision_status,
                "warning_ids": ";".join(context["backtest_warning_ids"]),
            }
        )

    if baseline_id not in weighted_scores or len(rows_out) != len(context["model_ids"]):
        checks.append(failed("leaderboard_uses_primary_metric_and_baseline", len(rows_out), len(context["model_ids"])))
    else:
        checks.append(passed("leaderboard_uses_primary_metric_and_baseline", baseline_id))
    if context["backtest_warning_ids"] and any(row["eligible_for_model_selection"] == "true" for row in rows_out):
        checks.append(
            failed(
                "leaderboard_policy_blocks_selection_when_backtest_warnings_exist",
                "eligible model despite upstream warnings",
                "no eligible model selection while backtest has warning limitations",
            )
        )
    else:
        checks.append(passed("leaderboard_policy_blocks_selection_when_backtest_warnings_exist", context["backtest_warning_ids"]))
    return checks, rows_out


def empty_report(spec: dict[str, Any] | None, checks: list[dict[str, Any]]) -> dict[str, Any]:
    warning_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "warning")
    error_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "error")
    return {
        "audit_id": "forecast-metric-evaluation-report",
        "metric_evaluation_id": spec.get("metric_evaluation_id") if spec else None,
        "forecast_id": spec.get("forecast_id") if spec else None,
        "backtest_id": spec.get("backtest_id") if spec else None,
        "valid": error_count == 0,
        "warning_count": warning_count,
        "error_count": error_count,
        "checks": checks,
        "outputs": {
            "metric_rows": 0,
            "leaderboard_rows": 0,
            "suitability_rows": 0,
            "mase_denominator_rows": 0,
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
    metric_rows: list[dict[str, Any]],
    leaderboard_rows: list[dict[str, Any]],
    suitability_rows: list[dict[str, Any]],
    denominator_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    warning_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "warning")
    error_count = sum(1 for check in checks if not check["valid"] and check["severity"] == "error")
    top_row = min(leaderboard_rows, key=lambda row: row["rank"]) if leaderboard_rows else {}
    return {
        "audit_id": "forecast-metric-evaluation-report",
        "metric_evaluation_id": spec["metric_evaluation_id"],
        "forecast_id": spec["forecast_id"],
        "backtest_id": spec["backtest_id"],
        "valid": error_count == 0,
        "warning_count": warning_count,
        "error_count": error_count,
        "checks": checks,
        "outputs": {
            "metric_rows": len(metric_rows),
            "leaderboard_rows": len(leaderboard_rows),
            "suitability_rows": len(suitability_rows),
            "mase_denominator_rows": len(denominator_rows),
            "primary_metric": spec["primary_metric"],
            "top_model_id": top_row.get("model_id"),
            "top_model_decision_status": top_row.get("decision_status"),
        },
        "leaderboard_policy": spec["leaderboard_policy"],
        "summary": {
            "checks_total": len(checks),
            "checks_failed": warning_count + error_count,
            "blocking_errors": [check["id"] for check in checks if not check["valid"] and check["severity"] == "error"],
            "warnings": [check["id"] for check in checks if not check["valid"] and check["severity"] == "warning"],
        },
    }


def build_forecast_metric_package(
    *,
    errors_path: Path,
    split_manifest_path: Path,
    series_path: Path,
    backtest_report_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    spec = read_json(spec_path)
    backtest_report = read_json(backtest_report_path)
    checks, context = normalize_spec_and_report(spec, backtest_report)
    if context is None:
        return {
            "metric_rows": [],
            "leaderboard_rows": [],
            "suitability_rows": [],
            "denominator_rows": [],
            "report": empty_report(spec, checks),
        }

    error_rows_raw, error_fields = read_csv(errors_path)
    error_checks, error_rows = parse_error_rows(error_rows_raw, error_fields, spec, context)
    checks.extend(error_checks)
    split_rows_raw, split_fields = read_csv(split_manifest_path)
    split_checks, splits_by_id = parse_split_rows(split_rows_raw, split_fields)
    checks.extend(split_checks)
    source_rows_raw, source_fields = read_csv(series_path)
    source_checks, series_by_key = parse_source_series(source_rows_raw, source_fields, spec)
    checks.extend(source_checks)
    if has_blocking_errors(checks) or error_rows is None or splits_by_id is None or series_by_key is None:
        return {
            "metric_rows": [],
            "leaderboard_rows": [],
            "suitability_rows": [],
            "denominator_rows": [],
            "report": empty_report(spec, checks),
        }

    denominator_checks, denominator_rows, denominators = build_mase_denominators(spec, context, splits_by_id, series_by_key)
    checks.extend(denominator_checks)
    if has_blocking_errors(checks) or denominators is None:
        return {
            "metric_rows": [],
            "leaderboard_rows": [],
            "suitability_rows": [],
            "denominator_rows": denominator_rows,
            "report": empty_report(spec, checks),
        }
    attach_checks, scaled_error_rows = attach_mase_denominators(error_rows, denominators)
    checks.extend(attach_checks)
    if has_blocking_errors(checks):
        return {
            "metric_rows": [],
            "leaderboard_rows": [],
            "suitability_rows": [],
            "denominator_rows": denominator_rows,
            "report": empty_report(spec, checks),
        }

    metric_checks, metric_rows = build_metric_rows(spec, context, scaled_error_rows)
    checks.extend(metric_checks)
    suitability_checks, suitability_rows = build_suitability_rows(spec, context, scaled_error_rows)
    checks.extend(suitability_checks)
    leaderboard_checks, leaderboard_rows = build_leaderboard_rows(spec, context, metric_rows)
    checks.extend(leaderboard_checks)
    report = build_report(spec, checks, metric_rows, leaderboard_rows, suitability_rows, denominator_rows)
    return {
        "metric_rows": metric_rows,
        "leaderboard_rows": leaderboard_rows,
        "suitability_rows": suitability_rows,
        "denominator_rows": denominator_rows,
        "report": report,
    }


def write_package(package: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "forecast_metrics.csv",
        package["metric_rows"],
        [
            "metric_evaluation_id",
            "forecast_id",
            "backtest_id",
            "aggregation_level",
            "target_metric",
            "segment_id",
            "horizon_step",
            "model_id",
            "model_role",
            "family",
            "n_errors",
            "mae",
            "rmse",
            "mape",
            "smape",
            "wape",
            "mase",
            "mape_status",
            "smape_status",
        ],
    )
    write_csv(
        output_dir / "metric_suitability_audit.csv",
        package["suitability_rows"],
        [
            "metric_evaluation_id",
            "metric_name",
            "decision_role",
            "lower_is_better",
            "scale_comparable",
            "zero_or_scale_sensitive",
            "denominator_basis",
            "observed_min_actual",
            "observed_zero_actual_count",
            "observed_small_actual_count",
            "status",
            "reason",
        ],
    )
    write_csv(
        output_dir / "metric_leaderboard.csv",
        package["leaderboard_rows"],
        [
            "metric_evaluation_id",
            "forecast_id",
            "backtest_id",
            "rank",
            "model_id",
            "model_role",
            "primary_metric",
            "primary_metric_value",
            "baseline_metric_value",
            "relative_improvement_vs_baseline",
            "clears_baseline_threshold",
            "all_segments_clear_baseline",
            "eligible_for_model_selection",
            "decision_status",
            "warning_ids",
        ],
    )
    write_csv(
        output_dir / "mase_denominators.csv",
        package["denominator_rows"],
        [
            "metric_evaluation_id",
            "backtest_id",
            "split_id",
            "segment_id",
            "training_start",
            "training_end",
            "seasonal_period_days",
            "scale_type",
            "denominator_rows",
            "mase_denominator",
        ],
    )
    (output_dir / "metric_report.json").write_text(
        json.dumps(package["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate rolling-origin forecast metrics and leaderboard policy.")
    parser.add_argument("--errors", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--backtest-report", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    package = build_forecast_metric_package(
        errors_path=args.errors,
        split_manifest_path=args.split_manifest,
        series_path=args.series,
        backtest_report_path=args.backtest_report,
        spec_path=args.spec,
    )
    write_package(package, args.output_dir)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "metric_rows": report["outputs"]["metric_rows"],
                "leaderboard_rows": report["outputs"]["leaderboard_rows"],
                "primary_metric": report["outputs"].get("primary_metric"),
                "top_model_id": report["outputs"].get("top_model_id"),
                "top_model_decision_status": report["outputs"].get("top_model_decision_status"),
            },
            ensure_ascii=False,
        )
    )
    if not report["valid"] or (args.fail_on_warning and report["warning_count"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
