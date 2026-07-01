from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from statistics import NormalDist
from typing import Any


REQUIRED_SPEC_FIELDS = {
    "interval_calibration_id",
    "forecast_id",
    "backtest_id",
    "metric_evaluation_id",
    "model_run_id",
    "baseline_id",
    "target_metric",
    "target_segments",
    "interval_model_ids",
    "primary_interval_method",
    "coverage_target",
    "alpha",
    "minimum_backtest_rows_per_group",
    "minimum_origins_for_coverage_claim",
    "calibration_grain",
    "horizon_policy",
    "methods",
    "interval_policy",
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
}
REQUIRED_FINAL_FORECAST_COLUMNS = {
    "forecast_id",
    "metric_id",
    "segment_id",
    "model_id",
    "forecast_date",
    "horizon_step",
    "forecast_value",
}
REQUIRED_METHODS = ["residual_quantile", "residual_bootstrap", "model_based_normal"]


class PredictionIntervalError(ValueError):
    """Raised when prediction interval inputs cannot be interpreted."""


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
        raise PredictionIntervalError(f"{path.name} must contain a JSON object")
    return value


def parse_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise PredictionIntervalError(f"{field} must be numeric: {value}") from error


def parse_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise PredictionIntervalError(f"{field} must be an integer: {value}")
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise PredictionIntervalError(f"{field} must be an integer: {value}") from error


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


def format_bool(value: bool) -> str:
    return "true" if value else "false"


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


def empirical_quantile(values: list[float], probability: float, *, conservative: str) -> float:
    if not values:
        raise PredictionIntervalError("quantile requires at least one value")
    if not 0 <= probability <= 1:
        raise PredictionIntervalError(f"quantile probability must be in [0, 1]: {probability}")
    ordered = sorted(values)
    n = len(ordered)
    if conservative == "lower":
        index = math.floor(probability * n)
    elif conservative == "upper":
        index = math.ceil(probability * n) - 1
    else:
        raise PredictionIntervalError(f"unknown conservative quantile side: {conservative}")
    return ordered[max(0, min(n - 1, index))]


def normalize_spec_and_reports(
    spec: dict[str, Any],
    backtest_report: dict[str, Any],
    metric_report: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing_spec:
        checks.append(failed("prediction_interval_spec_required_fields", missing_spec, "all prediction interval spec fields"))
        return checks, None
    checks.append(passed("prediction_interval_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))

    if backtest_report.get("valid") is not True:
        checks.append(failed("backtest_report_is_valid", backtest_report.get("valid"), True))
    else:
        checks.append(passed("backtest_report_is_valid", True))
    if metric_report.get("valid") is not True:
        checks.append(failed("metric_report_is_valid", metric_report.get("valid"), True))
    else:
        checks.append(passed("metric_report_is_valid", True))

    align_errors: list[str] = []
    if spec["forecast_id"] != backtest_report.get("forecast_id") or spec["forecast_id"] != metric_report.get("forecast_id"):
        align_errors.append("forecast_id")
    if spec["backtest_id"] != backtest_report.get("backtest_id") or spec["backtest_id"] != metric_report.get("backtest_id"):
        align_errors.append("backtest_id")
    if spec["metric_evaluation_id"] != metric_report.get("metric_evaluation_id"):
        align_errors.append("metric_evaluation_id")
    backtest_outputs = backtest_report.get("outputs", {})
    if sorted(spec["target_segments"]) != sorted(backtest_outputs.get("segments", [])):
        align_errors.append("target_segments")
    if spec["interval_model_ids"] != backtest_outputs.get("models"):
        align_errors.append("interval_model_ids")
    if align_errors:
        checks.append(failed("interval_spec_and_reports_align", sorted(set(align_errors)), "spec, backtest report and metric report agree"))
    else:
        checks.append(passed("interval_spec_and_reports_align", "forecast, backtest, metric, segments and models aligned"))

    try:
        coverage_target = parse_float(spec["coverage_target"], "coverage_target")
        alpha = parse_float(spec["alpha"], "alpha")
        minimum_rows = parse_int(spec["minimum_backtest_rows_per_group"], "minimum_backtest_rows_per_group")
        minimum_origins = parse_int(spec["minimum_origins_for_coverage_claim"], "minimum_origins_for_coverage_claim")
        final_horizon = parse_int(spec["horizon_policy"]["final_forecast_horizon_days"], "horizon_policy.final_forecast_horizon_days")
        calibrated_horizons = [
            parse_int(step, "horizon_policy.calibrated_horizon_steps")
            for step in spec["horizon_policy"]["calibrated_horizon_steps"]
        ]
        lower_bound_floor = parse_float(spec["interval_policy"].get("lower_bound_floor", 0.0), "interval_policy.lower_bound_floor")
    except (KeyError, PredictionIntervalError) as error:
        checks.append(failed("prediction_interval_spec_values_parse", str(error), "valid numeric interval policy settings"))
        return checks, None
    if not 0 < coverage_target < 1 or not 0 < alpha < 1:
        checks.append(failed("prediction_interval_spec_values_parse", {"coverage_target": coverage_target, "alpha": alpha}, "probabilities in (0, 1)"))
    else:
        checks.append(passed("prediction_interval_spec_values_parse", spec["interval_calibration_id"]))

    methods = spec.get("methods")
    if not isinstance(methods, list):
        checks.append(failed("interval_methods_declared", methods, "list of interval method definitions"))
        return checks, None
    method_by_id = {str(method.get("method_id")): method for method in methods if isinstance(method, dict)}
    if list(method_by_id) != REQUIRED_METHODS or spec.get("primary_interval_method") not in method_by_id:
        checks.append(failed("interval_methods_declared", list(method_by_id), REQUIRED_METHODS))
    else:
        checks.append(passed("interval_methods_declared", list(method_by_id)))
    if spec["interval_policy"].get("prediction_interval_not_confidence_interval") is not True:
        checks.append(failed("prediction_interval_not_confidence_interval", spec["interval_policy"].get("prediction_interval_not_confidence_interval"), True))
    else:
        checks.append(passed("prediction_interval_not_confidence_interval", True))

    origins = backtest_outputs.get("origins")
    if origins is not None and origins < minimum_origins:
        checks.append(
            failed(
                "small_origin_count_blocks_interval_sla_claim",
                origins,
                minimum_origins,
                severity="warning",
            )
        )
    else:
        checks.append(passed("small_origin_count_blocks_interval_sla_claim", origins))
    if backtest_outputs.get("backtest_horizon_days") is not None and backtest_outputs.get("backtest_horizon_days") < final_horizon:
        checks.append(
            failed(
                "interval_horizon_shorter_than_final_forecast",
                backtest_outputs.get("backtest_horizon_days"),
                final_horizon,
                severity="warning",
            )
        )
    else:
        checks.append(passed("interval_horizon_shorter_than_final_forecast", final_horizon))
    backtest_warning_ids = list(backtest_report.get("summary", {}).get("warnings", []))
    metric_warning_ids = list(metric_report.get("summary", {}).get("warnings", []))
    if backtest_warning_ids or metric_warning_ids:
        checks.append(
            failed(
                "upstream_warnings_limit_interval_claim",
                {"backtest": backtest_warning_ids, "metric": metric_warning_ids},
                "no upstream warnings for production interval claims",
                severity="warning",
            )
        )
    else:
        checks.append(passed("upstream_warnings_limit_interval_claim", []))

    if has_blocking_errors(checks):
        return checks, None
    return checks, {
        "segments": list(spec["target_segments"]),
        "model_ids": list(spec["interval_model_ids"]),
        "coverage_target": coverage_target,
        "alpha": alpha,
        "minimum_rows": minimum_rows,
        "minimum_origins": minimum_origins,
        "calibrated_horizons": calibrated_horizons,
        "final_horizon": final_horizon,
        "max_calibrated_horizon": max(calibrated_horizons),
        "lower_bound_floor": lower_bound_floor,
        "method_by_id": method_by_id,
        "expected_error_rows": backtest_outputs.get("error_rows"),
        "backtest_warning_ids": backtest_warning_ids,
        "metric_warning_ids": metric_warning_ids,
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
                    "forecast_date": row["forecast_date"],
                    "horizon_step": parse_int(row["horizon_step"], "horizon_step"),
                    "forecast_value": parse_float(row["forecast_value"], "forecast_value"),
                    "actual_value": parse_float(row["actual_value"], "actual_value"),
                    "error": parse_float(row["error"], "error"),
                    "absolute_error": parse_float(row["absolute_error"], "absolute_error"),
                }
            )
        except PredictionIntervalError as error:
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

    observed_horizons = sorted({row["horizon_step"] for row in target_rows})
    if observed_horizons != context["calibrated_horizons"]:
        checks.append(failed("calibrated_horizon_steps_match_errors", observed_horizons, context["calibrated_horizons"]))
    else:
        checks.append(passed("calibrated_horizon_steps_match_errors", observed_horizons))
    if has_blocking_errors(checks):
        return checks, None
    return checks, target_rows


def parse_final_forecasts(
    baseline_rows: list[dict[str, str]],
    baseline_fields: list[str],
    candidate_rows: list[dict[str, str]],
    candidate_fields: list[str],
    spec: dict[str, Any],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    checks: list[dict[str, Any]] = []
    missing_baseline = sorted(REQUIRED_FINAL_FORECAST_COLUMNS - set(baseline_fields))
    missing_candidate = sorted(REQUIRED_FINAL_FORECAST_COLUMNS - set(candidate_fields))
    if missing_baseline or missing_candidate:
        checks.append(
            failed(
                "final_forecasts_required_columns",
                {"baseline_missing": missing_baseline, "candidate_missing": missing_candidate},
                "required final forecast columns",
            )
        )
        return checks, None
    checks.append(passed("final_forecasts_required_columns", "baseline and candidate forecast tables"))

    final_rows: list[dict[str, Any]] = []
    parse_errors: list[dict[str, str]] = []
    for source_name, rows in (("baseline", baseline_rows), ("candidate", candidate_rows)):
        for row in rows:
            if row.get("model_id") not in context["model_ids"]:
                continue
            if row.get("forecast_id") != spec["forecast_id"] or row.get("metric_id") != spec["target_metric"]:
                continue
            try:
                model_id = row["model_id"]
                model_role = "primary_baseline" if model_id == context["model_ids"][0] else "candidate"
                family = row.get("family") or ("Baseline" if model_role == "primary_baseline" else "Unknown")
                final_rows.append(
                    {
                        "forecast_id": row["forecast_id"],
                        "metric_id": row["metric_id"],
                        "segment_id": row["segment_id"],
                        "model_id": model_id,
                        "model_role": model_role,
                        "family": family,
                        "forecast_date": row["forecast_date"],
                        "horizon_step": parse_int(row["horizon_step"], "horizon_step"),
                        "forecast_value": parse_float(row["forecast_value"], "forecast_value"),
                        "source_table": source_name,
                    }
                )
            except PredictionIntervalError as error:
                parse_errors.append({"source": source_name, "model_id": row.get("model_id", ""), "error": str(error)})
    if parse_errors:
        checks.append(failed("final_forecasts_parse", len(parse_errors), "all final forecast rows parse", parse_errors[:5]))
        return checks, None
    checks.append(passed("final_forecasts_parse", len(final_rows)))

    keys = [(row["metric_id"], row["segment_id"], row["model_id"], row["forecast_date"]) for row in final_rows]
    duplicate_keys = [key for key, count in Counter(keys).items() if count > 1]
    if duplicate_keys:
        checks.append(failed("final_forecast_grain_unique", len(duplicate_keys), "unique metric/segment/model/date final forecasts"))
    else:
        checks.append(passed("final_forecast_grain_unique", len(final_rows)))

    expected_horizons = list(range(1, context["final_horizon"] + 1))
    missing_groups: list[str] = []
    for model_id in context["model_ids"]:
        for segment in context["segments"]:
            observed = sorted(
                row["horizon_step"]
                for row in final_rows
                if row["model_id"] == model_id and row["segment_id"] == segment
            )
            if observed != expected_horizons:
                missing_groups.append(f"{model_id}:{segment}:{observed[:5]}..{observed[-5:] if observed else []}")
    expected_rows = len(context["model_ids"]) * len(context["segments"]) * context["final_horizon"]
    if missing_groups or len(final_rows) != expected_rows:
        checks.append(failed("final_forecast_table_has_full_horizon", {"rows": len(final_rows), "groups": missing_groups[:5]}, expected_rows))
    else:
        checks.append(passed("final_forecast_table_has_full_horizon", len(final_rows)))
    if has_blocking_errors(checks):
        return checks, None
    return checks, sorted(final_rows, key=lambda row: (row["model_id"], row["segment_id"], row["horizon_step"]))


def calibration_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return row["model_id"], row["segment_id"], row["horizon_step"]


def build_calibration_params(
    spec: dict[str, Any],
    context: dict[str, Any],
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, str, int, str], dict[str, Any]] | None]:
    checks: list[dict[str, Any]] = []
    rows_by_group: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_group[calibration_key(row)].append(row)

    params: dict[tuple[str, str, int, str], dict[str, Any]] = {}
    audit_rows: list[dict[str, Any]] = []
    insufficient: list[str] = []
    z_value = NormalDist().inv_cdf(1 - context["alpha"] / 2)
    for model_id in context["model_ids"]:
        for segment in context["segments"]:
            for horizon_step in context["calibrated_horizons"]:
                group_key = (model_id, segment, horizon_step)
                group = rows_by_group.get(group_key, [])
                if len(group) < context["minimum_rows"]:
                    insufficient.append(f"{model_id}:{segment}:h{horizon_step}:{len(group)}")
                    continue
                errors = [row["error"] for row in group]
                absolute_errors = [row["absolute_error"] for row in group]
                residual_quantile = empirical_quantile(
                    absolute_errors,
                    context["method_by_id"]["residual_quantile"]["absolute_error_quantile"],
                    conservative="upper",
                )
                bootstrap_lower = empirical_quantile(
                    errors,
                    context["method_by_id"]["residual_bootstrap"]["lower_quantile"],
                    conservative="lower",
                )
                bootstrap_upper = empirical_quantile(
                    errors,
                    context["method_by_id"]["residual_bootstrap"]["upper_quantile"],
                    conservative="upper",
                )
                residual_stddev = statistics.stdev(errors) if len(errors) > 1 else 0.0
                residual_mean = statistics.mean(errors)
                method_params = {
                    "residual_quantile": {
                        "lower_residual": -residual_quantile,
                        "upper_residual": residual_quantile,
                        "half_width": residual_quantile,
                    },
                    "residual_bootstrap": {
                        "lower_residual": bootstrap_lower,
                        "upper_residual": bootstrap_upper,
                        "half_width": (bootstrap_upper - bootstrap_lower) / 2,
                    },
                    "model_based_normal": {
                        "lower_residual": -z_value * residual_stddev,
                        "upper_residual": z_value * residual_stddev,
                        "half_width": z_value * residual_stddev,
                    },
                }
                for method_id, values in method_params.items():
                    method = context["method_by_id"][method_id]
                    params[(model_id, segment, horizon_step, method_id)] = {
                        **values,
                        "method_id": method_id,
                        "decision_role": method["decision_role"],
                        "calibration_rows": len(group),
                        "residual_mean": residual_mean,
                        "residual_stddev": residual_stddev,
                        "z_value": z_value if method_id == "model_based_normal" else None,
                    }
                    audit_rows.append(
                        {
                            "interval_calibration_id": spec["interval_calibration_id"],
                            "forecast_id": spec["forecast_id"],
                            "backtest_id": spec["backtest_id"],
                            "model_id": model_id,
                            "segment_id": segment,
                            "horizon_step": horizon_step,
                            "method_id": method_id,
                            "decision_role": method["decision_role"],
                            "calibration_rows": len(group),
                            "coverage_target": format_number(context["coverage_target"]),
                            "alpha": format_number(context["alpha"]),
                            "residual_mean": format_number(residual_mean),
                            "residual_stddev": format_number(residual_stddev),
                            "lower_residual": format_number(values["lower_residual"]),
                            "upper_residual": format_number(values["upper_residual"]),
                            "interval_half_width": format_number(values["half_width"]),
                            "calibration_status": "calibrated",
                        }
                    )
    if insufficient:
        checks.append(
            failed(
                "calibration_groups_have_minimum_rows",
                insufficient[:10],
                f">={context['minimum_rows']} rows per model/segment/horizon",
            )
        )
    else:
        expected_groups = len(context["model_ids"]) * len(context["segments"]) * len(context["calibrated_horizons"])
        checks.append(passed("calibration_groups_have_minimum_rows", expected_groups))
    if has_blocking_errors(checks):
        return checks, audit_rows, None
    return checks, audit_rows, params


def interval_from_params(point_forecast: float, params: dict[str, Any], lower_bound_floor: float) -> tuple[float, float, float]:
    lower = max(lower_bound_floor, point_forecast + params["lower_residual"])
    upper = max(lower, point_forecast + params["upper_residual"])
    return lower, upper, upper - lower


def build_backtest_interval_rows(
    spec: dict[str, Any],
    context: dict[str, Any],
    rows: list[dict[str, Any]],
    params: dict[tuple[str, str, int, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    interval_rows: list[dict[str, Any]] = []
    for row in rows:
        for method_id in REQUIRED_METHODS:
            group_params = params[(row["model_id"], row["segment_id"], row["horizon_step"], method_id)]
            lower, upper, width = interval_from_params(row["forecast_value"], group_params, context["lower_bound_floor"])
            covered = lower <= row["actual_value"] <= upper
            interval_rows.append(
                {
                    "interval_calibration_id": spec["interval_calibration_id"],
                    "forecast_id": row["forecast_id"],
                    "backtest_id": row["backtest_id"],
                    "split_id": row["split_id"],
                    "window_type": row["window_type"],
                    "metric_id": row["metric_id"],
                    "segment_id": row["segment_id"],
                    "model_id": row["model_id"],
                    "model_role": row["model_role"],
                    "family": row["family"],
                    "forecast_date": row["forecast_date"],
                    "horizon_step": row["horizon_step"],
                    "method_id": method_id,
                    "decision_role": group_params["decision_role"],
                    "point_forecast": format_number(row["forecast_value"]),
                    "actual_value": format_number(row["actual_value"]),
                    "lower_bound": format_number(lower),
                    "upper_bound": format_number(upper),
                    "interval_width": format_number(width),
                    "covered": format_bool(covered),
                    "calibration_rows": group_params["calibration_rows"],
                    "calibration_horizon_step": row["horizon_step"],
                }
            )
    return interval_rows


def coverage_status(method_id: str, decision_role: str, coverage: float, target: float) -> str:
    if coverage >= target:
        if decision_role == "primary":
            return "meets_target"
        if decision_role == "comparison":
            return "comparison_meets_target"
        return "diagnostic_meets_target"
    if decision_role == "primary":
        return "below_target"
    if decision_role == "comparison":
        return "comparison_undercoverage"
    return "diagnostic_undercoverage"


def coverage_row(
    spec: dict[str, Any],
    context: dict[str, Any],
    *,
    aggregation_level: str,
    method_id: str,
    decision_role: str,
    model_id: str,
    segment_id: str,
    horizon_step: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    n_observations = len(rows)
    covered_count = sum(1 for row in rows if row["covered"] == "true")
    coverage = covered_count / n_observations if n_observations else 0.0
    return {
        "interval_calibration_id": spec["interval_calibration_id"],
        "forecast_id": spec["forecast_id"],
        "backtest_id": spec["backtest_id"],
        "aggregation_level": aggregation_level,
        "method_id": method_id,
        "decision_role": decision_role,
        "model_id": model_id,
        "segment_id": segment_id,
        "horizon_step": horizon_step,
        "n_observations": n_observations,
        "covered_count": covered_count,
        "empirical_coverage": format_number(coverage),
        "target_coverage": format_number(context["coverage_target"]),
        "coverage_gap": format_number(coverage - context["coverage_target"]),
        "coverage_status": coverage_status(method_id, decision_role, coverage, context["coverage_target"]),
    }


def build_coverage_rows(
    spec: dict[str, Any],
    context: dict[str, Any],
    interval_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    rows_by_model_method: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    rows_by_model_method_segment: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    rows_by_model_method_horizon: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    role_by_method = {method_id: context["method_by_id"][method_id]["decision_role"] for method_id in REQUIRED_METHODS}
    for row in interval_rows:
        rows_by_model_method[(row["method_id"], row["model_id"])].append(row)
        rows_by_model_method_segment[(row["method_id"], row["model_id"], row["segment_id"])].append(row)
        rows_by_model_method_horizon[(row["method_id"], row["model_id"], str(row["horizon_step"]))].append(row)

    coverage_rows: list[dict[str, Any]] = []
    for method_id in REQUIRED_METHODS:
        for model_id in context["model_ids"]:
            coverage_rows.append(
                coverage_row(
                    spec,
                    context,
                    aggregation_level="overall",
                    method_id=method_id,
                    decision_role=role_by_method[method_id],
                    model_id=model_id,
                    segment_id="*",
                    horizon_step="*",
                    rows=rows_by_model_method[(method_id, model_id)],
                )
            )
            for segment in context["segments"]:
                coverage_rows.append(
                    coverage_row(
                        spec,
                        context,
                        aggregation_level="segment",
                        method_id=method_id,
                        decision_role=role_by_method[method_id],
                        model_id=model_id,
                        segment_id=segment,
                        horizon_step="*",
                        rows=rows_by_model_method_segment[(method_id, model_id, segment)],
                    )
                )
            for horizon_step in context["calibrated_horizons"]:
                coverage_rows.append(
                    coverage_row(
                        spec,
                        context,
                        aggregation_level="horizon",
                        method_id=method_id,
                        decision_role=role_by_method[method_id],
                        model_id=model_id,
                        segment_id="*",
                        horizon_step=str(horizon_step),
                        rows=rows_by_model_method_horizon[(method_id, model_id, str(horizon_step))],
                    )
                )
    primary_method = spec["primary_interval_method"]
    primary_overall = [
        row
        for row in coverage_rows
        if row["method_id"] == primary_method and row["aggregation_level"] == "overall"
    ]
    primary_min = min(parse_float(row["empirical_coverage"], "empirical_coverage") for row in primary_overall)
    if primary_min < context["coverage_target"]:
        checks.append(failed("primary_interval_coverage_meets_target", primary_min, context["coverage_target"]))
    else:
        checks.append(passed("primary_interval_coverage_meets_target", format_number(primary_min)))

    diagnostic_undercoverage = [
        f"{row['method_id']}:{row['model_id']}:{row['aggregation_level']}:{row['segment_id']}:{row['horizon_step']}"
        for row in coverage_rows
        if row["method_id"] == "model_based_normal" and row["coverage_status"] == "diagnostic_undercoverage"
    ]
    if diagnostic_undercoverage:
        checks.append(
            failed(
                "diagnostic_model_based_undercoverage_is_warned",
                len(diagnostic_undercoverage),
                "model-based diagnostic intervals meet target or stay warning-only",
                diagnostic_undercoverage[:8],
                severity="warning",
            )
        )
    else:
        checks.append(passed("diagnostic_model_based_undercoverage_is_warned", "none"))
    return checks, coverage_rows


def build_final_interval_rows(
    spec: dict[str, Any],
    context: dict[str, Any],
    final_rows: list[dict[str, Any]],
    params: dict[tuple[str, str, int, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    interval_rows: list[dict[str, Any]] = []
    missing_params: list[str] = []
    for row in final_rows:
        calibration_horizon = min(row["horizon_step"], context["max_calibrated_horizon"])
        horizon_status = "exact" if calibration_horizon == row["horizon_step"] else f"extrapolated_from_step_{calibration_horizon}"
        for method_id in REQUIRED_METHODS:
            key = (row["model_id"], row["segment_id"], calibration_horizon, method_id)
            if key not in params:
                missing_params.append(":".join(map(str, key)))
                continue
            group_params = params[key]
            lower, upper, width = interval_from_params(row["forecast_value"], group_params, context["lower_bound_floor"])
            confidence = int(round(context["coverage_target"] * 100))
            uncertainty_statement = (
                f"{confidence}% prediction interval from rolling-origin {method_id}; "
                f"{spec['interval_policy']['tiny_profile_decision_status']}"
            )
            interval_rows.append(
                {
                    "interval_calibration_id": spec["interval_calibration_id"],
                    "forecast_id": row["forecast_id"],
                    "metric_id": row["metric_id"],
                    "segment_id": row["segment_id"],
                    "model_id": row["model_id"],
                    "model_role": row["model_role"],
                    "family": row["family"],
                    "forecast_date": row["forecast_date"],
                    "horizon_step": row["horizon_step"],
                    "method_id": method_id,
                    "decision_role": group_params["decision_role"],
                    "point_forecast": format_number(row["forecast_value"]),
                    "lower_bound": format_number(lower),
                    "upper_bound": format_number(upper),
                    "interval_width": format_number(width),
                    "coverage_target": format_number(context["coverage_target"]),
                    "calibration_horizon_step": calibration_horizon,
                    "horizon_policy_status": horizon_status,
                    "uncertainty_statement": uncertainty_statement,
                }
            )
    if missing_params:
        checks.append(failed("final_intervals_have_calibration_params", missing_params[:10], "every final row has calibration parameters"))
    else:
        checks.append(passed("final_intervals_have_calibration_params", len(interval_rows)))

    expected_rows = len(final_rows) * len(REQUIRED_METHODS)
    if len(interval_rows) != expected_rows:
        checks.append(failed("point_forecasts_have_uncertainty_statement", len(interval_rows), expected_rows))
    elif any(not row["uncertainty_statement"] for row in interval_rows):
        checks.append(failed("point_forecasts_have_uncertainty_statement", "blank statement", "non-empty uncertainty statement"))
    else:
        checks.append(passed("point_forecasts_have_uncertainty_statement", len(interval_rows)))
    return checks, interval_rows


def build_report(
    spec: dict[str, Any],
    checks: list[dict[str, Any]],
    context: dict[str, Any] | None,
    calibration_rows: list[dict[str, Any]],
    backtest_interval_rows: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
    final_interval_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    blocking_errors = [check["id"] for check in checks if not check["valid"] and check["severity"] == "error"]
    warnings = [check["id"] for check in checks if not check["valid"] and check["severity"] == "warning"]
    primary_method = spec.get("primary_interval_method", "")
    primary_overall = [
        row
        for row in coverage_rows
        if row.get("method_id") == primary_method and row.get("aggregation_level") == "overall"
    ]
    primary_min_coverage = min(
        [parse_float(row["empirical_coverage"], "empirical_coverage") for row in primary_overall],
        default=None,
    )
    return {
        "audit_id": "prediction-interval-calibration-report",
        "interval_calibration_id": spec.get("interval_calibration_id"),
        "forecast_id": spec.get("forecast_id"),
        "backtest_id": spec.get("backtest_id"),
        "metric_evaluation_id": spec.get("metric_evaluation_id"),
        "valid": not blocking_errors,
        "warning_count": len(warnings),
        "error_count": len(blocking_errors),
        "checks": checks,
        "outputs": {
            "calibration_rows": len(calibration_rows),
            "backtest_interval_rows": len(backtest_interval_rows),
            "coverage_rows": len(coverage_rows),
            "interval_forecast_rows": len(final_interval_rows),
            "primary_interval_method": primary_method,
            "primary_interval_min_coverage": format_number(primary_min_coverage),
            "coverage_target": format_number(context["coverage_target"]) if context else None,
            "final_horizon_days": context["final_horizon"] if context else None,
            "calibrated_horizon_steps": context["calibrated_horizons"] if context else [],
        },
        "interval_policy": spec.get("interval_policy", {}),
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(blocking_errors) + len(warnings),
            "blocking_errors": blocking_errors,
            "warnings": warnings,
        },
    }


def build_prediction_interval_package(
    *,
    errors_path: Path,
    final_baseline_forecasts_path: Path,
    final_candidate_forecasts_path: Path,
    backtest_report_path: Path,
    metric_report_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    spec = read_json(spec_path)
    backtest_report = read_json(backtest_report_path)
    metric_report = read_json(metric_report_path)
    checks, context = normalize_spec_and_reports(spec, backtest_report, metric_report)
    if context is None:
        report = build_report(spec, checks, None, [], [], [], [])
        return {
            "calibration_rows": [],
            "backtest_interval_rows": [],
            "coverage_rows": [],
            "interval_forecast_rows": [],
            "report": report,
        }

    error_rows, error_fields = read_csv(errors_path)
    parsed_checks, parsed_errors = parse_error_rows(error_rows, error_fields, spec, context)
    checks.extend(parsed_checks)
    if parsed_errors is None:
        report = build_report(spec, checks, context, [], [], [], [])
        return {
            "calibration_rows": [],
            "backtest_interval_rows": [],
            "coverage_rows": [],
            "interval_forecast_rows": [],
            "report": report,
        }

    baseline_rows, baseline_fields = read_csv(final_baseline_forecasts_path)
    candidate_rows, candidate_fields = read_csv(final_candidate_forecasts_path)
    final_checks, final_forecasts = parse_final_forecasts(
        baseline_rows,
        baseline_fields,
        candidate_rows,
        candidate_fields,
        spec,
        context,
    )
    checks.extend(final_checks)
    if final_forecasts is None:
        report = build_report(spec, checks, context, [], [], [], [])
        return {
            "calibration_rows": [],
            "backtest_interval_rows": [],
            "coverage_rows": [],
            "interval_forecast_rows": [],
            "report": report,
        }

    calibration_checks, calibration_rows, params = build_calibration_params(spec, context, parsed_errors)
    checks.extend(calibration_checks)
    if params is None:
        report = build_report(spec, checks, context, calibration_rows, [], [], [])
        return {
            "calibration_rows": calibration_rows,
            "backtest_interval_rows": [],
            "coverage_rows": [],
            "interval_forecast_rows": [],
            "report": report,
        }

    backtest_interval_rows = build_backtest_interval_rows(spec, context, parsed_errors, params)
    coverage_checks, coverage_rows = build_coverage_rows(spec, context, backtest_interval_rows)
    checks.extend(coverage_checks)
    final_interval_checks, interval_forecast_rows = build_final_interval_rows(spec, context, final_forecasts, params)
    checks.extend(final_interval_checks)
    report = build_report(
        spec,
        checks,
        context,
        calibration_rows,
        backtest_interval_rows,
        coverage_rows,
        interval_forecast_rows,
    )
    return {
        "calibration_rows": calibration_rows,
        "backtest_interval_rows": backtest_interval_rows,
        "coverage_rows": coverage_rows,
        "interval_forecast_rows": interval_forecast_rows,
        "report": report,
    }


def write_package(package: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "interval_calibration_audit.csv",
        package["calibration_rows"],
        [
            "interval_calibration_id",
            "forecast_id",
            "backtest_id",
            "model_id",
            "segment_id",
            "horizon_step",
            "method_id",
            "decision_role",
            "calibration_rows",
            "coverage_target",
            "alpha",
            "residual_mean",
            "residual_stddev",
            "lower_residual",
            "upper_residual",
            "interval_half_width",
            "calibration_status",
        ],
    )
    write_csv(
        output_dir / "interval_backtest_predictions.csv",
        package["backtest_interval_rows"],
        [
            "interval_calibration_id",
            "forecast_id",
            "backtest_id",
            "split_id",
            "window_type",
            "metric_id",
            "segment_id",
            "model_id",
            "model_role",
            "family",
            "forecast_date",
            "horizon_step",
            "method_id",
            "decision_role",
            "point_forecast",
            "actual_value",
            "lower_bound",
            "upper_bound",
            "interval_width",
            "covered",
            "calibration_rows",
            "calibration_horizon_step",
        ],
    )
    write_csv(
        output_dir / "interval_coverage.csv",
        package["coverage_rows"],
        [
            "interval_calibration_id",
            "forecast_id",
            "backtest_id",
            "aggregation_level",
            "method_id",
            "decision_role",
            "model_id",
            "segment_id",
            "horizon_step",
            "n_observations",
            "covered_count",
            "empirical_coverage",
            "target_coverage",
            "coverage_gap",
            "coverage_status",
        ],
    )
    write_csv(
        output_dir / "interval_forecasts.csv",
        package["interval_forecast_rows"],
        [
            "interval_calibration_id",
            "forecast_id",
            "metric_id",
            "segment_id",
            "model_id",
            "model_role",
            "family",
            "forecast_date",
            "horizon_step",
            "method_id",
            "decision_role",
            "point_forecast",
            "lower_bound",
            "upper_bound",
            "interval_width",
            "coverage_target",
            "calibration_horizon_step",
            "horizon_policy_status",
            "uncertainty_statement",
        ],
    )
    (output_dir / "interval_report.json").write_text(
        json.dumps(package["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate prediction intervals from rolling-origin forecast errors")
    parser.add_argument("--errors", type=Path, required=True)
    parser.add_argument("--final-baseline-forecasts", type=Path, required=True)
    parser.add_argument("--final-candidate-forecasts", type=Path, required=True)
    parser.add_argument("--backtest-report", type=Path, required=True)
    parser.add_argument("--metric-report", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args()

    package = build_prediction_interval_package(
        errors_path=args.errors,
        final_baseline_forecasts_path=args.final_baseline_forecasts,
        final_candidate_forecasts_path=args.final_candidate_forecasts,
        backtest_report_path=args.backtest_report,
        metric_report_path=args.metric_report,
        spec_path=args.spec,
    )
    write_package(package, args.output_dir)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "interval_forecast_rows": report["outputs"]["interval_forecast_rows"],
                "coverage_rows": report["outputs"]["coverage_rows"],
                "primary_interval_method": report["outputs"]["primary_interval_method"],
                "primary_interval_min_coverage": report["outputs"]["primary_interval_min_coverage"],
            },
            ensure_ascii=False,
        )
    )
    if not report["valid"]:
        raise SystemExit(1)
    if args.fail_on_warning and report["warning_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
