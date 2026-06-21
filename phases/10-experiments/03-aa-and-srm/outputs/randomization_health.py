from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from scipy import stats


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


def parse_float(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value.strip() == "":
        raise ValueError("empty numeric value")
    return float(value)


def round_float(value: float, digits: int = 6) -> float | str:
    if math.isinf(value):
        return "inf"
    if math.isnan(value):
        return "nan"
    return round(value, digits)


def check_result(
    check_id: str,
    severity: str,
    valid: bool,
    observed: Any = None,
    expected: Any = None,
    sample: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": valid,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def variant_ids(protocol: dict[str, Any]) -> list[str]:
    variants = protocol.get("variants")
    if not isinstance(variants, list):
        raise ValueError("protocol variants must be a list")
    result = [str(item["variant_id"]) for item in variants]
    if len(result) < 2:
        raise ValueError("at least two variants are required")
    return result


def control_and_treatment(protocol: dict[str, Any]) -> tuple[str, str]:
    variants = protocol.get("variants", [])
    control = next((str(item["variant_id"]) for item in variants if item.get("is_control") is True), None)
    ids = variant_ids(protocol)
    treatment = next((variant_id for variant_id in ids if variant_id != control), None)
    if control is None or treatment is None:
        raise ValueError("exactly one control and at least one treatment variant are required")
    return control, treatment


def count_by_variant(rows: list[dict[str, Any]], variants: list[str]) -> dict[str, int]:
    counts = Counter(str(row.get("variant_id", "")) for row in rows)
    return {variant_id: counts.get(variant_id, 0) for variant_id in variants}


def expected_counts(total: int, protocol: dict[str, Any], variants: list[str]) -> dict[str, float]:
    allocation = protocol.get("traffic_allocation")
    if not isinstance(allocation, dict):
        raise ValueError("protocol traffic_allocation must be an object")
    return {variant_id: total * parse_float(allocation[variant_id]) for variant_id in variants}


def srm_check(
    rows: list[dict[str, Any]],
    protocol: dict[str, Any],
    health_spec: dict[str, Any],
    check_id: str,
) -> dict[str, Any]:
    variants = variant_ids(protocol)
    observed = count_by_variant(rows, variants)
    total = sum(observed.values())
    if total == 0:
        return check_result(check_id, "error", False, observed, "non-empty assignment or exposure rows")
    expected = expected_counts(total, protocol, variants)
    statistic, p_value = stats.chisquare(
        f_obs=[observed[variant_id] for variant_id in variants],
        f_exp=[expected[variant_id] for variant_id in variants],
    )
    alpha = parse_float(health_spec["srm_alpha"])
    min_expected = min(expected.values()) if expected else 0.0
    sample = [
        {
            "variant_id": variant_id,
            "observed": observed[variant_id],
            "expected": round_float(expected[variant_id]),
            "observed_share": round_float(observed[variant_id] / total),
            "expected_share": round_float(expected[variant_id] / total),
        }
        for variant_id in variants
    ]
    valid = float(p_value) >= alpha
    return check_result(
        check_id,
        "error",
        valid,
        {
            "counts": observed,
            "total": total,
            "chi_square": round_float(float(statistic)),
            "p_value": round_float(float(p_value)),
            "min_expected_count": round_float(min_expected),
        },
        {"alpha": alpha, "allocation": protocol["traffic_allocation"]},
        sample,
    )


def telemetry_loss_check(
    assignments: list[dict[str, Any]],
    exposures: list[dict[str, Any]],
    protocol: dict[str, Any],
    health_spec: dict[str, Any],
) -> dict[str, Any]:
    variants = variant_ids(protocol)
    assigned_units = {str(row["assignment_unit_id"]) for row in assignments}
    exposed_units = [str(row.get("assignment_unit_id", "")) for row in exposures]
    exposure_counts = Counter(exposed_units)
    duplicate_exposure_units = sorted(unit_id for unit_id, count in exposure_counts.items() if unit_id and count > 1)
    exposed_unit_set = {unit_id for unit_id in exposed_units if unit_id}
    missing_units = sorted(assigned_units - exposed_unit_set)
    extra_units = sorted(exposed_unit_set - assigned_units)
    assignment_by_variant = count_by_variant(assignments, variants)
    exposure_by_variant = count_by_variant(exposures, variants)
    by_variant: list[dict[str, Any]] = []
    missing_rates: list[float] = []
    for variant_id in variants:
        assigned = assignment_by_variant[variant_id]
        exposed = exposure_by_variant[variant_id]
        missing = max(assigned - exposed, 0)
        missing_rate = missing / assigned if assigned else 0.0
        missing_rates.append(missing_rate)
        by_variant.append(
            {
                "variant_id": variant_id,
                "assigned": assigned,
                "exposed": exposed,
                "missing": missing,
                "missing_rate": round_float(missing_rate),
                "exposure_rate": round_float(exposed / assigned if assigned else 0.0),
            }
        )
    overall_missing_rate = len(missing_units) / len(assigned_units) if assigned_units else 0.0
    variant_gap = max(missing_rates) - min(missing_rates) if missing_rates else 0.0
    valid = (
        not duplicate_exposure_units
        and not extra_units
        and overall_missing_rate <= parse_float(health_spec["max_missing_exposure_rate"])
        and variant_gap <= parse_float(health_spec["max_variant_missing_rate_gap"])
    )
    return check_result(
        "telemetry_loss_by_variant",
        "error",
        valid,
        {
            "assigned_units": len(assigned_units),
            "exposed_units": len(exposed_unit_set),
            "missing_units": len(missing_units),
            "extra_exposure_units": len(extra_units),
            "duplicate_exposure_units": duplicate_exposure_units,
            "overall_missing_rate": round_float(overall_missing_rate),
            "variant_missing_rate_gap": round_float(variant_gap),
        },
        {
            "max_missing_exposure_rate": health_spec["max_missing_exposure_rate"],
            "max_variant_missing_rate_gap": health_spec["max_variant_missing_rate_gap"],
        },
        by_variant + [{"missing_units": missing_units[:5], "extra_units": extra_units[:5]}],
    )


def pre_metric_rows_by_user(
    pre_metrics: list[dict[str, str]],
    experiment_id: str,
) -> dict[str, dict[str, str]]:
    return {row["user_id"]: row for row in pre_metrics if row.get("experiment_id") == experiment_id}


def pre_experiment_metrics_complete_check(
    assignments: list[dict[str, Any]],
    pre_metrics: list[dict[str, str]],
    protocol: dict[str, Any],
    health_spec: dict[str, Any],
) -> dict[str, Any]:
    experiment_id = str(protocol["experiment_id"])
    metrics_by_user = pre_metric_rows_by_user(pre_metrics, experiment_id)
    assigned_users = sorted(str(row["user_id"]) for row in assignments)
    columns = sorted(
        set(health_spec["covariate_balance"]["columns"])
        | set(health_spec["aa_pseudo_outcomes"]["columns"])
    )
    missing_users = [user_id for user_id in assigned_users if user_id not in metrics_by_user]
    missing_columns = [
        column
        for column in columns
        if any(column not in metrics_by_user.get(user_id, {}) for user_id in assigned_users if user_id in metrics_by_user)
    ]
    valid = not missing_users and not missing_columns
    return check_result(
        "pre_experiment_metrics_complete",
        "error",
        valid,
        {"assigned_users": len(assigned_users), "metric_rows": len(metrics_by_user), "missing_users": missing_users, "missing_columns": missing_columns},
        "one pre-treatment metric row with declared columns for every assigned user",
        [{"missing_users": missing_users[:5], "missing_columns": missing_columns[:5]}],
    )


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot calculate mean for empty values")
    return sum(values) / len(values)


def sample_variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = mean(values)
    return sum((value - avg) ** 2 for value in values) / (len(values) - 1)


def standardized_mean_difference(control_values: list[float], treatment_values: list[float]) -> float:
    control_mean = mean(control_values)
    treatment_mean = mean(treatment_values)
    pooled_sd = math.sqrt((sample_variance(control_values) + sample_variance(treatment_values)) / 2)
    diff = treatment_mean - control_mean
    if pooled_sd == 0:
        return 0.0 if diff == 0 else math.inf
    return diff / pooled_sd


def values_by_variant(
    assignments: list[dict[str, Any]],
    pre_metrics: list[dict[str, str]],
    protocol: dict[str, Any],
    column: str,
) -> dict[str, list[float]]:
    experiment_id = str(protocol["experiment_id"])
    metrics_by_user = pre_metric_rows_by_user(pre_metrics, experiment_id)
    result: dict[str, list[float]] = {variant_id: [] for variant_id in variant_ids(protocol)}
    for assignment in assignments:
        user_id = str(assignment["user_id"])
        metric_row = metrics_by_user[user_id]
        result[str(assignment["variant_id"])].append(parse_float(metric_row[column]))
    return result


def covariate_balance_check(
    assignments: list[dict[str, Any]],
    pre_metrics: list[dict[str, str]],
    protocol: dict[str, Any],
    health_spec: dict[str, Any],
) -> dict[str, Any]:
    control, treatment = control_and_treatment(protocol)
    balance_spec = health_spec["covariate_balance"]
    threshold = parse_float(balance_spec["max_abs_standardized_difference"])
    sample: list[dict[str, Any]] = []
    offenders: list[str] = []
    for column in balance_spec["columns"]:
        grouped = values_by_variant(assignments, pre_metrics, protocol, column)
        control_values = grouped[control]
        treatment_values = grouped[treatment]
        if not control_values or not treatment_values:
            offenders.append(column)
            sample.append(
                {
                    "column": column,
                    "reason": "empty variant cell",
                    "control_n": len(control_values),
                    "treatment_n": len(treatment_values),
                }
            )
            continue
        smd = standardized_mean_difference(control_values, treatment_values)
        row = {
            "column": column,
            "control_mean": round_float(mean(control_values)),
            "treatment_mean": round_float(mean(treatment_values)),
            "standardized_mean_difference": round_float(smd),
            "abs_standardized_mean_difference": round_float(abs(smd)),
            "control_n": len(control_values),
            "treatment_n": len(treatment_values),
        }
        if abs(smd) > threshold:
            offenders.append(column)
        sample.append(row)
    return check_result(
        "covariate_balance_standardized_difference",
        str(balance_spec.get("severity", "warning")),
        not offenders,
        {"offending_columns": offenders, "columns_checked": len(sample)},
        f"absolute standardized mean difference <= {threshold}",
        sample,
    )


def exact_permutation_p_value(control_values: list[float], treatment_values: list[float]) -> tuple[float, int, float]:
    values = control_values + treatment_values
    n = len(values)
    treatment_n = len(treatment_values)
    observed = mean(treatment_values) - mean(control_values)
    total = 0
    extreme = 0
    all_indices = range(n)
    for treatment_indices_tuple in itertools.combinations(all_indices, treatment_n):
        treatment_indices = set(treatment_indices_tuple)
        perm_treatment = [values[index] for index in all_indices if index in treatment_indices]
        perm_control = [values[index] for index in all_indices if index not in treatment_indices]
        diff = mean(perm_treatment) - mean(perm_control)
        total += 1
        if abs(diff) >= abs(observed) - 1e-12:
            extreme += 1
    return extreme / total, total, observed


def aa_pseudo_outcome_check(
    assignments: list[dict[str, Any]],
    pre_metrics: list[dict[str, str]],
    protocol: dict[str, Any],
    health_spec: dict[str, Any],
) -> dict[str, Any]:
    control, treatment = control_and_treatment(protocol)
    aa_spec = health_spec["aa_pseudo_outcomes"]
    alpha = parse_float(health_spec["aa_alpha"])
    sample: list[dict[str, Any]] = []
    offenders: list[str] = []
    for column in aa_spec["columns"]:
        grouped = values_by_variant(assignments, pre_metrics, protocol, column)
        control_values = grouped[control]
        treatment_values = grouped[treatment]
        if not control_values or not treatment_values:
            offenders.append(column)
            sample.append(
                {
                    "column": column,
                    "reason": "empty variant cell",
                    "control_n": len(control_values),
                    "treatment_n": len(treatment_values),
                }
            )
            continue
        p_value, permutations, observed_diff = exact_permutation_p_value(control_values, treatment_values)
        row = {
            "column": column,
            "control_mean": round_float(mean(control_values)),
            "treatment_mean": round_float(mean(treatment_values)),
            "observed_difference": round_float(observed_diff),
            "p_value": round_float(p_value),
            "permutations": permutations,
        }
        if p_value < alpha:
            offenders.append(column)
        sample.append(row)
    return check_result(
        "aa_pre_experiment_pseudo_outcomes",
        str(aa_spec.get("severity", "warning")),
        not offenders,
        {"offending_columns": offenders, "columns_checked": len(sample)},
        f"exact two-sided permutation p-value >= {alpha}",
        sample,
    )


def build_report(
    assignments: list[dict[str, Any]],
    exposures: list[dict[str, Any]],
    pre_metrics: list[dict[str, str]],
    protocol: dict[str, Any],
    health_spec: dict[str, Any],
) -> dict[str, Any]:
    checks = [
        srm_check(assignments, protocol, health_spec, "assignment_srm_chi_square"),
        srm_check(exposures, protocol, health_spec, "exposure_srm_chi_square"),
        telemetry_loss_check(assignments, exposures, protocol, health_spec),
        pre_experiment_metrics_complete_check(assignments, pre_metrics, protocol, health_spec),
    ]
    if checks[-1]["valid"]:
        checks.append(covariate_balance_check(assignments, pre_metrics, protocol, health_spec))
        checks.append(aa_pseudo_outcome_check(assignments, pre_metrics, protocol, health_spec))
    blocking_failures = [check["id"] for check in checks if check["severity"] == "error" and not check["valid"]]
    warnings = [check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]]
    assignment_counts = count_by_variant(assignments, variant_ids(protocol))
    exposure_counts = count_by_variant(exposures, variant_ids(protocol))
    return {
        "valid": not blocking_failures,
        "ready_for_ab_analysis": not blocking_failures,
        "checks": checks,
        "summary": {
            "experiment_id": protocol["experiment_id"],
            "assignment_units": len({str(row["assignment_unit_id"]) for row in assignments}),
            "exposure_units": len({str(row["assignment_unit_id"]) for row in exposures}),
            "assignment_variant_counts": assignment_counts,
            "exposure_variant_counts": exposure_counts,
            "blocking_failures": blocking_failures,
            "warning_checks": warnings,
        },
    }


def run(
    assignments_path: Path,
    exposures_path: Path,
    pre_metrics_path: Path,
    protocol_path: Path,
    health_spec_path: Path,
) -> dict[str, Any]:
    assignments = read_csv(assignments_path)
    exposures = read_csv(exposures_path)
    pre_metrics = read_csv(pre_metrics_path)
    protocol = read_json(protocol_path)
    health_spec = read_json(health_spec_path)
    if health_spec.get("experiment_id") != protocol.get("experiment_id"):
        raise ValueError("health spec experiment_id must match protocol")
    return build_report(assignments, exposures, pre_metrics, protocol, health_spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run A/A, SRM and randomization health diagnostics before A/B analysis")
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--exposures", type=Path, required=True)
    parser.add_argument("--pre-metrics", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--health-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run(args.assignments, args.exposures, args.pre_metrics, args.protocol, args.health_spec)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        write_json(args.output, report)
    print(rendered, end="")
    if report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
