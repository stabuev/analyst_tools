from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import warnings
from pathlib import Path
from typing import Any

import scipy
import statsmodels
from scipy import stats
from statsmodels.stats.proportion import proportions_ztest


SEGMENT_EFFECT_FIELDS = [
    "dimension",
    "segment_value",
    "metric_id",
    "role",
    "segment_role",
    "predeclared",
    "control_units",
    "treatment_units",
    "control_denominator",
    "treatment_denominator",
    "control_value",
    "treatment_value",
    "absolute_lift",
    "p_value",
    "p_value_method",
    "minimum_cell_size",
    "meets_minimum_cell_size",
    "has_both_variants",
    "decision_eligible",
    "decision_use",
    "status",
    "diagnostics",
]

INTERACTION_FIELDS = [
    "dimension",
    "metric_id",
    "role",
    "segment_values_compared",
    "estimable_segments",
    "interaction_estimate",
    "interaction_se",
    "interaction_p_value",
    "status",
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


def parse_float(value: str | int | float | None) -> float:
    if value is None:
        return math.nan
    if isinstance(value, (int, float)):
        return float(value)
    if value.strip() == "":
        return math.nan
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


def metric_roles(protocol: dict[str, Any]) -> dict[str, str]:
    roles = {protocol["primary_metric"]: "primary"}
    roles.update({metric_id: "guardrail" for metric_id in protocol.get("guardrail_metrics", [])})
    roles.update({metric_id: "secondary" for metric_id in protocol.get("secondary_metrics", [])})
    return roles


def user_map(users: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["user_id"]: row for row in users if row.get("is_test_user", "false").lower() != "true"}


def enriched_observations(observations: list[dict[str, str]], users: list[dict[str, str]]) -> list[dict[str, Any]]:
    profiles = user_map(users)
    enriched: list[dict[str, Any]] = []
    for row in observations:
        profile = profiles.get(row["user_id"])
        if profile is None:
            continue
        enriched.append({**row, "profile": profile})
    return enriched


def group_rows(
    rows: list[dict[str, Any]],
    dimension: str,
    metric_id: str,
    segment_value: str,
    variant_id: str,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["metric_id"] == metric_id
        and row["variant_id"] == variant_id
        and row["profile"].get(dimension, "") == segment_value
    ]


def usable_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not math.isnan(parse_float(row.get("denominator"))) and parse_float(row.get("denominator")) > 0]


def aggregate(rows: list[dict[str, Any]], metric_type: str) -> dict[str, float]:
    usable = usable_rows(rows)
    numerator = sum(parse_float(row.get("numerator")) for row in usable)
    denominator = sum(parse_float(row.get("denominator")) for row in usable)
    values = [parse_float(row.get("value")) for row in usable if not math.isnan(parse_float(row.get("value")))]
    if metric_type == "mean":
        value = sum(values) / len(values) if values else math.nan
    else:
        value = numerator / denominator if denominator > 0 else math.nan
    return {
        "units": float(len(usable)),
        "numerator": numerator,
        "denominator": denominator,
        "value": value,
    }


def two_sample_p_value(control: dict[str, float], treatment: dict[str, float]) -> float:
    if control["denominator"] <= 0 or treatment["denominator"] <= 0:
        return math.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _, p_value = proportions_ztest(
            count=[treatment["numerator"], control["numerator"]],
            nobs=[treatment["denominator"], control["denominator"]],
            alternative="two-sided",
        )
    return float(p_value)


def lift_standard_error(control: dict[str, float], treatment: dict[str, float]) -> float:
    if control["denominator"] <= 0 or treatment["denominator"] <= 0:
        return math.nan
    control_rate = control["value"]
    treatment_rate = treatment["value"]
    if math.isnan(control_rate) or math.isnan(treatment_rate):
        return math.nan
    return math.sqrt(
        control_rate * (1 - control_rate) / control["denominator"]
        + treatment_rate * (1 - treatment_rate) / treatment["denominator"]
    )


def segment_values(rows: list[dict[str, Any]], dimension: str, metric_id: str) -> list[str]:
    values = {
        row["profile"].get(dimension, "")
        for row in rows
        if row["metric_id"] == metric_id and row["profile"].get(dimension, "") != ""
    }
    return sorted(values)


def metric_type_for(rows: list[dict[str, Any]], metric_id: str) -> str:
    for row in rows:
        if row["metric_id"] == metric_id:
            return row["metric_type"]
    raise KeyError(f"metric not found: {metric_id}")


def build_segment_rows(
    protocol: dict[str, Any],
    policy: dict[str, Any],
    rows: list[dict[str, Any]],
    multiple_testing_report: dict[str, Any],
    peeking_report: dict[str, Any],
) -> list[dict[str, Any]]:
    control, treatment = ordered_variants(protocol)
    roles = metric_roles(protocol)
    minimum_cell_size = int(policy["minimum_cell_size"])
    upstream_blocks = []
    if multiple_testing_report.get("summary", {}).get("launch_allowed_by_multiple_testing") is not True:
        upstream_blocks.append("multiple_testing_does_not_allow_launch")
    if peeking_report.get("ready_for_decision") is not True:
        upstream_blocks.append("peeking_audit_not_ready_for_decision")

    output: list[dict[str, Any]] = []
    for dimension_spec in policy["dimensions"]:
        dimension = dimension_spec["name"]
        predeclared = dimension_spec.get("predeclared", False)
        segment_role = "predeclared" if predeclared else "post_hoc"
        decision_use = dimension_spec.get("decision_use", "diagnostic_supporting" if predeclared else "exploratory_only")
        for metric_id in dimension_spec["metrics"]:
            metric_type = metric_type_for(rows, metric_id)
            for value in segment_values(rows, dimension, metric_id):
                control_rows = group_rows(rows, dimension, metric_id, value, control)
                treatment_rows = group_rows(rows, dimension, metric_id, value, treatment)
                control_agg = aggregate(control_rows, metric_type)
                treatment_agg = aggregate(treatment_rows, metric_type)
                has_both_variants = control_agg["units"] > 0 and treatment_agg["units"] > 0
                meets_minimum = control_agg["units"] >= minimum_cell_size and treatment_agg["units"] >= minimum_cell_size
                absolute_lift = treatment_agg["value"] - control_agg["value"] if has_both_variants else math.nan
                p_value = two_sample_p_value(control_agg, treatment_agg) if has_both_variants else math.nan

                diagnostics = []
                if not has_both_variants:
                    diagnostics.append("missing_control_or_treatment_in_segment")
                if not meets_minimum:
                    diagnostics.append("cell_below_minimum_size")
                if not predeclared:
                    diagnostics.append("post_hoc_exploratory_only")
                    diagnostics.append("segment_dimension_not_predeclared")
                diagnostics.extend(upstream_blocks)
                diagnostics.append("segment_not_a_standalone_launch_gate")

                if not has_both_variants:
                    status = "missing_variant"
                elif not meets_minimum:
                    status = "below_minimum_cell_size"
                elif not predeclared:
                    status = "exploratory_only"
                else:
                    status = "diagnostic_ready"

                output.append(
                    {
                        "dimension": dimension,
                        "segment_value": value,
                        "metric_id": metric_id,
                        "role": roles.get(metric_id, "exploratory"),
                        "segment_role": segment_role,
                        "predeclared": predeclared,
                        "control_units": int(control_agg["units"]),
                        "treatment_units": int(treatment_agg["units"]),
                        "control_denominator": round_float(control_agg["denominator"]),
                        "treatment_denominator": round_float(treatment_agg["denominator"]),
                        "control_value": round_float(control_agg["value"]),
                        "treatment_value": round_float(treatment_agg["value"]),
                        "absolute_lift": round_float(absolute_lift),
                        "p_value": round_float(p_value),
                        "p_value_method": "statsmodels.proportions_ztest_two_sided" if has_both_variants else "not_estimated",
                        "minimum_cell_size": minimum_cell_size,
                        "meets_minimum_cell_size": meets_minimum,
                        "has_both_variants": has_both_variants,
                        "decision_eligible": False,
                        "decision_use": decision_use,
                        "status": status,
                        "diagnostics": diagnostics,
                    }
                )
    return output


def effect_for_interaction(row: dict[str, Any]) -> tuple[float, float]:
    control = {
        "denominator": float(row["control_denominator"]),
        "value": float(row["control_value"]),
    }
    treatment = {
        "denominator": float(row["treatment_denominator"]),
        "value": float(row["treatment_value"]),
    }
    se = lift_standard_error(control, treatment)
    lift = parse_float(row["absolute_lift"])
    return lift, se


def build_interaction_rows(policy: dict[str, Any], segment_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    interactions: list[dict[str, Any]] = []
    for dimension_spec in policy["dimensions"]:
        dimension = dimension_spec["name"]
        for metric_id in dimension_spec["metrics"]:
            candidates = [
                row
                for row in segment_rows
                if row["dimension"] == dimension
                and row["metric_id"] == metric_id
                and row["has_both_variants"] is True
            ]
            diagnostics = []
            if len(candidates) < 2:
                diagnostics.append("need_at_least_two_segments_with_both_variants")
                interactions.append(
                    {
                        "dimension": dimension,
                        "metric_id": metric_id,
                        "role": candidates[0]["role"] if candidates else "unknown",
                        "segment_values_compared": [row["segment_value"] for row in candidates],
                        "estimable_segments": len(candidates),
                        "interaction_estimate": "nan",
                        "interaction_se": "nan",
                        "interaction_p_value": "nan",
                        "status": "insufficient_overlap",
                        "diagnostics": diagnostics,
                    }
                )
                continue

            first = candidates[0]
            strongest = max(candidates[1:], key=lambda row: abs(parse_float(row["absolute_lift"]) - parse_float(first["absolute_lift"])))
            first_lift, first_se = effect_for_interaction(first)
            second_lift, second_se = effect_for_interaction(strongest)
            interaction = first_lift - second_lift
            interaction_se = math.sqrt(first_se**2 + second_se**2) if not math.isnan(first_se) and not math.isnan(second_se) else math.nan
            if interaction_se > 0:
                p_value = float(2 * (1 - stats.norm.cdf(abs(interaction / interaction_se))))
            else:
                p_value = math.nan
                diagnostics.append("zero_or_missing_interaction_standard_error")
            if any(row["meets_minimum_cell_size"] is not True for row in (first, strongest)):
                diagnostics.append("cell_below_minimum_size")
            interactions.append(
                {
                    "dimension": dimension,
                    "metric_id": metric_id,
                    "role": first["role"],
                    "segment_values_compared": [first["segment_value"], strongest["segment_value"]],
                    "estimable_segments": len(candidates),
                    "interaction_estimate": round_float(interaction),
                    "interaction_se": round_float(interaction_se),
                    "interaction_p_value": round_float(p_value),
                    "status": "below_minimum_cell_size" if "cell_below_minimum_size" in diagnostics else "estimated",
                    "diagnostics": diagnostics,
                }
            )
    return interactions


def audit_policy(
    protocol: dict[str, Any],
    policy: dict[str, Any],
    observations: list[dict[str, str]],
    users: list[dict[str, str]],
    multiple_testing_report: dict[str, Any],
    peeking_report: dict[str, Any],
) -> list[dict[str, Any]]:
    protocol_dimensions = set(protocol.get("segment_policy", {}).get("predeclared_dimensions", []))
    policy_predeclared = {dimension["name"] for dimension in policy.get("dimensions", []) if dimension.get("predeclared") is True}
    policy_post_hoc = {dimension["name"] for dimension in policy.get("dimensions", []) if dimension.get("predeclared") is not True}
    user_columns = set(users[0]) if users else set()
    observed_metrics = {row["metric_id"] for row in observations}
    policy_metrics = {
        metric_id
        for dimension in policy.get("dimensions", [])
        for metric_id in dimension.get("metrics", [])
    }
    checks = [
        {
            "id": "predeclared_dimensions_match_protocol",
            "severity": "error",
            "valid": policy_predeclared.issubset(protocol_dimensions),
            "observed": sorted(policy_predeclared),
            "expected": sorted(protocol_dimensions),
        },
        {
            "id": "post_hoc_dimensions_are_not_predeclared",
            "severity": "error",
            "valid": not (policy_post_hoc & protocol_dimensions),
            "observed": sorted(policy_post_hoc),
            "expected": "post-hoc dimensions outside protocol segment_policy.predeclared_dimensions",
        },
        {
            "id": "minimum_cell_size_matches_protocol",
            "severity": "error",
            "valid": int(policy["minimum_cell_size"]) == int(protocol["segment_policy"]["minimum_cell_size"]),
            "observed": int(policy["minimum_cell_size"]),
            "expected": int(protocol["segment_policy"]["minimum_cell_size"]),
        },
        {
            "id": "segment_dimensions_exist_in_users",
            "severity": "error",
            "valid": all(dimension["name"] in user_columns for dimension in policy.get("dimensions", [])),
            "observed": sorted(dimension["name"] for dimension in policy.get("dimensions", [])),
            "expected": sorted(user_columns),
        },
        {
            "id": "segment_metrics_exist_in_observations",
            "severity": "error",
            "valid": policy_metrics.issubset(observed_metrics),
            "observed": sorted(policy_metrics),
            "expected": sorted(observed_metrics),
        },
        {
            "id": "upstream_multiple_testing_valid",
            "severity": "error",
            "valid": multiple_testing_report.get("valid") is True,
            "observed": multiple_testing_report.get("valid"),
            "expected": True,
        },
        {
            "id": "upstream_peeking_audit_valid",
            "severity": "error",
            "valid": peeking_report.get("valid") is True,
            "observed": peeking_report.get("valid"),
            "expected": True,
        },
    ]
    return checks


def build_report(
    protocol: dict[str, Any],
    policy: dict[str, Any],
    observations: list[dict[str, str]],
    users: list[dict[str, str]],
    multiple_testing_report: dict[str, Any],
    peeking_report: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    checks = audit_policy(protocol, policy, observations, users, multiple_testing_report, peeking_report)
    rows = enriched_observations(observations, users)
    segment_rows = build_segment_rows(protocol, policy, rows, multiple_testing_report, peeking_report)
    interaction_rows = build_interaction_rows(policy, segment_rows)
    blocking_failures = [check["id"] for check in checks if check["severity"] == "error" and not check["valid"]]
    warning_checks = [check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]]
    missing_variant_rows = [row for row in segment_rows if row["status"] == "missing_variant"]
    below_minimum_rows = [row for row in segment_rows if row["meets_minimum_cell_size"] is not True]
    exploratory_rows = [row for row in segment_rows if row["segment_role"] == "post_hoc"]
    predeclared_estimable = [
        f"{row['dimension']}={row['segment_value']}"
        for row in segment_rows
        if row["segment_role"] == "predeclared" and row["has_both_variants"] is True
    ]
    decision_blockers = []
    if multiple_testing_report.get("summary", {}).get("launch_allowed_by_multiple_testing") is not True:
        decision_blockers.append("multiple_testing_does_not_allow_launch")
    if peeking_report.get("ready_for_decision") is not True:
        decision_blockers.append("peeking_audit_not_ready_for_decision")
    if below_minimum_rows:
        decision_blockers.append("segment_cells_below_minimum_size")
    if any(row["status"] == "insufficient_overlap" for row in interaction_rows):
        decision_blockers.append("interaction_checks_insufficient_overlap")

    report = {
        "valid": not blocking_failures,
        "ready_for_decision": False,
        "summary": {
            "experiment_id": protocol["experiment_id"],
            "alpha": float(protocol["alpha"]),
            "minimum_cell_size": int(policy["minimum_cell_size"]),
            "predeclared_dimensions": [dimension["name"] for dimension in policy["dimensions"] if dimension.get("predeclared") is True],
            "post_hoc_dimensions": [dimension["name"] for dimension in policy["dimensions"] if dimension.get("predeclared") is not True],
            "segment_rows": len(segment_rows),
            "predeclared_estimable_segments": sorted(set(predeclared_estimable)),
            "exploratory_rows": len(exploratory_rows),
            "missing_variant_rows": len(missing_variant_rows),
            "below_minimum_cell_rows": len(below_minimum_rows),
            "interaction_checks": len(interaction_rows),
            "insufficient_interaction_checks": len([row for row in interaction_rows if row["status"] == "insufficient_overlap"]),
            "decision_blockers": decision_blockers,
            "blocking_failures": blocking_failures,
            "warning_checks": warning_checks,
            "segment_findings_not_launch_gates": True,
            "multiple_testing_launch_allowed": multiple_testing_report.get("summary", {}).get("launch_allowed_by_multiple_testing"),
            "peeking_ready_for_decision": peeking_report.get("ready_for_decision"),
        },
        "checks": checks,
        "segment_effects": segment_rows,
        "interaction_checks": interaction_rows,
    }
    manifest = build_manifest(protocol, policy, report)
    return report, segment_rows, interaction_rows, manifest


def build_manifest(protocol: dict[str, Any], policy: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact": "segment-effect-auditor",
        "experiment_id": protocol["experiment_id"],
        "scipy_version": scipy.__version__,
        "statsmodels_version": statsmodels.__version__,
        "minimum_cell_size": int(policy["minimum_cell_size"]),
        "segment_rows": report["summary"]["segment_rows"],
        "interaction_checks": report["summary"]["interaction_checks"],
        "valid": report["valid"],
        "ready_for_decision": report["ready_for_decision"],
    }


def run(
    protocol_path: Path,
    policy_path: Path,
    observations_path: Path,
    users_path: Path,
    multiple_testing_report_path: Path,
    peeking_report_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return build_report(
        read_json(protocol_path),
        read_json(policy_path),
        read_csv(observations_path),
        read_csv(users_path),
        read_json(multiple_testing_report_path),
        read_json(peeking_report_path),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit heterogeneous segment effects for a pre-registered experiment.")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--segment-policy", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--multiple-testing-report", type=Path, required=True)
    parser.add_argument("--peeking-report", type=Path, required=True)
    parser.add_argument("--output-report", type=Path)
    parser.add_argument("--output-segment-effects", type=Path)
    parser.add_argument("--output-interactions", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report, segment_rows, interaction_rows, manifest = run(
        args.protocol,
        args.segment_policy,
        args.observations,
        args.users,
        args.multiple_testing_report,
        args.peeking_report,
    )
    if args.output_report is not None:
        write_json(args.output_report, report)
    if args.output_segment_effects is not None:
        write_csv(args.output_segment_effects, segment_rows, SEGMENT_EFFECT_FIELDS)
    if args.output_interactions is not None:
        write_csv(args.output_interactions, interaction_rows, INTERACTION_FIELDS)
    if args.output_manifest is not None:
        write_json(args.output_manifest, manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
