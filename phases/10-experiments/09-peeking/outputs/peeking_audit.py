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
from scipy import stats


SCHEDULE_FIELDS = [
    "look_id",
    "look_type",
    "calendar_date",
    "information_fraction",
    "planned",
    "alpha_spent_cumulative",
    "nominal_p_boundary",
    "observed_p_value",
    "crosses_naive_alpha",
    "crosses_spending_boundary",
    "decision_use",
    "status",
]

SIMULATION_FIELDS = [
    "look_count",
    "information_fractions",
    "naive_false_positive_rate",
    "obrien_fleming_false_positive_rate",
    "alpha",
    "repetitions",
]


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


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


def round_float(value: float, digits: int = 6) -> float | str:
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return round(float(value), digits)


def parse_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def obf_alpha_spent(alpha: float, information_fraction: float) -> float:
    if information_fraction <= 0 or information_fraction > 1:
        raise ValueError("information_fraction must be in (0, 1]")
    fixed_horizon_z = stats.norm.ppf(1 - alpha / 2)
    boundary_z = fixed_horizon_z / math.sqrt(information_fraction)
    return float(2 * (1 - stats.norm.cdf(boundary_z)))


def planned_look_map(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {look["look_id"]: look for look in policy.get("planned_decision_looks", [])}


def planned_schedule(policy: dict[str, Any]) -> list[dict[str, Any]]:
    alpha = float(policy["alpha"])
    rows: list[dict[str, Any]] = []
    for look in policy.get("planned_decision_looks", []):
        information_fraction = float(look["information_fraction"])
        spent = obf_alpha_spent(alpha, information_fraction)
        rows.append(
            {
                "look_id": look["look_id"],
                "look_type": "planned_decision",
                "calendar_date": look["calendar_date"],
                "information_fraction": information_fraction,
                "planned": True,
                "alpha_spent_cumulative": spent,
                "nominal_p_boundary": spent,
                "observed_p_value": None,
                "crosses_naive_alpha": False,
                "crosses_spending_boundary": False,
                "decision_use": look["decision_use"],
                "status": "planned_boundary",
            }
        )
    return rows


def observed_schedule(policy: dict[str, Any]) -> list[dict[str, Any]]:
    alpha = float(policy["alpha"])
    planned = planned_look_map(policy)
    rows: list[dict[str, Any]] = []
    for look in policy.get("observed_looks", []):
        information_fraction = float(look["information_fraction"])
        p_value = parse_optional_float(look.get("decision_metric_p_value"))
        look_id = look["look_id"]
        is_planned = look_id in planned and look.get("look_type") == "planned_decision"
        spent = obf_alpha_spent(alpha, information_fraction) if look.get("look_type") != "quality_monitoring" else 0.0
        crosses_naive = p_value is not None and p_value <= alpha
        crosses_spending = p_value is not None and p_value <= spent
        if look.get("look_type") == "quality_monitoring":
            status = "quality_only"
        elif not is_planned:
            status = "unplanned_decision_peek"
        elif look_id == "final" and not crosses_spending:
            status = "final_no_launch"
        elif crosses_spending:
            status = "crossed_planned_boundary"
        else:
            status = "continue_collecting"
        rows.append(
            {
                "look_id": look_id,
                "look_type": look["look_type"],
                "calendar_date": look["calendar_date"],
                "information_fraction": information_fraction,
                "planned": is_planned,
                "alpha_spent_cumulative": spent,
                "nominal_p_boundary": spent,
                "observed_p_value": p_value,
                "crosses_naive_alpha": crosses_naive,
                "crosses_spending_boundary": crosses_spending,
                "decision_use": look.get("decision_claim", ""),
                "status": status,
            }
        )
    return rows


def simulation_fractions(look_count: int) -> np.ndarray:
    return np.linspace(1 / look_count, 1.0, look_count, dtype=float)


def simulate_false_positive_rates(alpha: float, repetitions: int, seed: int, look_counts: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for look_count in look_counts:
        fractions = simulation_fractions(look_count)
        deltas = np.diff(np.r_[0.0, fractions])
        rng = np.random.default_rng(seed + look_count)
        increments = rng.normal(loc=0.0, scale=np.sqrt(deltas), size=(repetitions, look_count))
        brownian_path = np.cumsum(increments, axis=1)
        z_scores = brownian_path / np.sqrt(fractions)
        p_values = 2 * (1 - stats.norm.cdf(np.abs(z_scores)))
        obf_boundaries = np.array([obf_alpha_spent(alpha, float(fraction)) for fraction in fractions])
        rows.append(
            {
                "look_count": look_count,
                "information_fractions": [round_float(float(value)) for value in fractions],
                "naive_false_positive_rate": round_float(float(np.mean(np.any(p_values <= alpha, axis=1)))),
                "obrien_fleming_false_positive_rate": round_float(float(np.mean(np.any(p_values <= obf_boundaries, axis=1)))),
                "alpha": alpha,
                "repetitions": repetitions,
            }
        )
    return rows


def audit_policy(protocol: dict[str, Any], policy: dict[str, Any], multiple_testing_report: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    protocol_peeking = protocol.get("peeking_policy", {})
    planned_looks = policy.get("planned_decision_looks", [])
    planned_fractions = [float(look["information_fraction"]) for look in planned_looks]
    checks.append(
        {
            "id": "upstream_multiple_testing_valid",
            "severity": "error",
            "valid": multiple_testing_report.get("valid") is True,
            "observed": multiple_testing_report.get("valid"),
            "expected": True,
        }
    )
    checks.append(
        {
            "id": "protocol_disallows_unplanned_decision_looks",
            "severity": "error",
            "valid": protocol_peeking.get("unplanned_decision_looks_allowed") is False,
            "observed": protocol_peeking.get("unplanned_decision_looks_allowed"),
            "expected": False,
        }
    )
    checks.append(
        {
            "id": "policy_alpha_matches_protocol",
            "severity": "error",
            "valid": float(policy["alpha"]) == float(protocol["alpha"]),
            "observed": policy["alpha"],
            "expected": protocol["alpha"],
        }
    )
    checks.append(
        {
            "id": "final_decision_look_is_planned",
            "severity": "error",
            "valid": any(math.isclose(float(look["information_fraction"]), 1.0) for look in planned_looks),
            "observed": planned_fractions,
            "expected": "one planned decision look at information_fraction=1.0",
        }
    )
    checks.append(
        {
            "id": "planned_information_fractions_are_increasing",
            "severity": "error",
            "valid": planned_fractions == sorted(planned_fractions)
            and len(planned_fractions) == len(set(planned_fractions))
            and all(0 < value <= 1 for value in planned_fractions),
            "observed": planned_fractions,
            "expected": "strictly increasing fractions in (0, 1]",
        }
    )
    forbidden = set()
    for monitor in policy.get("quality_monitoring", []):
        forbidden.update(monitor.get("forbidden_fields", []))
    contaminated_quality_looks = []
    for look in policy.get("observed_looks", []):
        if look.get("look_type") != "quality_monitoring":
            continue
        if look.get("decision_metric_p_value") is not None:
            contaminated_quality_looks.append(look["look_id"])
        if "activation_rate_7d" in look.get("metrics_seen", []):
            contaminated_quality_looks.append(look["look_id"])
    checks.append(
        {
            "id": "quality_monitoring_excludes_decision_metrics",
            "severity": "error",
            "valid": not contaminated_quality_looks,
            "observed": sorted(set(contaminated_quality_looks)),
            "expected": f"quality monitoring excludes {sorted(forbidden)}",
        }
    )
    return checks


def decision_blockers(policy: dict[str, Any], observed_rows: list[dict[str, Any]], multiple_testing_report: dict[str, Any]) -> list[str]:
    blockers = []
    for row in observed_rows:
        if row["status"] == "unplanned_decision_peek":
            blockers.append(f"unplanned_decision_look:{row['look_id']}")
    if multiple_testing_report.get("summary", {}).get("launch_allowed_by_multiple_testing") is not True:
        blockers.append("multiple_testing_does_not_allow_launch")
    return blockers


def build_report(
    protocol: dict[str, Any],
    policy: dict[str, Any],
    power_plan: dict[str, Any],
    multiple_testing_report: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    checks = audit_policy(protocol, policy, multiple_testing_report)
    planned_rows = planned_schedule(policy)
    observed_rows = observed_schedule(policy)
    simulation_spec = policy["simulation"]
    simulation_rows = simulate_false_positive_rates(
        float(policy["alpha"]),
        int(simulation_spec["repetitions"]),
        int(simulation_spec["random_seed"]),
        [int(value) for value in simulation_spec["look_counts"]],
    )
    blockers = decision_blockers(policy, observed_rows, multiple_testing_report)
    warning_checks = [check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]]
    blocking_failures = [check["id"] for check in checks if check["severity"] == "error" and not check["valid"]]
    unplanned_peeks = [row["look_id"] for row in observed_rows if row["status"] == "unplanned_decision_peek"]
    naive_five = next(row for row in simulation_rows if row["look_count"] == 5)
    report = {
        "valid": not blocking_failures,
        "ready_for_decision": not blockers and not blocking_failures,
        "summary": {
            "experiment_id": protocol["experiment_id"],
            "alpha": float(policy["alpha"]),
            "planned_units_per_variant": power_plan["summary"]["planned_units_per_variant"],
            "planned_decision_looks": [row["look_id"] for row in planned_rows],
            "observed_decision_looks": [row["look_id"] for row in observed_rows if row["look_type"] != "quality_monitoring"],
            "unplanned_decision_looks": unplanned_peeks,
            "decision_blockers": blockers,
            "blocking_failures": blocking_failures,
            "warning_checks": warning_checks,
            "naive_fpr_at_five_looks": naive_five["naive_false_positive_rate"],
            "obrien_fleming_fpr_at_five_looks": naive_five["obrien_fleming_false_positive_rate"],
            "quality_monitoring_checks": policy["quality_monitoring"][0]["allowed_checks"],
            "multiple_testing_launch_allowed": multiple_testing_report.get("summary", {}).get("launch_allowed_by_multiple_testing"),
        },
        "checks": checks,
        "planned_schedule": planned_rows,
        "observed_schedule": observed_rows,
        "simulation": simulation_rows,
    }
    manifest = build_manifest(protocol, policy, report)
    return report, [*planned_rows, *observed_rows], simulation_rows, manifest


def build_manifest(protocol: dict[str, Any], policy: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact": "peeking-audit",
        "experiment_id": protocol["experiment_id"],
        "scipy_version": scipy.__version__,
        "alpha": float(policy["alpha"]),
        "alpha_spending": policy["alpha_spending"]["name"],
        "simulation_repetitions": int(policy["simulation"]["repetitions"]),
        "planned_decision_looks": report["summary"]["planned_decision_looks"],
        "unplanned_decision_looks": report["summary"]["unplanned_decision_looks"],
        "valid": report["valid"],
    }


def run(
    protocol_path: Path,
    policy_path: Path,
    power_plan_path: Path,
    multiple_testing_report_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return build_report(
        read_json(protocol_path),
        read_json(policy_path),
        read_json(power_plan_path),
        read_json(multiple_testing_report_path),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit peeking and sequential monitoring for an experiment.")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--peeking-policy", type=Path, required=True)
    parser.add_argument("--power-plan", type=Path, required=True)
    parser.add_argument("--multiple-testing-report", type=Path, required=True)
    parser.add_argument("--output-report", type=Path)
    parser.add_argument("--output-schedule", type=Path)
    parser.add_argument("--output-simulation", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report, schedule_rows, simulation_rows, manifest = run(
        args.protocol,
        args.peeking_policy,
        args.power_plan,
        args.multiple_testing_report,
    )
    if args.output_report is not None:
        write_json(args.output_report, report)
    if args.output_schedule is not None:
        write_csv(args.output_schedule, schedule_rows, SCHEDULE_FIELDS)
    if args.output_simulation is not None:
        write_csv(args.output_simulation, simulation_rows, SIMULATION_FIELDS)
    if args.output_manifest is not None:
        write_json(args.output_manifest, manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
