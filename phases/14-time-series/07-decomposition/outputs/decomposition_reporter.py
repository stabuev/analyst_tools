from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from statsmodels.tsa.seasonal import STL


REQUIRED_SERIES_COLUMNS = {
    "metric_id",
    "segment_id",
    "observed_date",
    "frequency",
    "value",
    "include_in_training",
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
    "embargo_dates",
    "split_type",
}
REQUIRED_BASELINE_REPORT_FIELDS = {
    "baseline_id",
    "forecast_id",
    "valid",
    "outputs",
    "policy",
    "summary",
}
REQUIRED_SPEC_FIELDS = {
    "decomposition_id",
    "forecast_id",
    "source_table",
    "cutoff_contract_id",
    "baseline_id",
    "target_metric",
    "target_segments",
    "time_column",
    "value_column",
    "complete_flag_column",
    "training_start",
    "training_end",
    "forecast_origin",
    "timezone",
    "frequency",
    "seasonal_period_days",
    "component_model",
    "method",
    "robust",
    "minimum_training_points",
    "minimum_cycles_for_decision",
    "residual_diagnostics",
    "interpretation_policy",
    "quality_gates",
}


class DecompositionReportError(ValueError):
    """Raised when decomposition inputs cannot be interpreted."""


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
        raise DecompositionReportError(f"{path.name} must contain a JSON object")
    return value


def parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise DecompositionReportError(f"{field} must be ISO date: {value}") from error


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DecompositionReportError(f"{field} must be ISO timestamp: {value}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DecompositionReportError(f"{field} must be timezone-aware: {value}")
    return parsed


def parse_bool(value: str | bool, field: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise DecompositionReportError(f"{field} must be true or false: {value}")
    return normalized == "true"


def parse_number(value: str, field: str) -> float:
    try:
        return float(value)
    except ValueError as error:
        raise DecompositionReportError(f"{field} must be numeric: {value}") from error


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def format_number(value: float) -> str:
    if abs(value) < 0.0000005:
        value = 0.0
    rounded = round(float(value), 6)
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
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    missing_scenario = sorted(REQUIRED_SCENARIO_FIELDS - set(scenario))
    missing_cutoff = sorted(REQUIRED_CUTOFF_FIELDS - set(cutoff_contract))
    missing_baseline = sorted(REQUIRED_BASELINE_REPORT_FIELDS - set(baseline_report))
    if missing_spec:
        checks.append(failed("decomposition_spec_required_fields", missing_spec, "all required decomposition fields"))
        return checks, None
    checks.append(passed("decomposition_spec_required_fields", len(REQUIRED_SPEC_FIELDS)))
    if missing_scenario:
        checks.append(failed("scenario_required_fields", missing_scenario, "all required scenario fields"))
        return checks, None
    checks.append(passed("scenario_required_fields", len(REQUIRED_SCENARIO_FIELDS)))
    if missing_cutoff:
        checks.append(failed("cutoff_contract_required_fields", missing_cutoff, "all required cutoff fields"))
        return checks, None
    checks.append(passed("cutoff_contract_required_fields", len(REQUIRED_CUTOFF_FIELDS)))
    if missing_baseline:
        checks.append(failed("baseline_report_required_fields", missing_baseline, "all required baseline report fields"))
        return checks, None
    checks.append(passed("baseline_report_required_fields", len(REQUIRED_BASELINE_REPORT_FIELDS)))

    try:
        timezone = ZoneInfo(str(spec["timezone"]))
        forecast_origin = parse_timestamp(str(spec["forecast_origin"]), "forecast_origin")
    except (ZoneInfoNotFoundError, DecompositionReportError) as error:
        checks.append(failed("timezone_and_origin_valid", str(error), "valid timezone and forecast origin"))
        return checks, None
    checks.append(passed("timezone_and_origin_valid", spec["timezone"]))

    segments = spec.get("target_segments")
    if not isinstance(segments, list) or not segments or not all(isinstance(item, str) and item for item in segments):
        checks.append(failed("target_segments_declared", segments, "non-empty segment list"))
        return checks, None
    checks.append(passed("target_segments_declared", segments))

    try:
        normalized = {
            "decomposition_id": str(spec["decomposition_id"]),
            "forecast_id": str(spec["forecast_id"]),
            "source_table": str(spec["source_table"]),
            "cutoff_contract_id": str(spec["cutoff_contract_id"]),
            "baseline_id": str(spec["baseline_id"]),
            "target_metric": str(spec["target_metric"]),
            "target_segments": [str(segment) for segment in segments],
            "time_column": str(spec["time_column"]),
            "value_column": str(spec["value_column"]),
            "complete_flag_column": str(spec["complete_flag_column"]),
            "training_start": parse_date(str(spec["training_start"]), "training_start"),
            "training_end": parse_date(str(spec["training_end"]), "training_end"),
            "forecast_origin": forecast_origin,
            "timezone": timezone,
            "timezone_name": str(spec["timezone"]),
            "frequency": str(spec["frequency"]),
            "seasonal_period_days": int(spec["seasonal_period_days"]),
            "component_model": str(spec["component_model"]),
            "method": str(spec["method"]),
            "robust": parse_bool(spec["robust"], "robust"),
            "minimum_training_points": int(spec["minimum_training_points"]),
            "minimum_cycles_for_decision": float(spec["minimum_cycles_for_decision"]),
            "residual_diagnostics": spec["residual_diagnostics"],
            "interpretation_policy": spec["interpretation_policy"],
            "scenario": scenario,
            "cutoff_contract": cutoff_contract,
            "baseline_report": baseline_report,
            "embargo_dates": [
                parse_date(str(day), "embargo_dates")
                for day in cutoff_contract["embargo_dates"]
            ],
        }
    except (TypeError, ValueError, DecompositionReportError) as error:
        checks.append(failed("decomposition_spec_values_parse", str(error), "parseable dates and numeric settings"))
        return checks, None
    checks.append(passed("decomposition_spec_values_parse", normalized["decomposition_id"]))

    alignment_errors: list[dict[str, Any]] = []
    for field in ("forecast_id", "target_metric", "target_segments", "timezone", "frequency", "forecast_origin"):
        if spec[field] != scenario[field]:
            alignment_errors.append({"field": field, "decomposition_spec": spec[field], "scenario": scenario[field]})
    if spec["training_end"] != scenario["complete_through"]:
        alignment_errors.append(
            {
                "field": "training_end/complete_through",
                "decomposition_spec": spec["training_end"],
                "scenario": scenario["complete_through"],
            }
        )
    for field in ("forecast_id", "target_metric", "target_segments", "timezone", "frequency", "training_start", "training_end", "forecast_origin"):
        if spec[field] != cutoff_contract[field]:
            alignment_errors.append({"field": field, "decomposition_spec": spec[field], "cutoff_contract": cutoff_contract[field]})
    if spec["cutoff_contract_id"] != cutoff_contract["leakage_audit_id"]:
        alignment_errors.append(
            {
                "field": "cutoff_contract_id",
                "decomposition_spec": spec["cutoff_contract_id"],
                "cutoff_contract": cutoff_contract["leakage_audit_id"],
            }
        )
    if spec["baseline_id"] != baseline_report["baseline_id"] or spec["forecast_id"] != baseline_report["forecast_id"]:
        alignment_errors.append(
            {
                "field": "baseline report ids",
                "decomposition_spec": {"baseline_id": spec["baseline_id"], "forecast_id": spec["forecast_id"]},
                "baseline_report": {
                    "baseline_id": baseline_report["baseline_id"],
                    "forecast_id": baseline_report["forecast_id"],
                },
            }
        )
    if alignment_errors:
        checks.append(
            failed(
                "scenario_cutoff_baseline_and_decomposition_spec_align",
                len(alignment_errors),
                "matching scenario, cutoff, baseline, and decomposition setup",
                alignment_errors,
            )
        )
    else:
        checks.append(passed("scenario_cutoff_baseline_and_decomposition_spec_align", "all setup ids and dates aligned"))

    if cutoff_contract["split_type"] != "time_ordered_cutoff":
        checks.append(failed("cutoff_contract_is_time_ordered", cutoff_contract["split_type"], "time_ordered_cutoff"))
    else:
        checks.append(passed("cutoff_contract_is_time_ordered", cutoff_contract["split_type"]))

    baseline_policy = baseline_report.get("policy", {})
    primary_baseline = baseline_report.get("outputs", {}).get("primary_baseline_model")
    if baseline_report.get("valid") is not True:
        checks.append(failed("baseline_report_is_valid", baseline_report.get("valid"), True))
    elif baseline_policy.get("candidate_model_must_beat") != "seasonal_naive_7" or primary_baseline != "seasonal_naive_7":
        checks.append(
            failed(
                "baseline_report_is_valid",
                {"policy": baseline_policy, "primary_baseline_model": primary_baseline},
                "valid seasonal_naive_7 baseline policy",
            )
        )
    else:
        checks.append(passed("baseline_report_is_valid", "seasonal_naive_7"))

    if normalized["method"] != "STL" or normalized["component_model"] != "additive":
        checks.append(
            failed(
                "decomposition_method_supported",
                {"method": normalized["method"], "component_model": normalized["component_model"]},
                "STL additive",
            )
        )
    else:
        checks.append(passed("decomposition_method_supported", "STL additive"))

    if normalized["seasonal_period_days"] != 7:
        checks.append(failed("seasonal_period_is_precommitted", normalized["seasonal_period_days"], 7))
    else:
        checks.append(passed("seasonal_period_is_precommitted", normalized["seasonal_period_days"]))

    policy = normalized["interpretation_policy"]
    if (
        not isinstance(policy, dict)
        or policy.get("decomposition_is_diagnostic_not_forecast_evidence") is not True
        or policy.get("candidate_models_still_must_beat_baseline") != "seasonal_naive_7"
    ):
        checks.append(failed("interpretation_policy_blocks_forecast_claim", policy, "diagnostic only with baseline comparison"))
    else:
        checks.append(passed("interpretation_policy_blocks_forecast_claim", "diagnostic_only"))

    return checks, normalized


def build_decomposition_package(
    *,
    series_path: Path,
    scenario_path: Path,
    cutoff_contract_path: Path,
    baseline_report_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    series_rows, series_columns = read_csv(series_path)
    scenario = read_json(scenario_path)
    cutoff_contract = read_json(cutoff_contract_path)
    baseline_report = read_json(baseline_report_path)
    spec = read_json(spec_path)

    spec_checks, normalized = normalize_inputs(spec, scenario, cutoff_contract, baseline_report)
    checks = list(spec_checks)
    missing_series_columns = sorted(REQUIRED_SERIES_COLUMNS - set(series_columns))
    checks.append(
        failed("series_columns_present", missing_series_columns, "all required series columns")
        if missing_series_columns
        else passed("series_columns_present", len(series_columns))
    )
    if normalized is None or missing_series_columns:
        return empty_package(spec, scenario, checks)

    parsed_series, series_checks = parse_series_rows(series_rows, normalized)
    checks.extend(series_checks)
    checks.extend(audit_source_series(parsed_series, normalized))

    if has_blocking_errors(checks):
        return empty_package(spec, scenario, checks)

    component_rows, diagnostics_rows, build_checks = build_components(parsed_series, normalized)
    checks.extend(build_checks)
    if not has_blocking_errors(checks):
        checks.extend(audit_component_outputs(component_rows, diagnostics_rows, normalized))

    report = build_report(spec, scenario, checks, component_rows, diagnostics_rows)
    return {
        "report": report,
        "component_rows": component_rows,
        "diagnostics_rows": diagnostics_rows,
    }


def empty_package(spec: dict[str, Any], scenario: dict[str, Any], checks: list[dict[str, Any]]) -> dict[str, Any]:
    report = build_report(spec, scenario, checks, [], [])
    return {"report": report, "component_rows": [], "diagnostics_rows": []}


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
        except DecompositionReportError as error:
            errors.append({"row": index, "error": str(error)})
    if errors:
        return parsed, [failed("series_rows_parse", len(errors), "valid date, value, and training flag", errors[:10])]
    return parsed, [passed("series_rows_parse", len(parsed))]


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

    forbidden_training_rows = [
        {"segment_id": row["segment_id"], "observed_date": row["_date"].isoformat()}
        for row in rows
        if row["_include_in_training"]
        and (row["_date"] > spec["training_end"] or row["_date"] in set(spec["embargo_dates"]))
    ]
    if forbidden_training_rows:
        checks.append(
            failed(
                "decomposition_uses_training_window_only",
                len(forbidden_training_rows),
                "no post-cutoff or embargo rows marked for training",
                forbidden_training_rows[:10],
            )
        )
    else:
        checks.append(passed("decomposition_uses_training_window_only", spec["training_end"].isoformat()))
    return checks


def build_components(
    rows: list[dict[str, Any]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    component_rows: list[dict[str, str]] = []
    diagnostics_rows: list[dict[str, str]] = []
    training_by_segment: dict[str, list[dict[str, Any]]] = {}
    for segment_id in spec["target_segments"]:
        segment_training = [
            row
            for row in rows
            if row["segment_id"] == segment_id
            and row["_include_in_training"]
            and spec["training_start"] <= row["_date"] <= spec["training_end"]
        ]
        training_by_segment[segment_id] = sorted(segment_training, key=lambda item: item["_date"])

    history_failures = []
    short_history_warnings = []
    for segment_id, training_rows in training_by_segment.items():
        training_points = len(training_rows)
        training_cycles = training_points / spec["seasonal_period_days"]
        if training_points < spec["minimum_training_points"]:
            history_failures.append(
                {
                    "segment_id": segment_id,
                    "training_points": training_points,
                    "minimum": spec["minimum_training_points"],
                }
            )
        if training_cycles < spec["minimum_cycles_for_decision"]:
            short_history_warnings.append(
                {
                    "segment_id": segment_id,
                    "training_cycles": format_number(training_cycles),
                    "minimum_cycles_for_decision": format_number(spec["minimum_cycles_for_decision"]),
                }
            )

    if history_failures:
        checks.append(failed("enough_history_for_stl", len(history_failures), "minimum training points for STL", history_failures))
        return component_rows, diagnostics_rows, checks
    checks.append(passed("enough_history_for_stl", "all segments"))

    if short_history_warnings:
        checks.append(
            failed(
                "short_history_blocks_accuracy_claim",
                len(short_history_warnings),
                "at least the configured number of full cycles for an accuracy claim",
                short_history_warnings,
                severity="warning",
            )
        )
    else:
        checks.append(passed("short_history_blocks_accuracy_claim", "enough cycles"))

    for segment_id, training_rows in training_by_segment.items():
        dates = [row["_date"] for row in training_rows]
        values = [row["_value"] for row in training_rows]
        series = pd.Series(values, index=pd.DatetimeIndex(dates)).asfreq(spec["frequency"])
        result = STL(series, period=spec["seasonal_period_days"], robust=spec["robust"]).fit()
        trend_values = [float(value) for value in result.trend.to_list()]
        seasonal_values = [float(value) for value in result.seasonal.to_list()]
        residual_values = [float(value) for value in result.resid.to_list()]

        for day, observed, trend, seasonal, residual in zip(dates, values, trend_values, seasonal_values, residual_values, strict=True):
            reconstructed = trend + seasonal + residual
            component_rows.append(
                {
                    "forecast_id": spec["forecast_id"],
                    "decomposition_id": spec["decomposition_id"],
                    "metric_id": spec["target_metric"],
                    "segment_id": segment_id,
                    "method_id": "stl_additive",
                    "component_model": spec["component_model"],
                    "observed_date": day.isoformat(),
                    "training_row": "true",
                    "observed_value": format_number(observed),
                    "trend": format_number(trend),
                    "seasonal": format_number(seasonal),
                    "residual": format_number(residual),
                    "reconstructed": format_number(reconstructed),
                    "reconstruction_error": format_number(observed - reconstructed),
                }
            )

        diagnostics_rows.append(build_residual_diagnostics(segment_id, values, trend_values, seasonal_values, residual_values, spec))
    return component_rows, diagnostics_rows, checks


def build_residual_diagnostics(
    segment_id: str,
    values: list[float],
    trend_values: list[float],
    seasonal_values: list[float],
    residual_values: list[float],
    spec: dict[str, Any],
) -> dict[str, str]:
    observed_mean = mean(values)
    residual_mean = mean(residual_values)
    residual_std = population_std(residual_values)
    residual_max_abs = max(abs(value) for value in residual_values)
    reconstructed_errors = [
        observed - (trend + seasonal + residual)
        for observed, trend, seasonal, residual in zip(values, trend_values, seasonal_values, residual_values, strict=True)
    ]
    reconstruction_max_abs_error = max(abs(value) for value in reconstructed_errors)
    lag1 = lag1_autocorrelation(residual_values)
    seasonal_amplitude = max(seasonal_values) - min(seasonal_values)
    trend_change = trend_values[-1] - trend_values[0]
    training_cycles = len(values) / spec["seasonal_period_days"]
    relative_amplitude = seasonal_amplitude / observed_mean if observed_mean else 0.0
    warnings = []
    decision_status = "diagnostic_ready_not_accuracy_proof"
    if training_cycles < spec["minimum_cycles_for_decision"]:
        warnings.append("short_history_blocks_accuracy_claim")
        decision_status = "diagnostic_only_short_history"
    interpretation = "additive_stl_diagnostic"
    if relative_amplitude > 0.25:
        interpretation = "multiplicative_review_recommended"

    return {
        "forecast_id": spec["forecast_id"],
        "decomposition_id": spec["decomposition_id"],
        "segment_id": segment_id,
        "method_id": "stl_additive",
        "component_model": spec["component_model"],
        "training_points": str(len(values)),
        "training_cycles": format_number(training_cycles),
        "seasonal_period_days": str(spec["seasonal_period_days"]),
        "observed_mean": format_number(observed_mean),
        "trend_start": format_number(trend_values[0]),
        "trend_end": format_number(trend_values[-1]),
        "trend_change": format_number(trend_change),
        "seasonal_amplitude": format_number(seasonal_amplitude),
        "seasonal_relative_amplitude": format_number(relative_amplitude),
        "residual_mean": format_number(residual_mean),
        "residual_std": format_number(residual_std),
        "residual_max_abs": format_number(residual_max_abs),
        "lag1_autocorrelation": format_number(lag1),
        "reconstruction_max_abs_error": format_number(reconstruction_max_abs_error),
        "interpretation": interpretation,
        "decision_status": decision_status,
        "warnings": ";".join(warnings),
    }


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def population_std(values: list[float]) -> float:
    average = mean(values)
    return math.sqrt(sum((value - average) ** 2 for value in values) / len(values))


def lag1_autocorrelation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = mean(values)
    denominator = sum((value - average) ** 2 for value in values)
    if denominator < 0.000000000001:
        return 0.0
    numerator = sum((values[index] - average) * (values[index - 1] - average) for index in range(1, len(values)))
    return numerator / denominator


def audit_component_outputs(
    component_rows: list[dict[str, str]],
    diagnostics_rows: list[dict[str, str]],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    expected_rows = len(spec["target_segments"]) * (
        (spec["training_end"] - spec["training_start"]).days + 1
    )
    if len(component_rows) != expected_rows:
        checks.append(failed("component_table_has_training_window", len(component_rows), expected_rows))
    else:
        checks.append(passed("component_table_has_training_window", expected_rows))

    key_counts = Counter((row["segment_id"], row["observed_date"]) for row in component_rows)
    duplicate_keys = [
        {"segment_id": segment_id, "observed_date": observed_date, "count": count}
        for (segment_id, observed_date), count in key_counts.items()
        if count > 1
    ]
    if duplicate_keys:
        checks.append(failed("one_component_row_per_segment_date", len(duplicate_keys), "unique component grain", duplicate_keys[:10]))
    else:
        checks.append(passed("one_component_row_per_segment_date", len(key_counts)))

    future_component_rows = [
        {"segment_id": row["segment_id"], "observed_date": row["observed_date"]}
        for row in component_rows
        if parse_date(row["observed_date"], "observed_date") > spec["training_end"]
    ]
    if future_component_rows:
        checks.append(failed("decomposition_uses_training_window_only", len(future_component_rows), "component dates stop at training_end", future_component_rows[:10]))
    else:
        checks.append(passed("decomposition_uses_training_window_only", spec["training_end"].isoformat()))

    tolerance = float(spec["residual_diagnostics"]["reconstruction_abs_tolerance"])
    reconstruction_errors = [
        {
            "segment_id": row["segment_id"],
            "observed_date": row["observed_date"],
            "reconstruction_error": row["reconstruction_error"],
        }
        for row in component_rows
        if abs(float(row["reconstruction_error"])) > tolerance
    ]
    if reconstruction_errors:
        checks.append(failed("component_table_reconstructs_observed", len(reconstruction_errors), f"abs(error) <= {tolerance}", reconstruction_errors[:10]))
    else:
        checks.append(passed("component_table_reconstructs_observed", tolerance))

    expected_diagnostics = len(spec["target_segments"])
    if len(diagnostics_rows) != expected_diagnostics:
        checks.append(failed("residual_diagnostics_emitted", len(diagnostics_rows), expected_diagnostics))
    else:
        checks.append(passed("residual_diagnostics_emitted", expected_diagnostics))

    residual_issues = []
    mean_abs_tolerance = float(spec["residual_diagnostics"]["mean_abs_tolerance"])
    lag1_abs_limit = float(spec["residual_diagnostics"]["lag1_autocorrelation_abs_limit"])
    for row in diagnostics_rows:
        if abs(float(row["residual_mean"])) > mean_abs_tolerance:
            residual_issues.append({"segment_id": row["segment_id"], "metric": "residual_mean", "value": row["residual_mean"]})
        if abs(float(row["lag1_autocorrelation"])) > lag1_abs_limit:
            residual_issues.append({"segment_id": row["segment_id"], "metric": "lag1_autocorrelation", "value": row["lag1_autocorrelation"]})
    if residual_issues:
        checks.append(failed("residual_diagnostics_within_thresholds", len(residual_issues), "residual mean and lag1 thresholds", residual_issues))
    else:
        checks.append(passed("residual_diagnostics_within_thresholds", "all segments"))
    return checks


def build_report(
    spec: dict[str, Any],
    scenario: dict[str, Any],
    checks: list[dict[str, Any]],
    component_rows: list[dict[str, str]],
    diagnostics_rows: list[dict[str, str]],
) -> dict[str, Any]:
    warnings = [check["id"] for check in checks if not check["valid"] and check["severity"] == "warning"]
    blocking_errors = [check["id"] for check in checks if not check["valid"] and check["severity"] == "error"]
    return {
        "audit_id": "stl-decomposition-report",
        "decomposition_id": spec.get("decomposition_id"),
        "forecast_id": scenario.get("forecast_id", spec.get("forecast_id")),
        "valid": not blocking_errors,
        "warning_count": len(warnings),
        "error_count": len(blocking_errors),
        "checks": checks,
        "outputs": {
            "component_rows": len(component_rows),
            "diagnostics_rows": len(diagnostics_rows),
            "segments": sorted({row["segment_id"] for row in component_rows}),
            "method_id": "stl_additive" if component_rows else None,
            "component_model": spec.get("component_model"),
            "training_start": spec.get("training_start"),
            "training_end": spec.get("training_end"),
        },
        "interpretation_policy": spec.get("interpretation_policy", {}),
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(warnings) + len(blocking_errors),
            "blocking_errors": blocking_errors,
            "warnings": warnings,
        },
    }


def write_package(package: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        output_dir / "decomposition_components.csv",
        package["component_rows"],
        [
            "forecast_id",
            "decomposition_id",
            "metric_id",
            "segment_id",
            "method_id",
            "component_model",
            "observed_date",
            "training_row",
            "observed_value",
            "trend",
            "seasonal",
            "residual",
            "reconstructed",
            "reconstruction_error",
        ],
    )
    write_csv(
        output_dir / "residual_diagnostics.csv",
        package["diagnostics_rows"],
        [
            "forecast_id",
            "decomposition_id",
            "segment_id",
            "method_id",
            "component_model",
            "training_points",
            "training_cycles",
            "seasonal_period_days",
            "observed_mean",
            "trend_start",
            "trend_end",
            "trend_change",
            "seasonal_amplitude",
            "seasonal_relative_amplitude",
            "residual_mean",
            "residual_std",
            "residual_max_abs",
            "lag1_autocorrelation",
            "reconstruction_max_abs_error",
            "interpretation",
            "decision_status",
            "warnings",
        ],
    )
    (output_dir / "decomposition_report.json").write_text(
        json.dumps(package["report"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an STL decomposition diagnostic report")
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--cutoff-contract", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--fail-on-warning", action="store_true")
    args = parser.parse_args(argv)

    package = build_decomposition_package(
        series_path=args.series,
        scenario_path=args.scenario,
        cutoff_contract_path=args.cutoff_contract,
        baseline_report_path=args.baseline_report,
        spec_path=args.spec,
    )
    write_package(package, args.output_dir)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "component_rows": report["outputs"]["component_rows"],
                "diagnostics_rows": report["outputs"]["diagnostics_rows"],
                "method_id": report["outputs"]["method_id"],
            },
            ensure_ascii=False,
        )
    )
    if not report["valid"]:
        return 1
    if args.fail_on_warning and report["warning_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
