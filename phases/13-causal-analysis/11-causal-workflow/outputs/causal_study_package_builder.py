from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = PHASE_ROOT.parents[1]
DEFAULT_SPEC = LESSON_ROOT / "outputs" / "causal_workflow_spec.json"
DEFAULT_OUTPUT = LESSON_ROOT / "outputs" / "causal_study_package.json"
DEFAULT_MANIFEST = LESSON_ROOT / "outputs" / "checksum_manifest.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    valid: bool,
    *,
    severity: str = "error",
    sample: Any = None,
    message: str = "",
) -> None:
    payload: dict[str, Any] = {
        "id": check_id,
        "valid": bool(valid),
        "severity": severity,
    }
    if message:
        payload["message"] = message
    if sample is not None:
        payload["sample"] = sample
    checks.append(payload)


def blocking_checks(checks: list[dict[str, Any]]) -> list[str]:
    return [
        check["id"]
        for check in checks
        if not check["valid"] and check["severity"] == "error"
    ]


def warning_checks(checks: list[dict[str, Any]]) -> list[str]:
    return [
        check["id"]
        for check in checks
        if not check["valid"] and check["severity"] == "warning"
    ]


def resolve_path(relative_path: str) -> Path:
    path = REPO_ROOT / relative_path
    if path.exists():
        return path
    return PHASE_ROOT.parent / relative_path


def load_sources(
    spec: dict[str, Any],
    checks: list[dict[str, Any]],
) -> tuple[dict[str, dict], list[dict]]:
    sources: dict[str, dict[str, Any]] = {}
    manifest_entries: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    invalid_json: list[dict[str, str]] = []
    for source in spec["source_files"]:
        path = resolve_path(source["path"])
        if not path.exists():
            missing.append({"id": source["id"], "path": source["path"]})
            continue
        try:
            payload = read_json(path)
        except json.JSONDecodeError as error:
            invalid_json.append({"id": source["id"], "path": source["path"], "error": str(error)})
            continue
        sources[source["id"]] = payload
        manifest_entries.append(
            {
                "id": source["id"],
                "section": source["section"],
                "path": source["path"],
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    add_check(
        checks,
        "all_required_sources_are_present",
        not missing,
        sample=missing or None,
        message="The final causal-study-package must reference every upstream artifact.",
    )
    add_check(
        checks,
        "all_required_sources_are_valid_json",
        not invalid_json,
        sample=invalid_json or None,
        message="Every upstream source in the package manifest must be parseable JSON.",
    )
    return sources, manifest_entries


def upstream_validity(sources: dict[str, dict[str, Any]], checks: list[dict[str, Any]]) -> None:
    invalid = [
        {"id": source_id, "summary": payload.get("summary", {})}
        for source_id, payload in sources.items()
        if "valid" in payload and payload.get("valid") is not True
    ]
    add_check(
        checks,
        "upstream_audits_are_structurally_valid",
        not invalid,
        sample=invalid or None,
        message="Warnings may exist, but upstream artifacts must be structurally valid.",
    )


def summarize_question(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    question_summary = sources["question_audit"]["summary"]
    causal_question = sources["causal_question"]
    estimand = sources["estimand"]
    return {
        "question_id": question_summary["question_id"],
        "business_decision": causal_question.get("business_decision"),
        "estimand_id": question_summary["estimand_id"],
        "estimand_type": question_summary["estimand_type"],
        "population_scope": question_summary["population_scope"],
        "effect_measure": question_summary["effect_measure"],
        "target_population_users": question_summary["target_population_users"],
        "treatment": estimand.get("treatment_strategy"),
        "comparator": estimand.get("comparator_strategy"),
        "outcome": estimand.get("outcome_id"),
    }


def summarize_model(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dag_summary = sources["dag_audit"]["summary"]
    return {
        "graph_id": dag_summary["graph_id"],
        "nodes": dag_summary["nodes"],
        "edges": dag_summary["edges"],
        "treatment": dag_summary["treatment"],
        "outcome": dag_summary["outcome"],
        "intervention_operation": dag_summary["intervention_graph"]["operation"],
        "removed_incoming_edges": dag_summary["intervention_graph"]["removed_incoming_edges"],
    }


def summarize_identification(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    dag_summary = sources["dag_audit"]["summary"]
    backdoor_summary = sources["backdoor_adjustment_audit"]["summary"]
    bad_control_summary = sources["bad_control_selection_audit"]["summary"]
    return {
        "graph_identification_status": dag_summary["identification_status"],
        "active_backdoor_paths_without_adjustment": dag_summary[
            "active_backdoor_paths_without_adjustment"
        ],
        "active_backdoor_paths_after_measured_adjustment": dag_summary[
            "active_backdoor_paths_after_measured_adjustment"
        ],
        "backdoor_identification_status": backdoor_summary["identification_status"],
        "primary_adjustment_set": backdoor_summary["primary_recommendation"],
        "measured_confounders": backdoor_summary["measured_confounders"],
        "unmeasured_confounders": backdoor_summary["unmeasured_confounders"],
        "bad_control_allowed_action": bad_control_summary.get("primary_recommendation"),
        "forbidden_controls": bad_control_summary.get("bad_control_variables"),
    }


def estimate_row(
    estimate_id: str,
    source: str,
    estimand: str,
    estimate: float | int | None,
    *,
    claim_allowed: bool | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "estimate_id": estimate_id,
        "source": source,
        "estimand": estimand,
        "estimate": estimate,
        "claim_allowed": claim_allowed,
        "warnings": warnings or [],
        "poolable": False,
    }


def summarize_estimates(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    g = sources["g_formula_report"]["summary"]
    matching = sources["matching_report"]["summary"]
    ipw = sources["ipw_aipw_report"]["summary"]
    did = sources["did_report"]["summary"]
    quasi = sources["quasi_experiment_report"]["summary"]
    rows = [
        estimate_row(
            "g_formula_manual_ate",
            "13/05",
            "ATE_under_outcome_regression",
            g["manual_ate"],
            claim_allowed=g["effect_claim_allowed"],
            warnings=g["warning_checks"],
        ),
        estimate_row(
            "matching_att",
            "13/06",
            "ATT_after_matching_population_change",
            matching["matched_att"],
            claim_allowed=False,
            warnings=matching["warning_checks"],
        ),
        estimate_row(
            "ipw_hajek_ate",
            "13/07",
            "ATE_under_propensity_weighting",
            ipw["ipw_hajek_ate"],
            claim_allowed=ipw["allowed_effect_claim"],
            warnings=ipw["warning_checks"],
        ),
        estimate_row(
            "aipw_ate",
            "13/07",
            "ATE_under_doubly_robust_assumptions",
            ipw["aipw_ate"],
            claim_allowed=ipw["allowed_effect_claim"],
            warnings=ipw["warning_checks"],
        ),
        estimate_row(
            "did_estimate",
            "13/08",
            "regional_rollout_ATT_under_parallel_trends",
            did["did_estimate"],
            claim_allowed=did["allowed_effect_claim"],
            warnings=did["warning_checks"],
        ),
        estimate_row(
            "rdd_wald_local_effect_diagnostic",
            "13/09",
            "local_cutoff_diagnostic",
            quasi["rdd_wald_local_effect_diagnostic"],
            claim_allowed=False,
            warnings=["rdd_tiny_wald_estimate_is_diagnostic_only"],
        ),
        estimate_row(
            "iv_wald_late",
            "13/09",
            "LATE_for_compliers",
            quasi["iv_wald_late"],
            claim_allowed=quasi["allowed_local_claim"],
            warnings=quasi["warning_checks"],
        ),
    ]
    estimates = [float(row["estimate"]) for row in rows if row["estimate"] is not None]
    return {
        "rows": rows,
        "min_estimate": min(estimates),
        "max_estimate": max(estimates),
        "range": max(estimates) - min(estimates),
        "pooling_allowed": False,
    }


def summarize_refutation(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sensitivity = sources["sensitivity_report"]
    summary = sensitivity["summary"]
    return {
        "allowed_effect_claim": summary["allowed_effect_claim"],
        "falsification_failures": summary["falsification_failures"],
        "required_bias_to_reach_null": summary["required_bias_to_reach_null"],
        "first_nulling_bias": summary["first_nulling_bias"],
        "design_estimate_range": summary["design_estimate_range"],
        "claim_blocking_reasons": summary["claim_blocking_reasons"],
        "recommended_wording": sensitivity["claim_policy"]["recommended_wording"],
    }


def dowhy_workflow_trace(package_sections: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "step": "model",
            "dowhy_surface": "CausalModel(data, treatment, outcome, graph)",
            "package_inputs": ["question", "model"],
            "status": "represented_by_package_trace",
            "boundary": (
                "Graph edges come from domain assumptions; automation must not invent them."
            ),
        },
        {
            "step": "identify",
            "dowhy_surface": "model.identify_effect()",
            "package_inputs": ["identify"],
            "status": package_sections["identify"]["backdoor_identification_status"],
            "boundary": (
                "Identification remains blocked for the primary backdoor ATE "
                "by unmeasured confounding."
            ),
        },
        {
            "step": "estimate",
            "dowhy_surface": "model.estimate_effect(identified_estimand, method_name=...)",
            "package_inputs": ["estimate"],
            "status": "transparent_estimates_reconciled_before_automation",
            "boundary": (
                "Estimation API cannot turn a weak design into an identified causal effect."
            ),
        },
        {
            "step": "refute",
            "dowhy_surface": "model.refute_estimate(...), placebo and subset refuters",
            "package_inputs": ["refute"],
            "status": "single_strong_claim_blocked",
            "boundary": "Refuters can falsify or weaken a claim; they do not prove assumptions.",
        },
    ]


def automation_audit(spec: dict[str, Any], package_sections: dict[str, Any]) -> dict[str, Any]:
    dowhy_available = importlib.util.find_spec("dowhy") is not None
    econml_available = importlib.util.find_spec("econml") is not None
    trace = dowhy_workflow_trace(package_sections)
    return {
        "dowhy_runtime_available": dowhy_available,
        "dowhy_dependency_policy": spec["workflow_contract"]["runtime_dependency_policy"],
        "dowhy_workflow_trace": trace,
        "dowhy_runtime_status": (
            "available_but_not_required_for_package_validation"
            if dowhy_available
            else "not_installed_trace_validates_workflow_contract"
        ),
        "econml_runtime_available": econml_available,
        "econml_scope_decision": {
            "used": False,
            "reason": (
                "The phase target is average/design-specific evidence, not CATE, "
                "DML or policy learning."
            ),
            "required_before_future_use": [
                "explicit heterogeneity estimand",
                "sufficient sample size",
                "separate ML validation",
                "identification already justified outside EconML",
            ],
        },
        "automation_must_not": spec["workflow_contract"]["automation_must_not"],
    }


def build_evidence_statement(package_sections: dict[str, Any]) -> dict[str, Any]:
    refute = package_sections["refute"]
    estimate = package_sections["estimate"]
    did = next(row for row in estimate["rows"] if row["estimate_id"] == "did_estimate")
    iv = next(row for row in estimate["rows"] if row["estimate_id"] == "iv_wald_late")
    aipw = next(row for row in estimate["rows"] if row["estimate_id"] == "aipw_ate")
    return {
        "final_claim_status": "blocked_single_strong_claim",
        "allowed_effect_claim": False,
        "headline": "Do not ship a single strong causal effect claim for assisted onboarding.",
        "design_specific_evidence": [
            {
                "design": "observational_aipw",
                "estimate": aipw["estimate"],
                "status": "blocked_by_falsification_and_unmeasured_confounding",
            },
            {
                "design": "regional_did",
                "estimate": did["estimate"],
                "status": "limited_rollout_att_under_parallel_trends_with_warnings",
            },
            {
                "design": "iv_encouragement",
                "estimate": iv["estimate"],
                "status": "limited_late_for_compliers_under_unverifiable_assumptions",
            },
        ],
        "blocking_reasons": refute["claim_blocking_reasons"],
        "recommended_next_step": (
            "Run a cleaner randomized encouragement or staged rollout with pre-registered "
            "estimand and stronger telemetry/negative-control plan before a broad rollout decision."
        ),
    }


def validate_package(
    spec: dict[str, Any],
    package_sections: dict[str, Any],
    manifest_entries: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> None:
    missing_sections = [
        section
        for section in spec["required_package_sections"]
        if section not in package_sections
    ]
    add_check(
        checks,
        "package_contains_required_sections",
        not missing_sections,
        sample=missing_sections or None,
        message="The final package must contain every handoff section.",
    )
    add_check(
        checks,
        "checksum_manifest_covers_all_sources",
        len(manifest_entries) == len(spec["source_files"]),
        sample={
            "manifest_entries": len(manifest_entries),
            "source_files": len(spec["source_files"]),
        },
        message="Every source file must be represented in the checksum manifest.",
    )
    trace_steps = [
        row["step"]
        for row in package_sections["automation_audit"]["dowhy_workflow_trace"]
    ]
    add_check(
        checks,
        "dowhy_workflow_trace_has_model_identify_estimate_refute",
        trace_steps == spec["workflow_contract"]["steps"],
        sample=trace_steps,
        message="Automation audit must preserve the DoWhy workflow order.",
    )
    add_check(
        checks,
        "automation_does_not_override_identification",
        package_sections["identify"]["backdoor_identification_status"]
        == "not_identified_due_to_unmeasured_confounding",
        sample=package_sections["identify"],
        message="Automation must not turn an unidentified primary ATE into an identified claim.",
    )
    add_check(
        checks,
        "final_claim_matches_sensitivity_policy",
        package_sections["evidence_statement"]["allowed_effect_claim"]
        == package_sections["refute"]["allowed_effect_claim"],
        sample={
            "evidence": package_sections["evidence_statement"]["allowed_effect_claim"],
            "refute": package_sections["refute"]["allowed_effect_claim"],
        },
        message="Final evidence statement must follow the sensitivity claim policy.",
    )
    add_check(
        checks,
        "different_estimands_are_not_pooled",
        package_sections["estimate"]["pooling_allowed"] is False,
        sample=package_sections["estimate"],
        message="The package may compare but must not average incompatible estimands.",
    )
    add_check(
        checks,
        "econml_is_not_used_without_heterogeneity_question",
        package_sections["automation_audit"]["econml_scope_decision"]["used"] is False,
        sample=package_sections["automation_audit"]["econml_scope_decision"],
        message="EconML is out of scope without an explicit CATE or policy-learning estimand.",
    )
    add_check(
        checks,
        "dowhy_runtime_is_optional_and_documented",
        package_sections["automation_audit"]["dowhy_runtime_status"]
        in {
            "not_installed_trace_validates_workflow_contract",
            "available_but_not_required_for_package_validation",
        },
        severity="warning",
        sample=package_sections["automation_audit"]["dowhy_runtime_status"],
        message=(
            "The package documents DoWhy workflow boundaries without requiring runtime "
            "installation."
        ),
    )


def build_package(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    sources, manifest_entries = load_sources(spec, checks)
    upstream_validity(sources, checks)
    if blocking_checks(checks):
        package = {
            "valid": False,
            "package_id": spec["package_id"],
            "summary": {
                "package_id": spec["package_id"],
                "source_files_n": len(manifest_entries),
                "allowed_effect_claim": False,
                "blocking_checks": blocking_checks(checks),
                "warning_checks": warning_checks(checks),
            },
            "checks": checks,
        }
        manifest = {"package_id": spec["package_id"], "files": manifest_entries}
        return package, manifest

    package_sections = {
        "question": summarize_question(sources),
        "model": summarize_model(sources),
        "identify": summarize_identification(sources),
        "estimate": summarize_estimates(sources),
        "refute": summarize_refutation(sources),
        "checksum_manifest": manifest_entries,
    }
    package_sections["automation_audit"] = automation_audit(spec, package_sections)
    package_sections["evidence_statement"] = build_evidence_statement(package_sections)
    validate_package(spec, package_sections, manifest_entries, checks)
    warning_ids = warning_checks(checks)
    blocking_ids = blocking_checks(checks)
    package = {
        "valid": not blocking_ids,
        "package_id": spec["package_id"],
        "summary": {
            "package_id": spec["package_id"],
            "source_files_n": len(manifest_entries),
            "workflow_steps": spec["workflow_contract"]["steps"],
            "estimate_rows_n": len(package_sections["estimate"]["rows"]),
            "final_claim_status": package_sections["evidence_statement"]["final_claim_status"],
            "allowed_effect_claim": package_sections["evidence_statement"]["allowed_effect_claim"],
            "dowhy_runtime_status": package_sections["automation_audit"]["dowhy_runtime_status"],
            "econml_used": package_sections["automation_audit"]["econml_scope_decision"]["used"],
            "blocking_checks": blocking_ids,
            "warning_checks": warning_ids,
        },
        **package_sections,
        "checks": checks,
    }
    manifest = {
        "package_id": spec["package_id"],
        "files": manifest_entries,
        "package_output": {
            "path": "phases/13-causal-analysis/11-causal-workflow/outputs/causal_study_package.json"
        },
    }
    return package, manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the final phase 13 causal-study-package."
    )
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--fail-on-invalid", action="store_true")
    args = parser.parse_args()

    package, manifest = build_package(read_json(args.spec))
    write_json(args.output, package)
    write_json(args.manifest, manifest)
    print(json.dumps(package["summary"], ensure_ascii=False, indent=2))
    if args.fail_on_invalid and not package["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
