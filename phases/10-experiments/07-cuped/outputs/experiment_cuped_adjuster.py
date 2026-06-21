from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import scipy
from scipy import stats


CUPED_EFFECT_FIELDS = [
    "metric_id",
    "role",
    "metric_type",
    "covariate",
    "method",
    "control_units",
    "treatment_units",
    "control_raw_mean",
    "treatment_raw_mean",
    "raw_absolute_lift",
    "control_adjusted_mean",
    "treatment_adjusted_mean",
    "adjusted_absolute_lift",
    "lift_delta",
    "covariate_control_mean",
    "covariate_treatment_mean",
    "theta",
    "correlation",
    "raw_variance",
    "adjusted_variance",
    "variance_reduction",
    "raw_welch_se",
    "adjusted_welch_se",
    "se_reduction",
    "ci_low",
    "ci_high",
    "p_value",
    "effect_table_absolute_lift",
    "apply_to_decision",
    "status",
    "diagnostics",
]

ADJUSTED_OBSERVATION_FIELDS = [
    "experiment_id",
    "user_id",
    "variant_id",
    "metric_id",
    "covariate",
    "raw_value",
    "covariate_value",
    "covariate_center",
    "theta",
    "adjusted_value",
]


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "")) for field in fieldnames})


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return value


def parse_float(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value.strip() == "":
        return math.nan
    if value == "inf":
        return math.inf
    if value == "-inf":
        return -math.inf
    return float(value)


def round_float(value: float, digits: int = 6) -> float | str:
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return round(float(value), digits)


def ordered_variants(protocol: dict[str, Any]) -> tuple[str, str]:
    control = next(item["variant_id"] for item in protocol["variants"] if item.get("is_control") is True)
    treatment = next(item["variant_id"] for item in protocol["variants"] if item.get("is_control") is False)
    return control, treatment


def effect_by_metric(effect_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["metric_id"]: row for row in effect_rows}


def pre_metrics_by_user(rows: list[dict[str, str]], experiment_id: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    indexed: dict[str, dict[str, str]] = {}
    duplicates: list[str] = []
    for row in rows:
        if row.get("experiment_id") != experiment_id:
            continue
        user_id = row["user_id"]
        if user_id in indexed:
            duplicates.append(user_id)
        indexed[user_id] = row
    return indexed, sorted(set(duplicates))


def protocol_covariate_names(protocol: dict[str, Any]) -> set[str]:
    return {item["name"] for item in protocol.get("pre_experiment_covariates", [])}


def protocol_cuped_covariates(protocol: dict[str, Any]) -> set[str]:
    return set(protocol.get("cuped_policy", {}).get("covariates", []))


def spec_covariates_by_name(cuped_spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in cuped_spec.get("covariates", [])}


def observations_for_metric(observations: list[dict[str, str]], metric_id: str) -> list[dict[str, str]]:
    rows = []
    for row in observations:
        if row.get("metric_id") != metric_id:
            continue
        if row.get("value", "").strip() == "":
            continue
        if parse_float(row.get("denominator", "")) <= 0:
            continue
        rows.append(row)
    return rows


def sample_variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return float(np.var(np.array(values, dtype=float), ddof=1))


def sample_covariance(x_values: list[float], y_values: list[float]) -> float:
    if len(x_values) < 2 or len(y_values) < 2:
        return 0.0
    x = np.array(x_values, dtype=float)
    y = np.array(y_values, dtype=float)
    return float(np.cov(x, y, ddof=1)[0, 1])


def correlation(x_values: list[float], y_values: list[float]) -> float:
    x_var = sample_variance(x_values)
    y_var = sample_variance(y_values)
    if x_var <= 0 or y_var <= 0:
        return math.nan
    return sample_covariance(x_values, y_values) / math.sqrt(x_var * y_var)


def mean(values: list[float]) -> float:
    if not values:
        return math.nan
    return float(np.mean(np.array(values, dtype=float)))


def values_by_variant(values: list[float], rows: list[dict[str, str]]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = {}
    for value, row in zip(values, rows, strict=True):
        grouped.setdefault(row["variant_id"], []).append(value)
    return grouped


def welch_se(treatment: list[float], control: list[float]) -> float:
    if not treatment or not control:
        return math.nan
    treatment_var = sample_variance(treatment)
    control_var = sample_variance(control)
    return math.sqrt(treatment_var / len(treatment) + control_var / len(control))


def welch_interval(treatment: list[float], control: list[float], alpha: float) -> tuple[float, float]:
    diff = mean(treatment) - mean(control)
    se = welch_se(treatment, control)
    if not math.isfinite(se) or se <= 0:
        return diff, diff
    treatment_var = sample_variance(treatment)
    control_var = sample_variance(control)
    df_num = (treatment_var / len(treatment) + control_var / len(control)) ** 2
    df_den = 0.0
    if len(treatment) > 1 and treatment_var > 0:
        df_den += (treatment_var / len(treatment)) ** 2 / (len(treatment) - 1)
    if len(control) > 1 and control_var > 0:
        df_den += (control_var / len(control)) ** 2 / (len(control) - 1)
    df = df_num / df_den if df_den > 0 else math.inf
    critical = stats.t.ppf(1 - alpha / 2, df) if math.isfinite(df) else stats.norm.ppf(1 - alpha / 2)
    margin = float(critical * se)
    return diff - margin, diff + margin


def scipy_alternative(expected_direction: str) -> str:
    if expected_direction in {"up", "up_is_bad"}:
        return "greater"
    if expected_direction in {"down", "down_is_bad"}:
        return "less"
    return "two-sided"


def welch_p_value(treatment: list[float], control: list[float], expected_direction: str) -> float:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = stats.ttest_ind(
            treatment,
            control,
            equal_var=False,
            alternative=scipy_alternative(expected_direction),
        )
    return float(result.pvalue)


def analyze_metric(
    protocol: dict[str, Any],
    cuped_spec: dict[str, Any],
    metric_config: dict[str, Any],
    observations: list[dict[str, str]],
    pre_metrics: dict[str, dict[str, str]],
    effect_map: dict[str, dict[str, str]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    metric_id = metric_config["metric_id"]
    checks: list[dict[str, Any]] = []
    adjusted_rows: list[dict[str, Any]] = []
    if metric_config.get("enabled") is not True:
        skipped = {
            "metric_id": metric_id,
            "reason": metric_config.get("skip_reason", "disabled_in_cuped_spec"),
        }
        return None, adjusted_rows, checks, [skipped]

    effect = effect_map.get(metric_id)
    checks.append(
        {
            "id": f"{metric_id}:effect_result_exists",
            "metric_id": metric_id,
            "severity": "error",
            "valid": effect is not None,
            "observed": sorted(effect_map),
            "expected": metric_id,
        }
    )
    if effect is None:
        return None, adjusted_rows, checks, []

    metric_type = effect["metric_type"]
    checks.append(
        {
            "id": f"{metric_id}:metric_type_supported_for_simple_cuped",
            "metric_id": metric_id,
            "severity": "error",
            "valid": metric_type in {"proportion", "mean"},
            "observed": metric_type,
            "expected": ["proportion", "mean"],
        }
    )
    if metric_type not in {"proportion", "mean"}:
        return None, adjusted_rows, checks, []

    covariate = metric_config["covariate"]
    declared_covariates = protocol_covariate_names(protocol) & protocol_cuped_covariates(protocol)
    spec_covariates = spec_covariates_by_name(cuped_spec)
    covariate_meta = spec_covariates.get(covariate, {})
    checks.append(
        {
            "id": f"{metric_id}:covariate_declared_in_protocol",
            "metric_id": metric_id,
            "severity": "error",
            "valid": covariate in declared_covariates,
            "observed": covariate,
            "expected": sorted(declared_covariates),
        }
    )
    checks.append(
        {
            "id": f"{metric_id}:covariate_is_pre_treatment",
            "metric_id": metric_id,
            "severity": "error",
            "valid": covariate_meta.get("timing") == "pre_treatment",
            "observed": covariate_meta.get("timing"),
            "expected": "pre_treatment",
        }
    )
    if covariate not in declared_covariates or covariate_meta.get("timing") != "pre_treatment":
        return None, adjusted_rows, checks, []

    rows = observations_for_metric(observations, metric_id)
    missing_covariate_users = [
        row["user_id"]
        for row in rows
        if row["user_id"] not in pre_metrics or pre_metrics[row["user_id"]].get(covariate, "").strip() == ""
    ]
    checks.append(
        {
            "id": f"{metric_id}:covariate_complete_for_analysis_units",
            "metric_id": metric_id,
            "severity": "error",
            "valid": not missing_covariate_users,
            "observed": sorted(missing_covariate_users),
            "expected": "every analyzed user has a pre-experiment covariate value",
        }
    )
    if missing_covariate_users:
        return None, adjusted_rows, checks, []

    control_id, treatment_id = ordered_variants(protocol)
    raw_y = [parse_float(row["value"]) for row in rows]
    covariate_x = [parse_float(pre_metrics[row["user_id"]][covariate]) for row in rows]
    grouped_raw = values_by_variant(raw_y, rows)
    checks.append(
        {
            "id": f"{metric_id}:both_variants_have_observations",
            "metric_id": metric_id,
            "severity": "error",
            "valid": bool(grouped_raw.get(control_id)) and bool(grouped_raw.get(treatment_id)),
            "observed": {variant: len(values) for variant, values in sorted(grouped_raw.items())},
            "expected": {control_id: "> 0", treatment_id: "> 0"},
        }
    )
    x_var = sample_variance(covariate_x)
    checks.append(
        {
            "id": f"{metric_id}:covariate_variance_positive",
            "metric_id": metric_id,
            "severity": "error",
            "valid": x_var > 0,
            "observed": round_float(x_var),
            "expected": "> 0",
        }
    )
    if not grouped_raw.get(control_id) or not grouped_raw.get(treatment_id) or x_var <= 0:
        return None, adjusted_rows, checks, []

    cov_y = sample_covariance(covariate_x, raw_y)
    theta = cov_y / x_var
    covariate_center = mean(covariate_x)
    adjusted_y = [y_value - theta * (x_value - covariate_center) for y_value, x_value in zip(raw_y, covariate_x, strict=True)]
    grouped_adjusted = values_by_variant(adjusted_y, rows)
    grouped_x = values_by_variant(covariate_x, rows)
    control_raw = grouped_raw[control_id]
    treatment_raw = grouped_raw[treatment_id]
    control_adjusted = grouped_adjusted[control_id]
    treatment_adjusted = grouped_adjusted[treatment_id]
    raw_lift = mean(treatment_raw) - mean(control_raw)
    adjusted_lift = mean(treatment_adjusted) - mean(control_adjusted)
    raw_variance = sample_variance(raw_y)
    adjusted_variance = sample_variance(adjusted_y)
    raw_se = welch_se(treatment_raw, control_raw)
    adjusted_se = welch_se(treatment_adjusted, control_adjusted)
    variance_reduction = 1 - adjusted_variance / raw_variance if raw_variance > 0 else 0.0
    se_reduction = 1 - adjusted_se / raw_se if raw_se > 0 else 0.0
    ci_low, ci_high = welch_interval(treatment_adjusted, control_adjusted, float(protocol["alpha"]))
    p_value = welch_p_value(treatment_adjusted, control_adjusted, effect["expected_direction"])
    effect_table_lift = parse_float(effect["absolute_lift"])

    diagnostics: list[str] = []
    minimum_units = int(cuped_spec["minimum_units_per_variant"])
    if len(control_adjusted) < minimum_units:
        diagnostics.append("control_sample_below_minimum_units")
    if len(treatment_adjusted) < minimum_units:
        diagnostics.append("treatment_sample_below_minimum_units")
    if abs(correlation(covariate_x, raw_y)) < float(cuped_spec["minimum_abs_correlation"]):
        diagnostics.append("weak_covariate_correlation")
    if variance_reduction <= 0:
        diagnostics.append("no_variance_reduction")

    checks.append(
        {
            "id": f"{metric_id}:effect_table_matches_raw_observations",
            "metric_id": metric_id,
            "severity": "error",
            "valid": round_float(raw_lift) == round_float(effect_table_lift),
            "observed": round_float(raw_lift),
            "expected": round_float(effect_table_lift),
        }
    )
    checks.append(
        {
            "id": f"{metric_id}:variance_reduction_calculated",
            "metric_id": metric_id,
            "severity": "warning",
            "valid": variance_reduction > 0,
            "observed": round_float(variance_reduction),
            "expected": "> 0",
        }
    )
    checks.append(
        {
            "id": f"{metric_id}:observed_sample_meets_cuped_minimum",
            "metric_id": metric_id,
            "severity": "warning",
            "valid": len(control_adjusted) >= minimum_units and len(treatment_adjusted) >= minimum_units,
            "observed": {control_id: len(control_adjusted), treatment_id: len(treatment_adjusted)},
            "expected": f"n per variant >= {minimum_units}",
        }
    )

    for row, raw_value, covariate_value, adjusted_value in zip(rows, raw_y, covariate_x, adjusted_y, strict=True):
        adjusted_rows.append(
            {
                "experiment_id": row["experiment_id"],
                "user_id": row["user_id"],
                "variant_id": row["variant_id"],
                "metric_id": metric_id,
                "covariate": covariate,
                "raw_value": round_float(raw_value),
                "covariate_value": round_float(covariate_value),
                "covariate_center": round_float(covariate_center),
                "theta": round_float(theta),
                "adjusted_value": round_float(adjusted_value),
            }
        )

    effect_row = {
        "metric_id": metric_id,
        "role": effect["role"],
        "metric_type": metric_type,
        "covariate": covariate,
        "method": "cuped_single_pre_treatment_covariate",
        "control_units": len(control_adjusted),
        "treatment_units": len(treatment_adjusted),
        "control_raw_mean": round_float(mean(control_raw)),
        "treatment_raw_mean": round_float(mean(treatment_raw)),
        "raw_absolute_lift": round_float(raw_lift),
        "control_adjusted_mean": round_float(mean(control_adjusted)),
        "treatment_adjusted_mean": round_float(mean(treatment_adjusted)),
        "adjusted_absolute_lift": round_float(adjusted_lift),
        "lift_delta": round_float(adjusted_lift - raw_lift),
        "covariate_control_mean": round_float(mean(grouped_x[control_id])),
        "covariate_treatment_mean": round_float(mean(grouped_x[treatment_id])),
        "theta": round_float(theta),
        "correlation": round_float(correlation(covariate_x, raw_y)),
        "raw_variance": round_float(raw_variance),
        "adjusted_variance": round_float(adjusted_variance),
        "variance_reduction": round_float(variance_reduction),
        "raw_welch_se": round_float(raw_se),
        "adjusted_welch_se": round_float(adjusted_se),
        "se_reduction": round_float(se_reduction),
        "ci_low": round_float(ci_low),
        "ci_high": round_float(ci_high),
        "p_value": round_float(p_value),
        "effect_table_absolute_lift": round_float(effect_table_lift),
        "apply_to_decision": bool(metric_config.get("apply_to_decision", False)),
        "status": "warning" if diagnostics else "ready",
        "diagnostics": diagnostics,
    }
    return effect_row, adjusted_rows, checks, []


def invalid_upstream_report(protocol: dict[str, Any], cuped_spec: dict[str, Any], assumption_checks: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    report = {
        "valid": False,
        "ready_for_decision": False,
        "summary": {
            "experiment_id": protocol["experiment_id"],
            "metrics_analyzed": 0,
            "adjustment_unit": cuped_spec.get("adjustment_unit"),
            "blocking_failures": ["upstream_effect_analysis_not_valid"],
            "warning_metrics": [],
            "skipped_metrics": [],
        },
        "effects": [],
        "skipped_metrics": [],
        "checks": [
            {
                "id": "upstream_effect_analysis_valid",
                "severity": "error",
                "valid": False,
                "observed": assumption_checks.get("valid"),
                "expected": True,
            }
        ],
    }
    manifest = build_manifest(protocol, cuped_spec, report)
    return report, [], [], manifest


def build_report(
    protocol: dict[str, Any],
    cuped_spec: dict[str, Any],
    observations: list[dict[str, str]],
    pre_experiment_metrics: list[dict[str, str]],
    effect_results: list[dict[str, str]],
    assumption_checks: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if assumption_checks.get("valid") is not True:
        return invalid_upstream_report(protocol, cuped_spec, assumption_checks)

    pre_metrics, duplicate_pre_users = pre_metrics_by_user(pre_experiment_metrics, protocol["experiment_id"])
    effect_map = effect_by_metric(effect_results)
    checks: list[dict[str, Any]] = [
        {
            "id": "upstream_effect_analysis_valid",
            "severity": "error",
            "valid": True,
            "observed": True,
            "expected": True,
        },
        {
            "id": "cuped_policy_enabled",
            "severity": "error",
            "valid": protocol.get("cuped_policy", {}).get("enabled") is True,
            "observed": protocol.get("cuped_policy", {}).get("enabled"),
            "expected": True,
        },
        {
            "id": "adjustment_unit_matches_protocol",
            "severity": "error",
            "valid": cuped_spec["adjustment_unit"] == protocol["analysis_unit"] == protocol["randomization_unit"],
            "observed": {
                "adjustment_unit": cuped_spec["adjustment_unit"],
                "analysis_unit": protocol["analysis_unit"],
                "randomization_unit": protocol["randomization_unit"],
            },
            "expected": "all are the same unit for this user-level experiment",
        },
        {
            "id": "pre_experiment_metrics_unique_by_user",
            "severity": "error",
            "valid": not duplicate_pre_users,
            "observed": duplicate_pre_users,
            "expected": "one pre-experiment metric row per experiment_id, user_id",
        },
    ]
    effects: list[dict[str, Any]] = []
    adjusted_rows: list[dict[str, Any]] = []
    skipped_metrics: list[dict[str, Any]] = []
    for metric_config in cuped_spec["metrics"]:
        effect_row, metric_adjusted_rows, metric_checks, metric_skipped = analyze_metric(
            protocol,
            cuped_spec,
            metric_config,
            observations,
            pre_metrics,
            effect_map,
        )
        checks.extend(metric_checks)
        adjusted_rows.extend(metric_adjusted_rows)
        skipped_metrics.extend(metric_skipped)
        if effect_row is not None:
            effects.append(effect_row)

    blocking_failures = [check["id"] for check in checks if check["severity"] == "error" and not check["valid"]]
    warning_checks = [check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]]
    warning_metrics = [row["metric_id"] for row in effects if row["status"] == "warning"]
    primary = next((row for row in effects if row["metric_id"] == protocol["primary_metric"]), None)
    report = {
        "valid": not blocking_failures,
        "ready_for_decision": False,
        "summary": {
            "experiment_id": protocol["experiment_id"],
            "metrics_analyzed": len(effects),
            "adjusted_observation_rows": len(adjusted_rows),
            "adjustment_unit": cuped_spec["adjustment_unit"],
            "blocking_failures": blocking_failures,
            "warning_checks": warning_checks,
            "warning_metrics": warning_metrics,
            "skipped_metrics": [row["metric_id"] for row in skipped_metrics],
            "variance_reduction_metrics": [
                row["metric_id"] for row in effects if parse_float(row["variance_reduction"]) > 0
            ],
            "primary_adjusted_absolute_lift": None if primary is None else primary["adjusted_absolute_lift"],
            "upstream_ready_for_decision": assumption_checks.get("ready_for_decision"),
        },
        "effects": effects,
        "skipped_metrics": skipped_metrics,
        "checks": checks,
    }
    manifest = build_manifest(protocol, cuped_spec, report)
    return report, effects, adjusted_rows, manifest


def build_manifest(protocol: dict[str, Any], cuped_spec: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact": "experiment-cuped-adjuster",
        "experiment_id": protocol["experiment_id"],
        "scipy_version": scipy.__version__,
        "adjustment_unit": cuped_spec.get("adjustment_unit"),
        "covariates": [item["name"] for item in cuped_spec.get("covariates", [])],
        "metrics": [row["metric_id"] for row in report.get("effects", [])],
        "skipped_metrics": [row["metric_id"] for row in report.get("skipped_metrics", [])],
        "valid": report["valid"],
    }


def run(
    protocol_path: Path,
    cuped_spec_path: Path,
    observations_path: Path,
    pre_experiment_metrics_path: Path,
    effect_results_path: Path,
    assumption_checks_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return build_report(
        read_json(protocol_path),
        read_json(cuped_spec_path),
        read_csv(observations_path),
        read_csv(pre_experiment_metrics_path),
        read_csv(effect_results_path),
        read_json(assumption_checks_path),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CUPED adjustment for fixed-horizon experiment effects.")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--cuped-spec", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--pre-experiment-metrics", type=Path, required=True)
    parser.add_argument("--effect-results", type=Path, required=True)
    parser.add_argument("--assumption-checks", type=Path, required=True)
    parser.add_argument("--output-effects", type=Path)
    parser.add_argument("--output-adjusted-observations", type=Path)
    parser.add_argument("--output-report", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report, effects, adjusted_rows, manifest = run(
        args.protocol,
        args.cuped_spec,
        args.observations,
        args.pre_experiment_metrics,
        args.effect_results,
        args.assumption_checks,
    )
    if args.output_effects is not None:
        write_csv(args.output_effects, effects, CUPED_EFFECT_FIELDS)
    if args.output_adjusted_observations is not None:
        write_csv(args.output_adjusted_observations, adjusted_rows, ADJUSTED_OBSERVATION_FIELDS)
    if args.output_report is not None:
        write_json(args.output_report, report)
    if args.output_manifest is not None:
        write_json(args.output_manifest, manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
