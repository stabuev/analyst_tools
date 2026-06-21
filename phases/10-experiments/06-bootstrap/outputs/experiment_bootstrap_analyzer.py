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


DISTRIBUTION_FIELDS = [
    "metric_id",
    "resample_index",
    "control_statistic",
    "treatment_statistic",
    "bootstrap_absolute_lift",
    "valid",
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


def observations_for_metric(
    observations: list[dict[str, str]],
    metric_id: str,
    variant_id: str,
    metric_type: str,
) -> list[dict[str, str]]:
    rows = [row for row in observations if row["metric_id"] == metric_id and row["variant_id"] == variant_id]
    if metric_type == "ratio":
        return rows
    return [row for row in rows if parse_float(row["denominator"]) > 0 and row["value"].strip() != ""]


def statistic(rows: list[dict[str, str]], metric_type: str) -> float:
    if not rows:
        return math.nan
    if metric_type == "ratio":
        numerator = sum(parse_float(row["numerator"]) for row in rows)
        denominator = sum(parse_float(row["denominator"]) for row in rows)
        if denominator <= 0:
            return math.nan
        return numerator / denominator
    values = [parse_float(row["value"]) for row in rows if row["value"].strip() != ""]
    if not values:
        return math.nan
    return float(np.mean(values))


def absolute_lift(control_rows: list[dict[str, str]], treatment_rows: list[dict[str, str]], metric_type: str) -> float:
    control = statistic(control_rows, metric_type)
    treatment = statistic(treatment_rows, metric_type)
    if not math.isfinite(control) or not math.isfinite(treatment):
        return math.nan
    return treatment - control


def resample_rows(rows: list[dict[str, str]], rng: np.random.Generator) -> list[dict[str, str]]:
    if not rows:
        return []
    indices = rng.integers(0, len(rows), size=len(rows))
    return [rows[int(index)] for index in indices]


def percentile_interval(values: list[float], confidence_level: float) -> tuple[float, float]:
    alpha = 1 - confidence_level
    return (
        float(np.quantile(values, alpha / 2)),
        float(np.quantile(values, 1 - alpha / 2)),
    )


def bootstrap_distribution(
    metric_id: str,
    metric_type: str,
    control_rows: list[dict[str, str]],
    treatment_rows: list[dict[str, str]],
    n_resamples: int,
    rng: np.random.Generator,
) -> tuple[list[dict[str, Any]], list[float], int]:
    rows: list[dict[str, Any]] = []
    valid_values: list[float] = []
    invalid = 0
    for index in range(n_resamples):
        control_sample = resample_rows(control_rows, rng)
        treatment_sample = resample_rows(treatment_rows, rng)
        control_statistic = statistic(control_sample, metric_type)
        treatment_statistic = statistic(treatment_sample, metric_type)
        lift = treatment_statistic - control_statistic
        valid = math.isfinite(lift)
        if valid:
            valid_values.append(float(lift))
        else:
            invalid += 1
        rows.append(
            {
                "metric_id": metric_id,
                "resample_index": index,
                "control_statistic": round_float(control_statistic),
                "treatment_statistic": round_float(treatment_statistic),
                "bootstrap_absolute_lift": round_float(lift),
                "valid": valid,
            }
        )
    return rows, valid_values, invalid


def permutation_p_value(
    metric_type: str,
    control_rows: list[dict[str, str]],
    treatment_rows: list[dict[str, str]],
    n_resamples: int,
    rng: np.random.Generator,
) -> tuple[float, int]:
    observed = absolute_lift(control_rows, treatment_rows, metric_type)
    if not math.isfinite(observed):
        return math.nan, 0
    combined = control_rows + treatment_rows
    treatment_n = len(treatment_rows)
    if treatment_n == 0 or len(control_rows) == 0:
        return math.nan, 0
    extreme = 0
    valid = 0
    for _ in range(n_resamples):
        indices = rng.permutation(len(combined))
        treatment_sample = [combined[int(index)] for index in indices[:treatment_n]]
        control_sample = [combined[int(index)] for index in indices[treatment_n:]]
        lift = absolute_lift(control_sample, treatment_sample, metric_type)
        if not math.isfinite(lift):
            continue
        valid += 1
        if abs(lift) >= abs(observed):
            extreme += 1
    if valid == 0:
        return math.nan, 0
    return (extreme + 1) / (valid + 1), valid


def scipy_bootstrap_check(
    metric_type: str,
    control_rows: list[dict[str, str]],
    treatment_rows: list[dict[str, str]],
    confidence_level: float,
    n_resamples: int,
    seed: int,
) -> dict[str, Any]:
    if metric_type == "ratio":
        return {
            "method": "manual_only_for_paired_denominator_ratio",
            "valid": True,
            "ci_low": "",
            "ci_high": "",
        }
    control_values = np.array([parse_float(row["value"]) for row in control_rows], dtype=float)
    treatment_values = np.array([parse_float(row["value"]) for row in treatment_rows], dtype=float)
    if len(control_values) == 0 or len(treatment_values) == 0:
        return {"method": "scipy.stats.bootstrap", "valid": False, "ci_low": "", "ci_high": ""}

    def statistic_fn(treatment: np.ndarray, control: np.ndarray) -> float:
        return float(np.mean(treatment) - np.mean(control))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = stats.bootstrap(
            (treatment_values, control_values),
            statistic_fn,
            n_resamples=n_resamples,
            confidence_level=confidence_level,
            method="percentile",
            paired=False,
            vectorized=False,
            rng=np.random.default_rng(seed),
        )
    return {
        "method": "scipy.stats.bootstrap_percentile",
        "valid": True,
        "ci_low": round_float(float(result.confidence_interval.low)),
        "ci_high": round_float(float(result.confidence_interval.high)),
    }


def zero_denominator_count(rows: list[dict[str, str]]) -> int:
    return sum(1 for row in rows if parse_float(row["denominator"]) <= 0)


def unique_value_count(values: list[float]) -> int:
    return len({round(value, 12) for value in values})


def interval_status(
    metric_type: str,
    control_rows: list[dict[str, str]],
    treatment_rows: list[dict[str, str]],
    valid_bootstrap: list[float],
    invalid_resamples: int,
    bootstrap_spec: dict[str, Any],
) -> tuple[str, list[str]]:
    warnings_list: list[str] = []
    if len(control_rows) < int(bootstrap_spec["minimum_units_per_variant"]):
        warnings_list.append("control_sample_below_minimum_units")
    if len(treatment_rows) < int(bootstrap_spec["minimum_units_per_variant"]):
        warnings_list.append("treatment_sample_below_minimum_units")
    if invalid_resamples > 0:
        warnings_list.append("invalid_denominator_resamples")
    if valid_bootstrap and unique_value_count(valid_bootstrap) <= int(bootstrap_spec["degenerate_unique_value_threshold"]):
        warnings_list.append("degenerate_bootstrap_distribution")
    if metric_type == "ratio" and (zero_denominator_count(control_rows) > 0 or zero_denominator_count(treatment_rows) > 0):
        warnings_list.append("paired_denominator_contains_zero_units")
    return ("warning" if warnings_list else "ready"), warnings_list


def analyze_metric(
    protocol: dict[str, Any],
    effect_rows: dict[str, dict[str, str]],
    observations: list[dict[str, str]],
    metric_config: dict[str, Any],
    bootstrap_spec: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    control_id, treatment_id = ordered_variants(protocol)
    metric_id = metric_config["metric_id"]
    effect = effect_rows[metric_id]
    metric_type = effect["metric_type"]
    control_rows = observations_for_metric(observations, metric_id, control_id, metric_type)
    treatment_rows = observations_for_metric(observations, metric_id, treatment_id, metric_type)
    observed_lift = absolute_lift(control_rows, treatment_rows, metric_type)
    bootstrap_rng = np.random.default_rng(int(bootstrap_spec["bootstrap_seed"]) + int(metric_config["seed_offset"]))
    permutation_rng = np.random.default_rng(int(bootstrap_spec["permutation_seed"]) + int(metric_config["seed_offset"]))
    distribution, valid_bootstrap, invalid_resamples = bootstrap_distribution(
        metric_id,
        metric_type,
        control_rows,
        treatment_rows,
        int(bootstrap_spec["n_resamples"]),
        bootstrap_rng,
    )
    if valid_bootstrap:
        ci_low, ci_high = percentile_interval(valid_bootstrap, float(bootstrap_spec["confidence_level"]))
    else:
        ci_low, ci_high = math.nan, math.nan
    permutation_p, permutation_valid = permutation_p_value(
        metric_type,
        control_rows,
        treatment_rows,
        int(bootstrap_spec["permutation_resamples"]),
        permutation_rng,
    )
    status, warning_ids = interval_status(
        metric_type,
        control_rows,
        treatment_rows,
        valid_bootstrap,
        invalid_resamples,
        bootstrap_spec,
    )
    scipy_check = scipy_bootstrap_check(
        metric_type,
        control_rows,
        treatment_rows,
        float(bootstrap_spec["confidence_level"]),
        int(bootstrap_spec["n_resamples"]),
        int(bootstrap_spec["scipy_seed"]) + int(metric_config["seed_offset"]),
    )
    interval = {
        "metric_id": metric_id,
        "role": effect["role"],
        "metric_type": metric_type,
        "resampling_unit": bootstrap_spec["resampling_unit"],
        "paired_denominator": metric_type == "ratio",
        "method": "manual_percentile_bootstrap_by_variant",
        "observed_absolute_lift": round_float(observed_lift),
        "effect_table_absolute_lift": round_float(parse_float(effect["absolute_lift"])),
        "ci_low": round_float(ci_low),
        "ci_high": round_float(ci_high),
        "confidence_level": float(bootstrap_spec["confidence_level"]),
        "interval_contains_zero": bool(ci_low <= 0 <= ci_high) if math.isfinite(ci_low) and math.isfinite(ci_high) else True,
        "valid_resamples": len(valid_bootstrap),
        "invalid_resamples": invalid_resamples,
        "permutation_method": "label_shuffle_fixed_group_sizes",
        "permutation_p_value": round_float(permutation_p),
        "permutation_valid_resamples": permutation_valid,
        "control_units": len(control_rows),
        "treatment_units": len(treatment_rows),
        "control_zero_denominator_units": zero_denominator_count(control_rows),
        "treatment_zero_denominator_units": zero_denominator_count(treatment_rows),
        "unique_bootstrap_lifts": unique_value_count(valid_bootstrap),
        "scipy_check": scipy_check,
        "diagnostics": warning_ids,
        "status": status,
    }
    return interval, distribution


def build_report(
    protocol: dict[str, Any],
    bootstrap_spec: dict[str, Any],
    observations: list[dict[str, str]],
    effect_results: list[dict[str, str]],
    assumption_checks: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if assumption_checks.get("valid") is not True:
        report = {
            "valid": False,
            "ready_for_decision": False,
            "summary": {
                "experiment_id": protocol["experiment_id"],
                "metrics_analyzed": 0,
                "blocking_failures": ["upstream_effect_analysis_not_valid"],
                "warning_metrics": [],
            },
            "intervals": [],
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
        manifest = build_manifest(protocol, bootstrap_spec, report)
        return report, [], manifest

    effect_map = effect_by_metric(effect_results)
    intervals: list[dict[str, Any]] = []
    distribution_rows: list[dict[str, Any]] = []
    checks = [
        {
            "id": "upstream_effect_analysis_valid",
            "severity": "error",
            "valid": True,
            "observed": True,
            "expected": True,
        },
        {
            "id": "resampling_unit_matches_protocol",
            "severity": "error",
            "valid": bootstrap_spec["resampling_unit"] == protocol["analysis_unit"] == protocol["randomization_unit"],
            "observed": {
                "resampling_unit": bootstrap_spec["resampling_unit"],
                "analysis_unit": protocol["analysis_unit"],
                "randomization_unit": protocol["randomization_unit"],
            },
            "expected": "all are the same unit for this two-arm user-level experiment",
        },
    ]
    for metric_config in bootstrap_spec["metrics"]:
        metric_id = metric_config["metric_id"]
        if metric_id not in effect_map:
            checks.append(
                {
                    "id": f"{metric_id}:effect_result_exists",
                    "severity": "error",
                    "valid": False,
                    "observed": list(effect_map),
                    "expected": metric_id,
                }
            )
            continue
        interval, distribution = analyze_metric(protocol, effect_map, observations, metric_config, bootstrap_spec)
        intervals.append(interval)
        distribution_rows.extend(distribution)
        checks.append(
            {
                "id": f"{metric_id}:effect_table_matches_observations",
                "metric_id": metric_id,
                "severity": "error",
                "valid": interval["observed_absolute_lift"] == interval["effect_table_absolute_lift"],
                "observed": interval["observed_absolute_lift"],
                "expected": interval["effect_table_absolute_lift"],
            }
        )
        checks.append(
            {
                "id": f"{metric_id}:bootstrap_has_valid_resamples",
                "metric_id": metric_id,
                "severity": "error",
                "valid": interval["valid_resamples"] >= int(bootstrap_spec["minimum_valid_resamples"]),
                "observed": interval["valid_resamples"],
                "expected": f">= {bootstrap_spec['minimum_valid_resamples']}",
            }
        )
    blocking_failures = [check["id"] for check in checks if check["severity"] == "error" and not check["valid"]]
    warning_metrics = [row["metric_id"] for row in intervals if row["status"] == "warning"]
    report = {
        "valid": not blocking_failures,
        "ready_for_decision": False,
        "summary": {
            "experiment_id": protocol["experiment_id"],
            "metrics_analyzed": len(intervals),
            "resampling_unit": bootstrap_spec["resampling_unit"],
            "n_resamples": int(bootstrap_spec["n_resamples"]),
            "permutation_resamples": int(bootstrap_spec["permutation_resamples"]),
            "confidence_level": float(bootstrap_spec["confidence_level"]),
            "blocking_failures": blocking_failures,
            "warning_metrics": warning_metrics,
            "upstream_ready_for_decision": assumption_checks.get("ready_for_decision"),
        },
        "intervals": intervals,
        "checks": checks,
    }
    manifest = build_manifest(protocol, bootstrap_spec, report)
    return report, distribution_rows, manifest


def build_manifest(protocol: dict[str, Any], bootstrap_spec: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact": "experiment-bootstrap-analyzer",
        "experiment_id": protocol["experiment_id"],
        "scipy_version": scipy.__version__,
        "resampling_unit": bootstrap_spec["resampling_unit"],
        "bootstrap_seed": int(bootstrap_spec["bootstrap_seed"]),
        "permutation_seed": int(bootstrap_spec["permutation_seed"]),
        "scipy_seed": int(bootstrap_spec["scipy_seed"]),
        "n_resamples": int(bootstrap_spec["n_resamples"]),
        "permutation_resamples": int(bootstrap_spec["permutation_resamples"]),
        "metrics": [row["metric_id"] for row in report.get("intervals", [])],
        "paired_denominator_metrics": [
            row["metric_id"] for row in report.get("intervals", []) if row.get("paired_denominator") is True
        ],
        "valid": report["valid"],
    }


def run(
    protocol_path: Path,
    bootstrap_spec_path: Path,
    observations_path: Path,
    effect_results_path: Path,
    assumption_checks_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    return build_report(
        read_json(protocol_path),
        read_json(bootstrap_spec_path),
        read_csv(observations_path),
        read_csv(effect_results_path),
        read_json(assumption_checks_path),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap and permutation sensitivity for experiment effects.")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--bootstrap-spec", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--effect-results", type=Path, required=True)
    parser.add_argument("--assumption-checks", type=Path, required=True)
    parser.add_argument("--output-report", type=Path)
    parser.add_argument("--output-distribution", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report, distribution, manifest = run(
        args.protocol,
        args.bootstrap_spec,
        args.observations,
        args.effect_results,
        args.assumption_checks,
    )
    if args.output_report is not None:
        write_json(args.output_report, report)
    if args.output_distribution is not None:
        write_csv(args.output_distribution, distribution, DISTRIBUTION_FIELDS)
    if args.output_manifest is not None:
        write_json(args.output_manifest, manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
