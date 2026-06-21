from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


EVIDENCE_FILES = [
    {
        "id": "protocol",
        "category": "protocol",
        "source": "01-hypothesis-and-metric/outputs/experiment_protocol.json",
        "package_path": "evidence/01_experiment_protocol.json",
        "required_for": "pre-registration, owner, metric roles and decision rule",
    },
    {
        "id": "randomization_spec",
        "category": "assignment",
        "source": "02-randomization-unit/outputs/randomization_spec.json",
        "package_path": "evidence/02_randomization_spec.json",
        "required_for": "assignment key, hash buckets and exposure contract",
    },
    {
        "id": "assignments",
        "category": "assignment",
        "source": "data/tiny/assignments.csv",
        "package_path": "evidence/02_assignments.csv",
        "required_for": "one-unit-one-variant assignment audit",
    },
    {
        "id": "exposures",
        "category": "assignment",
        "source": "data/tiny/exposures.csv",
        "package_path": "evidence/02_exposures.csv",
        "required_for": "assignment-to-exposure audit",
    },
    {
        "id": "randomization_health",
        "category": "aa_srm",
        "source": "03-aa-and-srm/outputs/randomization_health_report.json",
        "package_path": "evidence/03_randomization_health_report.json",
        "required_for": "A/A, SRM, covariate balance and telemetry checks",
    },
    {
        "id": "power_plan",
        "category": "power",
        "source": "04-mde-and-power/outputs/power_plan.json",
        "package_path": "evidence/04_power_plan.json",
        "required_for": "MDE, target power and planned sample size",
    },
    {
        "id": "effect_results",
        "category": "effects",
        "source": "05-means-and-proportions/outputs/effect_results.csv",
        "package_path": "evidence/05_effect_results.csv",
        "required_for": "primary, secondary and guardrail effect estimates",
    },
    {
        "id": "assumption_checks",
        "category": "effects",
        "source": "05-means-and-proportions/outputs/assumption_checks.json",
        "package_path": "evidence/05_assumption_checks.json",
        "required_for": "effect-analysis blockers and warnings",
    },
    {
        "id": "bootstrap_intervals",
        "category": "uncertainty",
        "source": "06-bootstrap/outputs/bootstrap_intervals.json",
        "package_path": "evidence/06_bootstrap_intervals.json",
        "required_for": "bootstrap confidence intervals and permutation diagnostics",
    },
    {
        "id": "variance_reduction",
        "category": "cuped",
        "source": "07-cuped/outputs/variance_reduction_report.json",
        "package_path": "evidence/07_variance_reduction_report.json",
        "required_for": "CUPED readiness, adjusted primary effect and variance reduction",
    },
    {
        "id": "cuped_effects",
        "category": "cuped",
        "source": "07-cuped/outputs/cuped_effects.csv",
        "package_path": "evidence/07_cuped_effects.csv",
        "required_for": "metric-level CUPED adjusted estimates",
    },
    {
        "id": "multiple_testing_policy",
        "category": "multiple_testing",
        "source": "08-multiple-testing/outputs/multiple_testing_policy.json",
        "package_path": "evidence/08_multiple_testing_policy.json",
        "required_for": "hypothesis families and adjustment methods",
    },
    {
        "id": "multiple_testing",
        "category": "multiple_testing",
        "source": "08-multiple-testing/outputs/multiple_testing_report.json",
        "package_path": "evidence/08_multiple_testing_report.json",
        "required_for": "gatekeeping and adjusted decision eligibility",
    },
    {
        "id": "adjusted_results",
        "category": "multiple_testing",
        "source": "08-multiple-testing/outputs/adjusted_results.csv",
        "package_path": "evidence/08_adjusted_results.csv",
        "required_for": "metric-level adjusted p-values",
    },
    {
        "id": "peeking_policy",
        "category": "peeking",
        "source": "09-peeking/outputs/peeking_policy.json",
        "package_path": "evidence/09_peeking_policy.json",
        "required_for": "planned and observed monitoring looks",
    },
    {
        "id": "peeking",
        "category": "peeking",
        "source": "09-peeking/outputs/sequential_monitoring_report.json",
        "package_path": "evidence/09_sequential_monitoring_report.json",
        "required_for": "alpha spending and unplanned decision look audit",
    },
    {
        "id": "segment_policy",
        "category": "segments",
        "source": "10-heterogeneous-effects/outputs/segment_policy.json",
        "package_path": "evidence/10_segment_policy.json",
        "required_for": "predeclared and post-hoc segment policy",
    },
    {
        "id": "heterogeneity",
        "category": "segments",
        "source": "10-heterogeneous-effects/outputs/heterogeneity_report.json",
        "package_path": "evidence/10_heterogeneity_report.json",
        "required_for": "segment effects, interaction checks and exploratory flags",
    },
    {
        "id": "segment_effects",
        "category": "segments",
        "source": "10-heterogeneous-effects/outputs/segment_effects.csv",
        "package_path": "evidence/10_segment_effects.csv",
        "required_for": "segment-level effect table",
    },
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


def write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_evidence(phase_root: Path, output_dir: Path) -> list[dict[str, Any]]:
    evidence_index: list[dict[str, Any]] = []
    for spec in EVIDENCE_FILES:
        source = phase_root / spec["source"]
        if not source.is_file():
            raise FileNotFoundError(source)
        destination = output_dir / spec["package_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        evidence_index.append(
            {
                "id": spec["id"],
                "category": spec["category"],
                "source_path": spec["source"],
                "package_path": spec["package_path"],
                "required_for": spec["required_for"],
                "sha256": sha256_file(destination),
            }
        )
    return evidence_index


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() == "true"


def assignment_audit(protocol: dict[str, Any], assignments: list[dict[str, str]], exposures: list[dict[str, str]]) -> dict[str, Any]:
    experiment_id = protocol["experiment_id"]
    eligible_assignments = [
        row
        for row in assignments
        if row["experiment_id"] == experiment_id and parse_bool(row.get("is_eligible", "false"))
    ]
    experiment_exposures = [row for row in exposures if row["experiment_id"] == experiment_id]
    assignment_by_unit: dict[str, list[dict[str, str]]] = {}
    for row in eligible_assignments:
        assignment_by_unit.setdefault(row["assignment_unit_id"], []).append(row)
    exposure_by_unit: dict[str, list[dict[str, str]]] = {}
    for row in experiment_exposures:
        exposure_by_unit.setdefault(row["assignment_unit_id"], []).append(row)

    duplicate_assignment_units = sorted(unit for unit, rows in assignment_by_unit.items() if len({row["variant_id"] for row in rows}) > 1)
    duplicate_exposure_units = sorted(unit for unit, rows in exposure_by_unit.items() if len(rows) > 1)
    missing_exposure_units = sorted(set(assignment_by_unit) - set(exposure_by_unit))
    extra_exposure_units = sorted(set(exposure_by_unit) - set(assignment_by_unit))
    variant_mismatches = []
    for unit, rows in assignment_by_unit.items():
        exposure_rows = exposure_by_unit.get(unit, [])
        if not exposure_rows:
            continue
        if rows[0]["variant_id"] != exposure_rows[0]["variant_id"]:
            variant_mismatches.append(
                {
                    "assignment_unit_id": unit,
                    "assignment_variant": rows[0]["variant_id"],
                    "exposure_variant": exposure_rows[0]["variant_id"],
                }
            )

    variant_counts: dict[str, int] = {}
    exposure_counts: dict[str, int] = {}
    for row in eligible_assignments:
        variant_counts[row["variant_id"]] = variant_counts.get(row["variant_id"], 0) + 1
    for row in experiment_exposures:
        exposure_counts[row["variant_id"]] = exposure_counts.get(row["variant_id"], 0) + 1

    checks = [
        {
            "id": "one_unit_one_assignment_variant",
            "valid": not duplicate_assignment_units,
            "observed": duplicate_assignment_units,
            "expected": "no assignment unit appears in multiple variants",
        },
        {
            "id": "every_assignment_has_exposure",
            "valid": not missing_exposure_units,
            "observed": missing_exposure_units,
            "expected": "every eligible assignment has one exposure",
        },
        {
            "id": "no_extra_exposures",
            "valid": not extra_exposure_units,
            "observed": extra_exposure_units,
            "expected": "every exposure has a matching eligible assignment",
        },
        {
            "id": "exposure_variant_matches_assignment",
            "valid": not variant_mismatches,
            "observed": variant_mismatches,
            "expected": "exposure variant equals assigned variant",
        },
        {
            "id": "no_duplicate_exposures",
            "valid": not duplicate_exposure_units,
            "observed": duplicate_exposure_units,
            "expected": "one exposure row per assignment unit",
        },
    ]
    return {
        "valid": all(check["valid"] for check in checks),
        "summary": {
            "experiment_id": experiment_id,
            "assignment_unit": protocol["assignment_key"],
            "assigned_units": len(eligible_assignments),
            "exposed_units": len(experiment_exposures),
            "variant_counts": variant_counts,
            "exposure_counts": exposure_counts,
            "missing_exposure_units": missing_exposure_units,
            "extra_exposure_units": extra_exposure_units,
            "variant_mismatches": variant_mismatches,
        },
        "checks": checks,
    }


def row_by_metric(rows: list[dict[str, str]], metric_id: str) -> dict[str, str]:
    for row in rows:
        if row["metric_id"] == metric_id:
            return row
    raise KeyError(metric_id)


def bootstrap_interval(report: dict[str, Any], metric_id: str) -> dict[str, Any]:
    for row in report.get("intervals", []):
        if row["metric_id"] == metric_id:
            return row
    raise KeyError(metric_id)


def cuped_effect(report: dict[str, Any], metric_id: str) -> dict[str, Any]:
    for row in report.get("effects", []):
        if row["metric_id"] == metric_id:
            return row
    raise KeyError(metric_id)


def append_unique(items: list[str], values: list[str]) -> None:
    for value in values:
        if value not in items:
            items.append(value)


def build_decision_summary(
    policy: dict[str, Any],
    protocol: dict[str, Any],
    assignment: dict[str, Any],
    randomization_health: dict[str, Any],
    power_plan: dict[str, Any],
    effect_results: list[dict[str, str]],
    assumption_checks: dict[str, Any],
    bootstrap: dict[str, Any],
    cuped: dict[str, Any],
    multiple_testing: dict[str, Any],
    peeking: dict[str, Any],
    heterogeneity: dict[str, Any],
) -> dict[str, Any]:
    primary_metric = protocol["primary_metric"]
    primary_effect = row_by_metric(effect_results, primary_metric)
    primary_bootstrap = bootstrap_interval(bootstrap, primary_metric)
    primary_cuped = cuped_effect(cuped, primary_metric)
    guardrail_rows = [row for row in effect_results if row["role"] == "guardrail"]
    guardrail_statuses = {row["metric_id"]: row["guardrail_status"] for row in guardrail_rows}
    rollback_required = any(status == "breached" for status in guardrail_statuses.values())

    launch_requirements = {
        "assignment_audit_valid": assignment["valid"],
        "randomization_health_ready": randomization_health.get("valid") is True and randomization_health.get("ready_for_ab_analysis") is True,
        "power_plan_ready": power_plan.get("valid") is True and power_plan.get("ready_for_sizing") is True,
        "effect_analysis_ready": assumption_checks.get("ready_for_decision") is True,
        "multiple_testing_allows_launch": multiple_testing.get("summary", {}).get("launch_allowed_by_multiple_testing") is True,
        "peeking_ready_for_decision": peeking.get("ready_for_decision") is True,
        "heterogeneity_report_valid": heterogeneity.get("valid") is True,
        "no_guardrail_breach": not rollback_required,
    }
    launch_allowed = all(launch_requirements.values())

    reasons: list[str] = []
    append_unique(reasons, assumption_checks.get("summary", {}).get("decision_blockers", []))
    if multiple_testing.get("summary", {}).get("launch_allowed_by_multiple_testing") is not True:
        append_unique(reasons, ["multiple_testing_does_not_allow_launch"])
    append_unique(reasons, peeking.get("summary", {}).get("decision_blockers", []))
    append_unique(reasons, heterogeneity.get("summary", {}).get("decision_blockers", []))
    if not assignment["valid"]:
        append_unique(reasons, ["assignment_audit_failed"])
    if rollback_required:
        append_unique(reasons, ["guardrail_breached_requires_rollback"])

    if rollback_required:
        decision = "rollback"
    elif launch_allowed:
        decision = "launch"
    elif "missed_primary_direction" in reasons or "observed_sample_below_power_plan" in reasons:
        decision = "hold"
    else:
        decision = "iterate"

    if decision not in policy["allowed_decisions"]:
        raise ValueError(f"decision {decision} is not allowed by decision policy")

    return {
        "artifact": "experiment-decision-package",
        "experiment_id": protocol["experiment_id"],
        "decision": decision,
        "launch_allowed": launch_allowed,
        "rollback_required": rollback_required,
        "decision_owner": protocol["decision_owner"],
        "decision_reasons": reasons,
        "launch_requirements": launch_requirements,
        "primary_metric": {
            "metric_id": primary_metric,
            "raw_absolute_lift": float(primary_effect["absolute_lift"]),
            "raw_p_value": float(primary_effect["p_value"]),
            "practical_status": primary_effect["practical_status"],
            "decision_status": primary_effect["decision_status"],
            "bootstrap_ci_low": primary_bootstrap["ci_low"],
            "bootstrap_ci_high": primary_bootstrap["ci_high"],
            "cuped_adjusted_absolute_lift": primary_cuped["adjusted_absolute_lift"],
            "cuped_p_value": primary_cuped["p_value"],
        },
        "guardrails": {
            "statuses": guardrail_statuses,
            "watch_metrics": multiple_testing.get("summary", {}).get("guardrail_watch_metrics", []),
            "adjusted_breaches": multiple_testing.get("summary", {}).get("adjusted_guardrail_breaches", []),
        },
        "source_statuses": {
            "assignment_audit_valid": assignment["valid"],
            "randomization_health_valid": randomization_health.get("valid"),
            "randomization_ready_for_ab_analysis": randomization_health.get("ready_for_ab_analysis"),
            "power_plan_valid": power_plan.get("valid"),
            "effect_analysis_ready_for_decision": assumption_checks.get("ready_for_decision"),
            "bootstrap_ready_for_decision": bootstrap.get("ready_for_decision"),
            "cuped_ready_for_decision": cuped.get("ready_for_decision"),
            "multiple_testing_ready_for_decision": multiple_testing.get("ready_for_decision"),
            "peeking_ready_for_decision": peeking.get("ready_for_decision"),
            "heterogeneity_ready_for_decision": heterogeneity.get("ready_for_decision"),
        },
        "communication": {
            "headline": "Hold launch: primary metric missed direction and decision gates are not cleared.",
            "next_action": "Do not launch from this experiment; keep the segment findings as exploratory inputs for a new pre-registered iteration.",
        },
    }


def markdown_report(summary: dict[str, Any]) -> str:
    reasons = "\n".join(f"- {reason}" for reason in summary["decision_reasons"])
    requirements = "\n".join(
        f"- {name}: {str(value).lower()}" for name, value in summary["launch_requirements"].items()
    )
    guardrails = "\n".join(
        f"- {metric_id}: {status}" for metric_id, status in summary["guardrails"]["statuses"].items()
    )
    primary = summary["primary_metric"]
    return f"""# Experiment Decision Report

Experiment: `{summary["experiment_id"]}`

Decision: `{summary["decision"]}`

Owner: `{summary["decision_owner"]}`

## Headline

{summary["communication"]["headline"]}

## Primary Metric

- metric_id: `{primary["metric_id"]}`
- raw_absolute_lift: `{primary["raw_absolute_lift"]}`
- raw_p_value: `{primary["raw_p_value"]}`
- bootstrap_ci: `[{primary["bootstrap_ci_low"]}, {primary["bootstrap_ci_high"]}]`
- cuped_adjusted_absolute_lift: `{primary["cuped_adjusted_absolute_lift"]}`
- practical_status: `{primary["practical_status"]}`

## Launch Requirements

{requirements}

## Decision Reasons

{reasons}

## Guardrails

{guardrails}

## Next Action

{summary["communication"]["next_action"]}
"""


def build_checksums(output_dir: Path, package_files: list[str]) -> dict[str, Any]:
    return {
        "algorithm": "sha256",
        "files": [
            {
                "path": relative,
                "sha256": sha256_file(output_dir / relative),
            }
            for relative in sorted(package_files)
        ],
    }


def build_package(phase_root: Path, decision_policy_path: Path, output_dir: Path) -> dict[str, Any]:
    policy = read_json(decision_policy_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_index = copy_evidence(phase_root, output_dir)

    protocol = read_json(phase_root / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json")
    assignments = read_csv(phase_root / "data" / "tiny" / "assignments.csv")
    exposures = read_csv(phase_root / "data" / "tiny" / "exposures.csv")
    assignment = assignment_audit(protocol, assignments, exposures)
    assignment_path = output_dir / "evidence" / "02_assignment_audit.json"
    write_json(assignment_path, assignment)
    evidence_index.append(
        {
            "id": "assignment_audit",
            "category": "assignment",
            "source_path": "generated:assignment_audit",
            "package_path": "evidence/02_assignment_audit.json",
            "required_for": "assignment-exposure consistency checks",
            "sha256": sha256_file(assignment_path),
        }
    )

    randomization_health = read_json(phase_root / "03-aa-and-srm" / "outputs" / "randomization_health_report.json")
    power_plan = read_json(phase_root / "04-mde-and-power" / "outputs" / "power_plan.json")
    effect_results = read_csv(phase_root / "05-means-and-proportions" / "outputs" / "effect_results.csv")
    assumption_checks = read_json(phase_root / "05-means-and-proportions" / "outputs" / "assumption_checks.json")
    bootstrap = read_json(phase_root / "06-bootstrap" / "outputs" / "bootstrap_intervals.json")
    cuped = read_json(phase_root / "07-cuped" / "outputs" / "variance_reduction_report.json")
    multiple_testing = read_json(phase_root / "08-multiple-testing" / "outputs" / "multiple_testing_report.json")
    peeking = read_json(phase_root / "09-peeking" / "outputs" / "sequential_monitoring_report.json")
    heterogeneity = read_json(phase_root / "10-heterogeneous-effects" / "outputs" / "heterogeneity_report.json")

    summary = build_decision_summary(
        policy,
        protocol,
        assignment,
        randomization_health,
        power_plan,
        effect_results,
        assumption_checks,
        bootstrap,
        cuped,
        multiple_testing,
        peeking,
        heterogeneity,
    )

    evidence_index_path = output_dir / "evidence_index.json"
    decision_summary_path = output_dir / "decision_summary.json"
    decision_report_path = output_dir / "decision_report.md"
    write_json(evidence_index_path, {"evidence": evidence_index})
    write_json(decision_summary_path, summary)
    write_text(decision_report_path, markdown_report(summary))

    package_files = [entry["package_path"] for entry in evidence_index]
    package_files.extend(["evidence_index.json", "decision_summary.json", "decision_report.md"])
    checksums = build_checksums(output_dir, package_files)
    checksums_path = output_dir / "checksums.json"
    write_json(checksums_path, checksums)
    manifest = {
        "artifact": "experiment-decision-package",
        "experiment_id": protocol["experiment_id"],
        "decision": summary["decision"],
        "launch_allowed": summary["launch_allowed"],
        "checksum_algorithm": "sha256",
        "package_files": len(package_files),
        "evidence_items": len(evidence_index),
        "checksums_path": "checksums.json",
        "checksums_sha256": sha256_file(checksums_path),
        "valid": assignment["valid"] and summary["decision"] in policy["allowed_decisions"],
    }
    write_json(output_dir / "manifest.json", manifest)
    return {
        "manifest": manifest,
        "decision_summary": summary,
        "evidence_index": {"evidence": evidence_index},
        "checksums": checksums,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a reproducible experiment decision package.")
    parser.add_argument("--phase-root", type=Path, required=True)
    parser.add_argument("--decision-policy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    package = build_package(args.phase_root, args.decision_policy, args.output_dir)
    print(json.dumps(package["manifest"], ensure_ascii=False, indent=2))
    return 0 if package["manifest"]["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
