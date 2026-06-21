from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import scipy
import statsmodels
from scipy import stats
from statsmodels.stats.multitest import multipletests


ADJUSTED_RESULT_FIELDS = [
    "hypothesis_id",
    "metric_id",
    "family",
    "role",
    "source",
    "method",
    "raw_p_value",
    "adjusted_p_value",
    "reject_raw",
    "reject_adjusted",
    "gate_status",
    "decision_eligible",
    "decision_reason",
    "effect_source",
    "effect_estimate",
    "effect_p_value_source",
    "diagnostics",
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


def effect_by_metric(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["metric_id"]: row for row in rows}


def cuped_by_metric(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["metric_id"]: row for row in rows}


def bootstrap_by_metric(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["metric_id"]: row for row in report.get("intervals", [])}


def family_names(protocol: dict[str, Any]) -> dict[str, list[str]]:
    policy = protocol["multiple_testing_policy"]
    return {
        "primary": list(policy.get("primary_family", [])),
        "guardrail": list(policy.get("guardrail_family", [])),
        "secondary": list(policy.get("secondary_family", [])),
        "exploratory": list(protocol.get("exploratory_metrics", [])),
    }


def policy_family_names(policy_spec: dict[str, Any]) -> dict[str, list[str]]:
    return {
        family["name"]: list(family.get("hypotheses", []))
        for family in policy_spec.get("families", [])
    }


def method_for_family(policy_spec: dict[str, Any], family_name: str) -> str:
    for family in policy_spec["families"]:
        if family["name"] == family_name:
            return family["method"]
    raise KeyError(f"unknown family {family_name}")


def metric_family_audit(protocol: dict[str, Any], policy_spec: dict[str, Any], effect_map: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    protocol_families = family_names(protocol)
    spec_families = policy_family_names(policy_spec)
    checks: list[dict[str, Any]] = []
    for family in ("primary", "guardrail", "secondary"):
        checks.append(
            {
                "id": f"{family}_family_matches_protocol",
                "severity": "error",
                "valid": spec_families.get(family, []) == protocol_families.get(family, []),
                "observed": spec_families.get(family, []),
                "expected": protocol_families.get(family, []),
            }
        )
        missing = [metric_id for metric_id in spec_families.get(family, []) if metric_id not in effect_map]
        checks.append(
            {
                "id": f"{family}_family_effect_results_exist",
                "severity": "error",
                "valid": not missing,
                "observed": missing,
                "expected": "every decision-family metric has an effect result",
            }
        )
    decision_members: list[str] = []
    for family in ("primary", "guardrail", "secondary"):
        decision_members.extend(spec_families.get(family, []))
    duplicates = sorted({metric_id for metric_id in decision_members if decision_members.count(metric_id) > 1})
    checks.append(
        {
            "id": "decision_metric_belongs_to_one_family",
            "severity": "error",
            "valid": not duplicates,
            "observed": duplicates,
            "expected": "no duplicate metric_id across primary, guardrail and secondary families",
        }
    )
    allowed_methods = {"none", "bonferroni", "holm", "fdr_bh"}
    methods = {family["name"]: family["method"] for family in policy_spec.get("families", [])}
    invalid_methods = {name: method for name, method in methods.items() if method not in allowed_methods}
    checks.append(
        {
            "id": "family_methods_are_supported",
            "severity": "error",
            "valid": not invalid_methods,
            "observed": invalid_methods,
            "expected": sorted(allowed_methods),
        }
    )
    return checks


def exploratory_candidate_audit(protocol: dict[str, Any], policy_spec: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    predeclared_dimensions = set(protocol.get("segment_policy", {}).get("predeclared_dimensions", []))
    for candidate in policy_spec.get("exploratory_candidates", []):
        dimension = candidate.get("segment_dimension")
        checks.append(
            {
                "id": f"{candidate['hypothesis_id']}:segment_dimension_predeclared",
                "hypothesis_id": candidate["hypothesis_id"],
                "severity": "warning",
                "valid": dimension in predeclared_dimensions,
                "observed": dimension,
                "expected": sorted(predeclared_dimensions),
            }
        )
        checks.append(
            {
                "id": f"{candidate['hypothesis_id']}:excluded_from_launch_decision",
                "hypothesis_id": candidate["hypothesis_id"],
                "severity": "error",
                "valid": candidate.get("decision_use") == "exploratory_only",
                "observed": candidate.get("decision_use"),
                "expected": "exploratory_only",
            }
        )
    return checks


def holm_adjust(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    order = sorted(range(len(p_values)), key=lambda index: p_values[index])
    adjusted_sorted: list[float] = []
    running = 0.0
    total = len(p_values)
    for rank, original_index in enumerate(order, start=1):
        value = min(1.0, (total - rank + 1) * p_values[original_index])
        running = max(running, value)
        adjusted_sorted.append(running)
    adjusted = [0.0] * len(p_values)
    for sorted_value, original_index in zip(adjusted_sorted, order, strict=True):
        adjusted[original_index] = min(1.0, sorted_value)
    return adjusted


def bonferroni_adjust(p_values: list[float]) -> list[float]:
    total = len(p_values)
    return [min(1.0, value * total) for value in p_values]


def bh_adjust(p_values: list[float]) -> list[float]:
    if not p_values:
        return []
    order = sorted(range(len(p_values)), key=lambda index: p_values[index], reverse=True)
    total = len(p_values)
    running = 1.0
    adjusted = [0.0] * len(p_values)
    for reverse_rank, original_index in enumerate(order, start=1):
        rank = total - reverse_rank + 1
        value = min(running, p_values[original_index] * total / rank)
        running = value
        adjusted[original_index] = min(1.0, value)
    return adjusted


def adjust_p_values(p_values: list[float], method: str) -> list[float]:
    if method == "none":
        return p_values[:]
    if method == "bonferroni":
        return bonferroni_adjust(p_values)
    if method == "holm":
        return holm_adjust(p_values)
    if method == "fdr_bh":
        return bh_adjust(p_values)
    raise ValueError(f"unsupported method: {method}")


def statsmodels_adjust(p_values: list[float], method: str, alpha: float) -> list[float]:
    if method == "none" or not p_values:
        return p_values[:]
    _, corrected, _, _ = multipletests(p_values, alpha=alpha, method=method)
    return [float(value) for value in corrected]


def scipy_fdr_adjust(p_values: list[float], method: str) -> list[float]:
    if method != "fdr_bh" or not p_values:
        return []
    return [float(value) for value in stats.false_discovery_control(np.array(p_values, dtype=float), method="bh")]


def effect_estimate_for_metric(effect: dict[str, str], cuped_map: dict[str, dict[str, str]]) -> tuple[str, float, float, str]:
    metric_id = effect["metric_id"]
    cuped = cuped_map.get(metric_id)
    if cuped is not None and cuped.get("apply_to_decision") == "true":
        return "cuped_sensitivity", parse_float(cuped["adjusted_absolute_lift"]), parse_float(cuped["p_value"]), "cuped_effects"
    return "raw_effect", parse_float(effect["absolute_lift"]), parse_float(effect["p_value"]), "effect_results"


def build_decision_hypotheses(
    policy_spec: dict[str, Any],
    effect_map: dict[str, dict[str, str]],
    cuped_map: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    for family in policy_spec["families"]:
        family_name = family["name"]
        if family_name == "exploratory":
            continue
        for metric_id in family.get("hypotheses", []):
            effect = effect_map.get(metric_id)
            if effect is None:
                continue
            effect_source, estimate, sensitivity_p_value, sensitivity_source = effect_estimate_for_metric(effect, cuped_map)
            hypotheses.append(
                {
                    "hypothesis_id": metric_id,
                    "metric_id": metric_id,
                    "family": family_name,
                    "role": effect["role"],
                    "source": "effect_results",
                    "raw_p_value": parse_float(effect["p_value"]),
                    "effect_source": effect_source,
                    "effect_estimate": estimate,
                    "effect_p_value_source": f"raw_p_value; {sensitivity_source}_p_value={round_float(sensitivity_p_value)}",
                    "diagnostics": [],
                }
            )
    return hypotheses


def build_exploratory_hypotheses(policy_spec: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in policy_spec.get("exploratory_candidates", []):
        diagnostics: list[str] = []
        if candidate.get("decision_use") == "exploratory_only":
            diagnostics.append("exploratory_only_not_a_launch_gate")
        if candidate.get("post_hoc") is True:
            diagnostics.append("post_hoc_candidate")
        if candidate.get("segment_dimension") == "country":
            diagnostics.append("segment_dimension_not_predeclared")
        rows.append(
            {
                "hypothesis_id": candidate["hypothesis_id"],
                "metric_id": candidate["metric_id"],
                "family": "exploratory",
                "role": "exploratory",
                "source": candidate.get("source", "exploratory_candidate"),
                "raw_p_value": parse_float(candidate["p_value"]),
                "effect_source": "exploratory_candidate",
                "effect_estimate": parse_float(candidate["effect_estimate"]),
                "effect_p_value_source": "exploratory_candidate_p_value",
                "diagnostics": diagnostics,
            }
        )
    return rows


def apply_family_adjustments(
    hypotheses: list[dict[str, Any]],
    policy_spec: dict[str, Any],
    alpha: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    adjusted_rows: list[dict[str, Any]] = []
    family_order = [family["name"] for family in policy_spec["families"]]
    for family_name in family_order:
        family_rows = [row for row in hypotheses if row["family"] == family_name]
        method = method_for_family(policy_spec, family_name)
        p_values = [row["raw_p_value"] for row in family_rows]
        manual = adjust_p_values(p_values, method)
        statsmodels_values = statsmodels_adjust(p_values, method, alpha)
        scipy_values = scipy_fdr_adjust(p_values, method)
        checks.append(
            {
                "id": f"{family_name}:statsmodels_adjustment_matches_manual",
                "family": family_name,
                "severity": "error",
                "valid": [round_float(value) for value in manual] == [round_float(value) for value in statsmodels_values],
                "observed": [round_float(value) for value in manual],
                "expected": [round_float(value) for value in statsmodels_values],
            }
        )
        if method == "fdr_bh":
            checks.append(
                {
                    "id": f"{family_name}:scipy_fdr_matches_manual",
                    "family": family_name,
                    "severity": "error",
                    "valid": [round_float(value) for value in manual] == [round_float(value) for value in scipy_values],
                    "observed": [round_float(value) for value in manual],
                    "expected": [round_float(value) for value in scipy_values],
                }
            )
        for row, adjusted in zip(family_rows, manual, strict=True):
            new_row = dict(row)
            new_row["method"] = method
            new_row["adjusted_p_value"] = adjusted
            new_row["reject_raw"] = row["raw_p_value"] <= alpha
            new_row["reject_adjusted"] = adjusted <= alpha
            adjusted_rows.append(new_row)
    return adjusted_rows, checks


def apply_gatekeeping(
    rows: list[dict[str, Any]],
    effect_map: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    primary_rows = [row for row in rows if row["family"] == "primary"]
    primary_passed = all(row["reject_adjusted"] for row in primary_rows) and bool(primary_rows)
    primary_status = {
        row["metric_id"]: effect_map[row["metric_id"]].get("practical_status", "")
        for row in primary_rows
        if row["metric_id"] in effect_map
    }
    primary_meets_practical = all(status == "meets_primary_rule" for status in primary_status.values()) if primary_status else False
    primary_gate_passed = primary_passed and primary_meets_practical
    guardrail_rows = [row for row in rows if row["family"] == "guardrail"]
    adjusted_guardrail_breaches = [row["metric_id"] for row in guardrail_rows if row["reject_adjusted"]]
    guardrail_watch = [
        row["metric_id"]
        for row in guardrail_rows
        if row["metric_id"] in effect_map and effect_map[row["metric_id"]].get("guardrail_status") == "watch"
    ]
    guardrail_gate_clear = not adjusted_guardrail_breaches and not guardrail_watch
    secondary_adjusted_signals = [
        row["metric_id"] for row in rows if row["family"] == "secondary" and row["reject_adjusted"]
    ]
    exploratory_adjusted_signals = [
        row["hypothesis_id"] for row in rows if row["family"] == "exploratory" and row["reject_adjusted"]
    ]
    updated: list[dict[str, Any]] = []
    for row in rows:
        row = dict(row)
        if row["family"] == "primary":
            row["gate_status"] = "passed" if primary_gate_passed else "failed"
            row["decision_eligible"] = bool(primary_gate_passed)
            row["decision_reason"] = "primary_gate" if primary_gate_passed else "primary_not_successful"
        elif row["family"] == "guardrail":
            row["gate_status"] = "clear" if guardrail_gate_clear else "watch_or_breached"
            row["decision_eligible"] = bool(primary_gate_passed and guardrail_gate_clear)
            row["decision_reason"] = "guardrail_gate" if row["decision_eligible"] else "guardrails_not_cleared"
        elif row["family"] == "secondary":
            row["gate_status"] = "opened" if primary_gate_passed else "blocked_by_primary"
            row["decision_eligible"] = bool(primary_gate_passed and row["reject_adjusted"])
            row["decision_reason"] = "secondary_supporting_signal" if row["decision_eligible"] else "secondary_diagnostic_only"
            if not primary_gate_passed and row["reject_adjusted"]:
                row["diagnostics"] = [*row.get("diagnostics", []), "adjusted_secondary_signal_blocked_by_primary_gate"]
        else:
            row["gate_status"] = "exploratory_only"
            row["decision_eligible"] = False
            row["decision_reason"] = "not_pre_registered_launch_gate"
        updated.append(row)
    summary = {
        "primary_gate_passed": primary_gate_passed,
        "primary_adjusted_reject": primary_passed,
        "primary_practical_status": primary_status,
        "guardrail_gate_clear": guardrail_gate_clear,
        "adjusted_guardrail_breaches": adjusted_guardrail_breaches,
        "guardrail_watch_metrics": guardrail_watch,
        "secondary_adjusted_signals": secondary_adjusted_signals,
        "exploratory_adjusted_signals": exploratory_adjusted_signals,
        "launch_allowed_by_multiple_testing": primary_gate_passed and guardrail_gate_clear,
    }
    return updated, summary


def build_report(
    protocol: dict[str, Any],
    policy_spec: dict[str, Any],
    effect_results: list[dict[str, str]],
    bootstrap_report: dict[str, Any],
    cuped_report: dict[str, Any],
    cuped_effects: list[dict[str, str]],
    assumption_checks: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    effect_map = effect_by_metric(effect_results)
    cuped_map = cuped_by_metric(cuped_effects)
    checks: list[dict[str, Any]] = [
        {
            "id": "upstream_effect_analysis_valid",
            "severity": "error",
            "valid": assumption_checks.get("valid") is True,
            "observed": assumption_checks.get("valid"),
            "expected": True,
        },
        {
            "id": "upstream_bootstrap_valid",
            "severity": "error",
            "valid": bootstrap_report.get("valid") is True,
            "observed": bootstrap_report.get("valid"),
            "expected": True,
        },
        {
            "id": "upstream_cuped_valid",
            "severity": "error",
            "valid": cuped_report.get("valid") is True,
            "observed": cuped_report.get("valid"),
            "expected": True,
        },
    ]
    checks.extend(metric_family_audit(protocol, policy_spec, effect_map))
    checks.extend(exploratory_candidate_audit(protocol, policy_spec))
    decision_hypotheses = build_decision_hypotheses(policy_spec, effect_map, cuped_map)
    exploratory_hypotheses = build_exploratory_hypotheses(policy_spec)
    adjusted_rows, adjustment_checks = apply_family_adjustments(
        [*decision_hypotheses, *exploratory_hypotheses],
        policy_spec,
        float(policy_spec["alpha"]),
    )
    checks.extend(adjustment_checks)
    adjusted_rows, gate_summary = apply_gatekeeping(adjusted_rows, effect_map)
    blocking_failures = [check["id"] for check in checks if check["severity"] == "error" and not check["valid"]]
    warning_checks = [check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]]
    adjusted_rows = sorted(
        adjusted_rows,
        key=lambda row: (["primary", "guardrail", "secondary", "exploratory"].index(row["family"]), row["hypothesis_id"]),
    )
    report = {
        "valid": not blocking_failures,
        "ready_for_decision": False,
        "summary": {
            "experiment_id": protocol["experiment_id"],
            "alpha": float(policy_spec["alpha"]),
            "hypotheses_evaluated": len(adjusted_rows),
            "families": {
                family["name"]: {
                    "method": family["method"],
                    "hypotheses": family.get("hypotheses", []),
                }
                for family in policy_spec["families"]
            },
            "blocking_failures": blocking_failures,
            "warning_checks": warning_checks,
            **gate_summary,
        },
        "adjusted_results": adjusted_rows,
        "checks": checks,
    }
    manifest = build_manifest(protocol, policy_spec, report)
    return report, adjusted_rows, manifest


def build_manifest(protocol: dict[str, Any], policy_spec: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact": "multiple-testing-policy-checker",
        "experiment_id": protocol["experiment_id"],
        "scipy_version": scipy.__version__,
        "statsmodels_version": statsmodels.__version__,
        "alpha": float(policy_spec["alpha"]),
        "families": [family["name"] for family in policy_spec.get("families", [])],
        "hypotheses_evaluated": report["summary"]["hypotheses_evaluated"],
        "valid": report["valid"],
    }


def run(
    protocol_path: Path,
    policy_spec_path: Path,
    effect_results_path: Path,
    bootstrap_report_path: Path,
    cuped_report_path: Path,
    cuped_effects_path: Path,
    assumption_checks_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    return build_report(
        read_json(protocol_path),
        read_json(policy_spec_path),
        read_csv(effect_results_path),
        read_json(bootstrap_report_path),
        read_json(cuped_report_path),
        read_csv(cuped_effects_path),
        read_json(assumption_checks_path),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multiple-testing policy checker for experiment results.")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--policy-spec", type=Path, required=True)
    parser.add_argument("--effect-results", type=Path, required=True)
    parser.add_argument("--bootstrap-report", type=Path, required=True)
    parser.add_argument("--cuped-report", type=Path, required=True)
    parser.add_argument("--cuped-effects", type=Path, required=True)
    parser.add_argument("--assumption-checks", type=Path, required=True)
    parser.add_argument("--output-report", type=Path)
    parser.add_argument("--output-adjusted-results", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report, adjusted_rows, manifest = run(
        args.protocol,
        args.policy_spec,
        args.effect_results,
        args.bootstrap_report,
        args.cuped_report,
        args.cuped_effects,
        args.assumption_checks,
    )
    if args.output_report is not None:
        write_json(args.output_report, report)
    if args.output_adjusted_results is not None:
        write_csv(args.output_adjusted_results, adjusted_rows, ADJUSTED_RESULT_FIELDS)
    if args.output_manifest is not None:
        write_json(args.output_manifest, manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
