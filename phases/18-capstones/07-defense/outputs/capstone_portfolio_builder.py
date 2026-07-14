from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any


PORTFOLIO_VERSION = "1.0.0"
PACKAGE_NAME = "capstone-portfolio-package"
REPO_ROOT = Path(__file__).resolve().parents[4]
PHASE_ROOT = REPO_ROOT / "phases" / "18-capstones"
IMPLEMENTATION_RUNNER = (
    PHASE_ROOT / "04-implementation" / "outputs" / "capstone_route_implementation.py"
)
ALLOWED_CHALLENGE_CLASSES = {
    "data_defect",
    "method_assumption",
    "alternative_explanation",
    "failed_deployment_condition",
    "changed_business_constraint",
}
ALLOWED_ANSWER_STATUSES = {"bounded_answer", "unknown_with_testable_next_step"}
REQUIRED_BRIEF_SECTIONS = [
    "decision",
    "data",
    "baseline",
    "method",
    "result",
    "limitations",
    "recommendation",
    "next_step",
]
RUBRIC_DIMENSIONS = [
    ("problem_framing", "Problem framing"),
    ("data_contract", "Data contract"),
    ("method_and_baseline", "Method and baseline"),
    ("verification", "Verification"),
    ("delivery_and_handoff", "Delivery and handoff"),
    ("review_and_defense", "Review and defense"),
]
CRITICAL_BLOCKER_IDS = [
    "decision_scope_or_route_not_ready",
    "data_contract_rights_or_privacy_not_ready",
    "documented_locked_build_not_reproducible",
    "required_checksum_mismatch",
    "defense_claim_not_supported_or_too_broad",
    "route_specific_verification_failed",
    "public_package_contains_restricted_material",
    "independent_verification_not_reproduced",
    "review_blocker_or_major_open",
    "defense_differs_from_reviewed_package",
]
FORBIDDEN_PUBLIC_MARKERS = [
    "TOKEN=",
    "SECRET=",
    "PASSWORD=",
    "API_KEY=",
    "BEGIN PRIVATE KEY",
    "sk_live_",
    "ya_oauth",
]
RESTRICTED_PUBLIC_COLUMNS = {
    "email",
    "phone",
    "full_name",
    "address",
    "access_token",
    "password",
    "secret",
}
TEXT_SUFFIXES = {".csv", ".json", ".md", ".py", ".txt", ".yml", ".yaml"}

STAGE_DEFINITIONS = {
    "brief": {
        "manifest": "brief_manifest.json",
        "status": "ready_for_data_contract",
        "current_stage": "problem_selection",
    },
    "data": {
        "manifest": "data_package_manifest.json",
        "status": "data_ready",
        "current_stage": "data_contract",
    },
    "baseline": {
        "manifest": "baseline_manifest.json",
        "status": "baseline_ready",
        "current_stage": "baseline",
    },
    "implementation": {
        "manifest": "implementation_manifest.json",
        "status": "implementation_ready",
        "current_stage": "implementation",
    },
    "verification": {
        "manifest": "verification_manifest.json",
        "status": "verification_ready",
        "current_stage": "verification",
    },
    "review": {
        "manifest": "review_manifest.json",
        "status": "review_ready",
        "current_stage": "review",
    },
}

CANONICAL_STAGE_FILES = {
    "brief": {
        "capstone_brief_audit.json": "brief/brief-audit.json",
        "risk_register.csv": "brief/risk-register.csv",
        "milestone_plan.csv": "brief/milestone-plan.csv",
        "capstone_state.json": "brief/stage-state.json",
        "brief_manifest.json": "brief/source-manifest.json",
    },
    "data": {
        "data_contract.json": "data/data-contract.json",
        "dataset_manifest.json": "data/dataset-manifest.json",
        "data_audit.json": "data/data-audit.json",
        "lineage_report.csv": "data/lineage-report.csv",
        "checksum_inventory.csv": "data/checksum-inventory.csv",
        "public_data_sample.csv": "data/public-data-sample/data.csv",
        "capstone_state.json": "data/stage-state.json",
        "data_package_manifest.json": "data/source-manifest.json",
    },
    "baseline": {
        "baseline_spec.json": "baseline/baseline-spec.json",
        "baseline_report.json": "baseline/baseline-report.json",
        "baseline_metrics.csv": "baseline/baseline-metrics.csv",
        "baseline_decision.json": "baseline/baseline-decision.json",
        "manual_reconciliation.csv": "baseline/manual-cross-check.csv",
        "acceptance_gate.json": "baseline/acceptance-gate.json",
        "complexity_budget.json": "baseline/complexity-budget.json",
        "capstone_state.json": "baseline/stage-state.json",
        "baseline_manifest.json": "baseline/source-manifest.json",
    },
    "implementation": {
        "implementation_spec.json": "implementation/config/implementation-spec.json",
        "implementation_config.json": "implementation/config/implementation-config.json",
        "implementation_report.json": "implementation/implementation-report.json",
        "route_adapter_report.json": "implementation/route-adapter-report.json",
        "candidate_metrics.csv": "implementation/outputs/candidate-metrics.csv",
        "candidate_decision.json": "implementation/outputs/candidate-decision.json",
        "candidate_acceptance.json": "implementation/outputs/candidate-acceptance.json",
        "evidence_ledger.csv": "implementation/evidence-ledger.csv",
        "run_trace.csv": "implementation/run-trace.csv",
        "capstone_state.json": "implementation/stage-state.json",
        "implementation_manifest.json": "implementation/run-manifest.json",
    },
    "verification": {
        "verification_spec.json": "verification/verification-spec.json",
        "verification_report.json": "verification/verification-report.json",
        "clean_room_rerun.json": "verification/clean-room-rerun.json",
        "shadow_calculation.csv": "verification/shadow-calculation.csv",
        "failure_fixture_results.csv": "verification/failure-fixture-results.csv",
        "sensitivity_report.csv": "verification/sensitivity-report.csv",
        "claim_evidence_audit.csv": "verification/claim-evidence-audit.csv",
        "route_verification_report.json": "verification/route-verification-report.json",
        "test_results.json": "verification/test-results.json",
        "capstone_state.json": "verification/stage-state.json",
        "verification_manifest.json": "verification/source-manifest.json",
    },
    "review": {
        "review_spec.json": "review/review-spec.json",
        "review_report.json": "review/review-report.json",
        "review_rubric.json": "review/review-rubric.json",
        "finding_ledger.csv": "review/finding-ledger.csv",
        "author_responses.csv": "review/author-responses.csv",
        "reviewed_claims.json": "review/reviewed-claims.json",
        "changed_file_inventory.csv": "review/changed-file-inventory.csv",
        "rerun_results.json": "review/rerun-results.json",
        "re_review_report.json": "review/re-review-report.json",
        "capstone_state.json": "review/stage-state.json",
        "review_manifest.json": "review/source-manifest.json",
    },
}

REQUIRED_PACKAGE_FILES = [
    "brief/capstone-brief.json",
    "brief/risk-register.csv",
    "brief/milestone-plan.csv",
    "data/data-contract.json",
    "data/dataset-manifest.json",
    "data/data-audit.json",
    "data/public-data-sample/data.csv",
    "baseline/baseline-report.json",
    "baseline/manual-cross-check.csv",
    "baseline/complexity-budget.json",
    "implementation/config/implementation-spec.json",
    "implementation/src/implementation-runner.py",
    "implementation/outputs/candidate-metrics.csv",
    "implementation/evidence-ledger.csv",
    "implementation/run-manifest.json",
    "verification/verification-report.json",
    "verification/shadow-calculation.csv",
    "verification/failure-fixture-results.csv",
    "verification/test-results.json",
    "review/review-rubric.json",
    "review/finding-ledger.csv",
    "review/author-responses.csv",
    "review/re-review-report.json",
    "defense/defense-spec.json",
    "defense/defense-brief.md",
    "defense/demo-script.md",
    "defense/challenge-questions.json",
    "defense/decision-report.md",
    "defense/live-rerun-report.json",
    "defense/defense-audit.json",
    "handoff/README.md",
    "handoff/runbook.md",
    "handoff/limitations.md",
    "handoff/assistance-disclosure.md",
    "handoff/stage-provenance.json",
    "handoff/claim-evidence-index.csv",
    "capstone-state.json",
    "rubric-result.json",
    "manifest.json",
]


def read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def write_json(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def write_text(path: str | Path, value: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")
    return target


def read_csv(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: str | Path, rows: list[dict[str, Any]], fields: list[str]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: json.dumps(row.get(field), sort_keys=True)
                    if isinstance(row.get(field), (dict, list))
                    else str(row.get(field)).lower()
                    if isinstance(row.get(field), bool)
                    else row.get(field, "")
                    for field in fields
                }
            )
    return target


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def safe_relative_path(value: Any) -> bool:
    if not non_empty_text(value):
        return False
    path = Path(str(value).split("#", 1)[0])
    return not path.is_absolute() and ".." not in path.parts


def check(
    check_id: str,
    valid: bool,
    *,
    observed: Any,
    expected: Any,
    message: str,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": bool(valid),
        "severity": "block",
        "observed": observed,
        "expected": expected,
        "message": message,
    }


def directory_checksums(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_dir():
        return {}
    return {
        item.relative_to(path).as_posix(): {
            "sha256": sha256_file(item),
            "bytes": item.stat().st_size,
        }
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def manifest_output_errors(package: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        return [{"field": "outputs", "reason": "non-empty object required"}]
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for output_id, entry in outputs.items():
        if not isinstance(entry, dict):
            errors.append({"field": f"outputs.{output_id}", "reason": "object required"})
            continue
        relative = entry.get("path")
        if not safe_relative_path(relative):
            errors.append({"field": f"outputs.{output_id}.path", "observed": relative})
            continue
        relative = str(relative)
        if relative in seen:
            errors.append({"field": f"outputs.{output_id}.path", "reason": "duplicate"})
        seen.add(relative)
        target = package / relative
        if not target.is_file():
            errors.append({"field": f"outputs.{output_id}.path", "reason": "missing"})
            continue
        actual_hash = sha256_file(target)
        if actual_hash != entry.get("sha256"):
            errors.append(
                {
                    "field": f"outputs.{output_id}.sha256",
                    "expected": entry.get("sha256"),
                    "observed": actual_hash,
                }
            )
        if target.stat().st_size != entry.get("bytes"):
            errors.append(
                {
                    "field": f"outputs.{output_id}.bytes",
                    "expected": entry.get("bytes"),
                    "observed": target.stat().st_size,
                }
            )
    return errors


def validate_stage_package(
    stage: str, package: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    definition = STAGE_DEFINITIONS[stage]
    manifest_path = package / definition["manifest"]
    state_path = package / "capstone_state.json"
    missing = [
        name
        for name, path in (
            (definition["manifest"], manifest_path),
            ("capstone_state.json", state_path),
        )
        if not path.is_file()
    ]
    if missing:
        result = check(
            f"{stage}_package_is_ready_and_immutable",
            False,
            observed={"missing": missing, "errors": []},
            expected=f"complete {definition['status']} package with manifest",
            message="Every defense stage must preserve its independently verified bytes.",
        )
        return result, {}, {}
    manifest = read_json(manifest_path)
    state = read_json(state_path)
    errors = manifest_output_errors(package, manifest)
    if manifest.get("status") != definition["status"] or manifest.get("valid") is not True:
        errors.append(
            {
                "field": "manifest.status",
                "expected": definition["status"],
                "observed": manifest.get("status"),
            }
        )
    if (
        state.get("current_stage") != definition["current_stage"]
        or state.get("stage_status") != definition["status"]
    ):
        errors.append(
            {
                "field": "capstone_state.stage",
                "expected": [definition["current_stage"], definition["status"]],
                "observed": [state.get("current_stage"), state.get("stage_status")],
            }
        )
    if manifest.get("project_id") != state.get("project_id"):
        errors.append({"field": "project_id", "reason": "manifest and state disagree"})
    result = check(
        f"{stage}_package_is_ready_and_immutable",
        not errors,
        observed={"errors": errors, "verified_outputs": len(manifest.get("outputs", {}))},
        expected=f"complete {definition['status']} package with matching SHA-256 outputs",
        message="Every defense stage must preserve its independently verified bytes.",
    )
    return result, manifest, state


def manifest_input_hash(manifest: dict[str, Any], input_id: str) -> str | None:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        return None
    entry = inputs.get(input_id)
    return entry.get("sha256") if isinstance(entry, dict) else None


def validate_stage_chain(
    packages: dict[str, Path], manifests: dict[str, dict[str, Any]], states: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    projects = {state.get("project_id") for state in states.values() if state}
    routes = {state.get("route") for state in states.values() if state}
    variants = {state.get("route_variant") for state in states.values() if state}
    if len(projects) != 1:
        errors.append({"field": "project_id", "observed": sorted(str(item) for item in projects)})
    if len(routes) != 1 or len(variants) != 1:
        errors.append(
            {
                "field": "route",
                "routes": sorted(str(item) for item in routes),
                "variants": sorted(str(item) for item in variants),
            }
        )
    bindings = [
        ("data", "upstream_capstone_state", "brief", "capstone_state.json"),
        ("baseline", "upstream_data_manifest", "data", "data_package_manifest.json"),
        (
            "implementation",
            "upstream_baseline_manifest",
            "baseline",
            "baseline_manifest.json",
        ),
        (
            "verification",
            "upstream_implementation_manifest",
            "implementation",
            "implementation_manifest.json",
        ),
        (
            "review",
            "upstream_verification_manifest",
            "verification",
            "verification_manifest.json",
        ),
    ]
    for downstream, input_id, upstream, filename in bindings:
        source = packages[upstream] / filename
        expected = sha256_file(source) if source.is_file() else None
        observed = manifest_input_hash(manifests.get(downstream, {}), input_id)
        if expected != observed:
            errors.append(
                {
                    "field": f"{downstream}.inputs.{input_id}.sha256",
                    "expected": expected,
                    "observed": observed,
                }
            )
    final_state = states.get("review", {})
    for field in (
        "data_contract_id",
        "baseline_id",
        "implementation_id",
        "verification_id",
        "review_id",
    ):
        expected = final_state.get(field)
        values = {
            state.get(field)
            for state in states.values()
            if state and state.get(field) is not None
        }
        if values != {expected}:
            errors.append({"field": field, "expected": expected, "observed": sorted(values)})
    return check(
        "stage_chain_is_continuous_and_checksum_bound",
        not errors,
        observed={"errors": errors, "stages": list(STAGE_DEFINITIONS)},
        expected="six ordered stages with one project, route, IDs and upstream hash chain",
        message="A collection of individually valid packages is insufficient without continuity.",
    )


def nested_forbidden_keys(value: Any, forbidden: set[str], prefix: str = "") -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in forbidden:
                result.append(path)
            result.extend(nested_forbidden_keys(child, forbidden, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(nested_forbidden_keys(child, forbidden, f"{prefix}[{index}]"))
    return result


def default_defense_spec(review_state: dict[str, Any], runner: Path) -> dict[str, Any]:
    return {
        "version": PORTFOLIO_VERSION,
        "project_id": review_state.get("project_id"),
        "review_id": review_state.get("review_id"),
        "defense_id": "weekly-retention-core-defense-v1",
        "reviewed_manifest_sha256": sha256_file(
            PHASE_ROOT / "06-peer-review" / "outputs" / "review_manifest.json"
        ),
        "required_brief_sections": REQUIRED_BRIEF_SECTIONS,
        "max_defense_minutes": 10,
        "challenge_policy": {
            "allowed_classes": sorted(ALLOWED_CHALLENGE_CLASSES),
            "minimum_distinct_classes": 3,
            "allowed_answer_statuses": sorted(ALLOWED_ANSWER_STATUSES),
        },
        "live_rerun": {
            "implementation_runner_sha256": sha256_file(runner),
            "timeout_seconds": 30,
            "check_mode_required": True,
            "verify_command": (
                "uv run --locked python "
                "phases/18-capstones/07-defense/outputs/"
                "capstone_portfolio_builder.py --verify-package "
                "path/to/capstone-portfolio-package"
            ),
        },
        "rubric_policy": {
            "dimension_ids": [item[0] for item in RUBRIC_DIMENSIONS],
            "score_min": 0,
            "score_max": 4,
            "passed": {
                "minimum_each": 2,
                "critical_minimum": 3,
                "critical_dimensions": [
                    "data_contract",
                    "method_and_baseline",
                    "verification",
                ],
                "minimum_total": 18,
            },
            "passed_with_distinction": {
                "minimum_each": 3,
                "minimum_total": 22,
            },
        },
        "critical_blocker_ids": CRITICAL_BLOCKER_IDS,
        "public_package_policy": {
            "raw_sources_allowed": False,
            "pii_allowed": False,
            "secrets_allowed": False,
            "aggregate_or_synthetic_sample_required": True,
        },
        "required_package_files": REQUIRED_PACKAGE_FILES,
        "created_before_defense": True,
    }


def reference_defense_submission(review_manifest_sha256: str) -> dict[str, Any]:
    return {
        "version": PORTFOLIO_VERSION,
        "project_id": "weekly-retention-decision-core",
        "review_id": "weekly-retention-core-review-v1",
        "defense_id": "weekly-retention-core-defense-v1",
        "reviewed_manifest_sha256": review_manifest_sha256,
        "presenter": {"author_id": "learner-reference-author", "accountable": True},
        "evaluator": {
            "evaluator_id": "independent-defense-agent-01",
            "evaluator_type": "independent_agent",
            "is_project_author": False,
            "conflict_of_interest": False,
            "clean_context": True,
            "assistance_disclosure": (
                "Independent agent evaluates the reviewed package, live rerun and "
                "challenge answers without rewriting project evidence."
            ),
        },
        "defense_brief": {
            "duration_minutes": 9,
            "sections": {
                "decision": (
                    "Support operations must choose between the current weekly review "
                    "and a predeclared targeted manual-review policy."
                ),
                "data": (
                    "The public evidence is an aggregate tiny sample with explicit grain, "
                    "rights, privacy policy, freshness and known defects."
                ),
                "baseline": (
                    "The no-action baseline captures 0.666667 of observed churn under a "
                    "four-user review capacity."
                ),
                "method": (
                    "A frozen weighted segment adapter ranks high_touch first without "
                    "claiming an intervention effect."
                ),
                "result": (
                    "Candidate value is 0.666667 below the frozen 0.766667 threshold, so "
                    "the retained method is baseline."
                ),
                "limitations": (
                    "The tiny two-segment profile is threshold-sensitive, descriptive "
                    "and not production or causal evidence."
                ),
                "recommendation": (
                    "Keep the current weekly review and use the ranking only as a "
                    "diagnostic input for manual investigation."
                ),
                "next_step": (
                    "Collect a larger longitudinal sample and predeclare an evaluation "
                    "that can test decision utility under operational capacity."
                ),
            },
        },
        "defense_claims": [
            {
                "claim_id": "defense-claim-01",
                "statement": "The frozen acceptance gate retains baseline.",
                "claim_type": "descriptive",
                "evidence_path": (
                    "verification:verification_report.json#summary.selected_method"
                ),
                "limitation": "A lower post-hoc threshold produces one sensitivity flip.",
            },
            {
                "claim_id": "defense-claim-02",
                "statement": "The weighted adapter ranks high_touch first.",
                "claim_type": "descriptive",
                "evidence_path": (
                    "implementation:candidate_metrics.csv#segment_id=high_touch"
                ),
                "limitation": "Observed ranking is not a causal intervention effect.",
            },
            {
                "claim_id": "defense-claim-03",
                "statement": "All three peer-review findings are independently closed.",
                "claim_type": "process",
                "evidence_path": "review:re_review_report.json#summary.open_findings",
                "limitation": "Review closure is not production certification.",
            },
        ],
        "demo": {
            "duration_minutes": 4,
            "check_mode": True,
            "verify_command": (
                "uv run --locked python "
                "phases/18-capstones/07-defense/outputs/"
                "capstone_portfolio_builder.py --verify-package "
                "path/to/capstone-portfolio-package"
            ),
            "steps": [
                "Show the reviewed manifest hash and final state.",
                "Run package check mode and inspect the zero exit code.",
                "Show the implementation rerun output comparisons.",
                "Trace the retained baseline claim to verification evidence.",
                "Open limitations and the next-step contract.",
            ],
        },
        "challenge_questions": [
            {
                "question_id": "challenge-01",
                "class": "data_defect",
                "question": "What happens if aggregate keys stop being unique?",
                "answer_status": "bounded_answer",
                "answer": "The data gate blocks and downstream checksums become stale.",
                "claim_boundary": "No decision is valid until grain is restored.",
                "evidence_path": "data:data_audit.json#checks",
                "next_check": "Rerun data audit, baseline and every downstream stage.",
            },
            {
                "question_id": "challenge-02",
                "class": "method_assumption",
                "question": "Why not lower the practical threshold after seeing the result?",
                "answer_status": "bounded_answer",
                "answer": "That would replace a frozen gate with a post-hoc selection rule.",
                "claim_boundary": "Sensitivity describes dependence but does not move the gate.",
                "evidence_path": "verification:sensitivity_report.csv#frozen_gate",
                "next_check": "Predeclare a new threshold in a new project version.",
            },
            {
                "question_id": "challenge-03",
                "class": "alternative_explanation",
                "question": "Does high_touch ranking prove support outreach reduces churn?",
                "answer_status": "bounded_answer",
                "answer": "No; observed priority may reflect baseline risk or support burden.",
                "claim_boundary": "The project makes a descriptive ranking claim only.",
                "evidence_path": "implementation:evidence_ledger.csv#implementation-claim-01",
                "next_check": "Use an identified experiment before any causal claim.",
            },
            {
                "question_id": "challenge-04",
                "class": "failed_deployment_condition",
                "question": "What if the weekly owner or freshness process is unavailable?",
                "answer_status": "unknown_with_testable_next_step",
                "answer": "Operational reliability is not known from this tiny profile.",
                "claim_boundary": "The package is a reproducible handoff, not an SLA claim.",
                "evidence_path": "review:review_report.json#summary.warnings",
                "next_check": "Run an owned scheduled pilot with freshness and escalation tests.",
            },
            {
                "question_id": "challenge-05",
                "class": "changed_business_constraint",
                "question": "What if review capacity falls from four users to three?",
                "answer_status": "bounded_answer",
                "answer": "The predeclared capacity sensitivity keeps baseline selected.",
                "claim_boundary": "The conclusion applies only to evaluated capacities.",
                "evidence_path": "verification:sensitivity_report.csv#capacity_minus_one",
                "next_check": "Recalculate utility for any new sustained capacity constraint.",
            },
        ],
        "public_release": {
            "raw_sources_included": False,
            "pii_included": False,
            "secrets_included": False,
            "sample_kind": "aggregate_reference_tiny",
        },
        "assistance_disclosure": {
            "ai_assistance_used": True,
            "author_accountable_for_claims": True,
            "verified_before_release": True,
        },
        "defended_at": "2026-01-14T12:00:00Z",
    }


def validate_defense_spec(
    spec: dict[str, Any], review_state: dict[str, Any], review_manifest_sha: str, runner: Path
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    for field, expected in (
        ("project_id", review_state.get("project_id")),
        ("review_id", review_state.get("review_id")),
        ("reviewed_manifest_sha256", review_manifest_sha),
    ):
        if spec.get(field) != expected:
            errors.append({"field": field, "expected": expected, "observed": spec.get(field)})
    if not non_empty_text(spec.get("defense_id")):
        errors.append({"field": "defense_id", "reason": "required"})
    if spec.get("required_brief_sections") != REQUIRED_BRIEF_SECTIONS:
        errors.append({"field": "required_brief_sections", "expected": REQUIRED_BRIEF_SECTIONS})
    if spec.get("max_defense_minutes") != 10:
        errors.append({"field": "max_defense_minutes", "expected": 10})
    challenge = spec.get("challenge_policy") if isinstance(spec.get("challenge_policy"), dict) else {}
    if set(challenge.get("allowed_classes", [])) != ALLOWED_CHALLENGE_CLASSES:
        errors.append({"field": "challenge_policy.allowed_classes"})
    if challenge.get("minimum_distinct_classes", 0) < 3:
        errors.append({"field": "challenge_policy.minimum_distinct_classes"})
    live = spec.get("live_rerun") if isinstance(spec.get("live_rerun"), dict) else {}
    runner_hash = sha256_file(runner) if runner.is_file() else None
    if live.get("implementation_runner_sha256") != runner_hash:
        errors.append(
            {
                "field": "live_rerun.implementation_runner_sha256",
                "expected": runner_hash,
                "observed": live.get("implementation_runner_sha256"),
            }
        )
    rubric = spec.get("rubric_policy") if isinstance(spec.get("rubric_policy"), dict) else {}
    if rubric.get("dimension_ids") != [item[0] for item in RUBRIC_DIMENSIONS]:
        errors.append({"field": "rubric_policy.dimension_ids"})
    if spec.get("critical_blocker_ids") != CRITICAL_BLOCKER_IDS:
        errors.append({"field": "critical_blocker_ids"})
    if spec.get("required_package_files") != REQUIRED_PACKAGE_FILES:
        errors.append({"field": "required_package_files"})
    forbidden = nested_forbidden_keys(
        spec,
        {"final_status", "rubric_result", "observed_score", "observed_result"},
    )
    if forbidden:
        errors.append({"field": "predeclared_spec", "forbidden_result_fields": forbidden})
    return check(
        "defense_spec_is_predeclared_and_bound_to_review",
        not errors,
        observed={"errors": errors, "defense_id": spec.get("defense_id")},
        expected="review-bound timing, challenge, live-rerun, blocker and rubric contract",
        message="Defense rules must be fixed before presentation and scoring are observed.",
    )


def validate_evaluator(submission: dict[str, Any]) -> dict[str, Any]:
    presenter = submission.get("presenter") if isinstance(submission.get("presenter"), dict) else {}
    evaluator = submission.get("evaluator") if isinstance(submission.get("evaluator"), dict) else {}
    errors: list[dict[str, Any]] = []
    if not non_empty_text(presenter.get("author_id")) or presenter.get("accountable") is not True:
        errors.append({"field": "presenter", "reason": "accountable author required"})
    if not non_empty_text(evaluator.get("evaluator_id")):
        errors.append({"field": "evaluator.evaluator_id", "reason": "required"})
    if (
        evaluator.get("evaluator_id") == presenter.get("author_id")
        or evaluator.get("is_project_author") is not False
    ):
        errors.append({"field": "evaluator.independence", "reason": "author cannot evaluate"})
    if evaluator.get("conflict_of_interest") is not False:
        errors.append({"field": "evaluator.conflict_of_interest", "reason": "must be false"})
    if evaluator.get("evaluator_type") == "independent_agent" and (
        evaluator.get("clean_context") is not True
        or not non_empty_text(evaluator.get("assistance_disclosure"))
    ):
        errors.append({"field": "evaluator.agent_disclosure", "reason": "required"})
    return check(
        "defense_evaluator_is_independent_and_disclosed",
        not errors,
        observed={"errors": errors, "evaluator_type": evaluator.get("evaluator_type")},
        expected="accountable presenter and independent disclosed evaluator",
        message="A polished self-assessment is not an independent defense result.",
    )


def validate_defense_brief(submission: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    brief = submission.get("defense_brief") if isinstance(submission.get("defense_brief"), dict) else {}
    sections = brief.get("sections") if isinstance(brief.get("sections"), dict) else {}
    missing = [name for name in spec.get("required_brief_sections", []) if not non_empty_text(sections.get(name))]
    duration = brief.get("duration_minutes")
    errors: list[dict[str, Any]] = []
    if missing:
        errors.append({"field": "defense_brief.sections", "missing": missing})
    if not isinstance(duration, (int, float)) or duration <= 0 or duration > spec.get(
        "max_defense_minutes", 10
    ):
        errors.append({"field": "defense_brief.duration_minutes", "observed": duration})
    return check(
        "defense_brief_fits_time_and_covers_decision_story",
        not errors,
        observed={"errors": errors, "duration_minutes": duration, "sections": list(sections)},
        expected="eight required sections in ten minutes or less",
        message="Defense time is reserved for decision reasoning, evidence and limitations.",
    )


def parse_stage_evidence(value: Any) -> tuple[str, str] | None:
    if not non_empty_text(value) or ":" not in str(value):
        return None
    stage, selector = str(value).split(":", 1)
    if stage not in STAGE_DEFINITIONS or not safe_relative_path(selector):
        return None
    return stage, selector


def validate_claims_and_challenges(
    submission: dict[str, Any], packages: dict[str, Path], spec: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    claims = submission.get("defense_claims") if isinstance(submission.get("defense_claims"), list) else []
    claim_errors: list[dict[str, Any]] = []
    claim_ids: set[str] = set()
    for index, claim in enumerate(claims):
        prefix = f"defense_claims[{index}]"
        if not isinstance(claim, dict):
            claim_errors.append({"field": prefix, "reason": "object required"})
            continue
        claim_id = claim.get("claim_id")
        if not non_empty_text(claim_id) or claim_id in claim_ids:
            claim_errors.append({"field": f"{prefix}.claim_id", "reason": "unique ID required"})
        claim_ids.add(str(claim_id))
        for field in ("statement", "claim_type", "evidence_path", "limitation"):
            if not non_empty_text(claim.get(field)):
                claim_errors.append({"field": f"{prefix}.{field}", "reason": "required"})
        parsed = parse_stage_evidence(claim.get("evidence_path"))
        if parsed is None:
            claim_errors.append({"field": f"{prefix}.evidence_path", "reason": "invalid"})
        else:
            stage, selector = parsed
            if not (packages[stage] / selector.split("#", 1)[0]).is_file():
                claim_errors.append({"field": f"{prefix}.evidence_path", "reason": "missing"})
        statement = str(claim.get("statement", "")).lower()
        if claim.get("claim_type") == "descriptive" and any(
            term in statement for term in (" causes ", "causal effect", "guarantees")
        ):
            claim_errors.append({"field": f"{prefix}.statement", "reason": "overbroad"})
    claim_check = check(
        "defense_claims_have_exact_evidence_and_bounded_language",
        bool(claims) and not claim_errors,
        observed={"errors": claim_errors, "claim_count": len(claims)},
        expected="unique claims with exact stage evidence, type and limitation",
        message="Presentation language cannot exceed the reviewed claim boundary.",
    )

    questions = (
        submission.get("challenge_questions")
        if isinstance(submission.get("challenge_questions"), list)
        else []
    )
    challenge_errors: list[dict[str, Any]] = []
    classes: set[str] = set()
    question_ids: set[str] = set()
    allowed_statuses = set(spec.get("challenge_policy", {}).get("allowed_answer_statuses", []))
    for index, question in enumerate(questions):
        prefix = f"challenge_questions[{index}]"
        if not isinstance(question, dict):
            challenge_errors.append({"field": prefix, "reason": "object required"})
            continue
        question_id = question.get("question_id")
        if not non_empty_text(question_id) or question_id in question_ids:
            challenge_errors.append({"field": f"{prefix}.question_id", "reason": "unique ID required"})
        question_ids.add(str(question_id))
        challenge_class = question.get("class")
        if challenge_class not in ALLOWED_CHALLENGE_CLASSES:
            challenge_errors.append({"field": f"{prefix}.class", "observed": challenge_class})
        else:
            classes.add(str(challenge_class))
        for field in ("question", "answer", "claim_boundary", "evidence_path", "next_check"):
            if not non_empty_text(question.get(field)):
                challenge_errors.append({"field": f"{prefix}.{field}", "reason": "required"})
        if question.get("answer_status") not in allowed_statuses:
            challenge_errors.append(
                {"field": f"{prefix}.answer_status", "observed": question.get("answer_status")}
            )
        parsed = parse_stage_evidence(question.get("evidence_path"))
        if parsed is None:
            challenge_errors.append({"field": f"{prefix}.evidence_path", "reason": "invalid"})
        else:
            stage, selector = parsed
            if not (packages[stage] / selector.split("#", 1)[0]).is_file():
                challenge_errors.append({"field": f"{prefix}.evidence_path", "reason": "missing"})
    minimum = spec.get("challenge_policy", {}).get("minimum_distinct_classes", 3)
    if len(classes) < minimum:
        challenge_errors.append(
            {"field": "challenge_questions.classes", "minimum": minimum, "observed": sorted(classes)}
        )
    challenge_check = check(
        "challenge_answers_cover_failure_classes_and_bound_uncertainty",
        not challenge_errors,
        observed={"errors": challenge_errors, "classes": sorted(classes)},
        expected="three or more challenge classes with evidence, boundary and next check",
        message="A defensible unknown names what is unknown and how to test it.",
    )
    return claim_check, challenge_check, claims


def validate_review_closure(package: Path, submission: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    report_path = package / "review_report.json"
    re_review_path = package / "re_review_report.json"
    if not report_path.is_file() or not re_review_path.is_file():
        errors.append({"field": "review_outputs", "reason": "missing"})
        report, re_review = {}, {}
    else:
        report, re_review = read_json(report_path), read_json(re_review_path)
    if report.get("status") != "review_ready" or report.get("valid") is not True:
        errors.append({"field": "review_report.status", "observed": report.get("status")})
    summary = re_review.get("summary") if isinstance(re_review.get("summary"), dict) else {}
    if re_review.get("valid") is not True or summary.get("open_findings") != []:
        errors.append({"field": "re_review_report.summary", "observed": summary})
    manifest_sha = sha256_file(package / "review_manifest.json") if (package / "review_manifest.json").is_file() else None
    if submission.get("reviewed_manifest_sha256") != manifest_sha:
        errors.append(
            {
                "field": "reviewed_manifest_sha256",
                "expected": manifest_sha,
                "observed": submission.get("reviewed_manifest_sha256"),
            }
        )
    return check(
        "peer_review_is_closed_for_exact_defense_input",
        not errors,
        observed={"errors": errors, "open_findings": summary.get("open_findings")},
        expected="review_ready package, zero open findings and exact reviewed manifest hash",
        message="Defense cannot silently move from the package approved in re-review.",
    )


def run_live_implementation_rerun(
    implementation_package: Path,
    baseline_package: Path,
    runner: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    if not runner.is_file():
        return {"valid": False, "reason": "implementation runner missing", "comparisons": []}
    required = [
        implementation_package / "implementation_spec.json",
        implementation_package / "implementation_manifest.json",
    ]
    if not all(path.is_file() for path in required):
        return {"valid": False, "reason": "implementation evidence missing", "comparisons": []}
    manifest = read_json(implementation_package / "implementation_manifest.json")
    with TemporaryDirectory() as directory:
        output = Path(directory) / "live-rerun"
        command = [
            sys.executable,
            str(runner),
            "--upstream-baseline-package",
            str(baseline_package),
            "--implementation-spec",
            str(implementation_package / "implementation_spec.json"),
            "--output-dir",
            str(output),
            "--fail-on-invalid",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "valid": False,
                "timed_out": True,
                "return_code": None,
                "comparisons": [],
            }
        comparisons = []
        for output_id, entry in sorted(manifest.get("outputs", {}).items()):
            relative = entry.get("path") if isinstance(entry, dict) else None
            rerun_path = output / str(relative)
            observed = sha256_file(rerun_path) if rerun_path.is_file() else None
            comparisons.append(
                {
                    "output_id": output_id,
                    "path": relative,
                    "expected_sha256": entry.get("sha256") if isinstance(entry, dict) else None,
                    "rerun_sha256": observed,
                    "match": observed == (entry.get("sha256") if isinstance(entry, dict) else None),
                }
            )
    try:
        process_payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        process_payload = {}
    return {
        "valid": completed.returncode == 0 and bool(comparisons) and all(
            row["match"] for row in comparisons
        ),
        "timed_out": False,
        "return_code": completed.returncode,
        "stderr_present": bool(completed.stderr.strip()),
        "process_summary": {
            key: process_payload.get(key)
            for key in (
                "project_id",
                "implementation_id",
                "status",
                "valid",
                "selected_method",
                "candidate_pass",
            )
        },
        "comparisons": comparisons,
        "check_mode": True,
        "source_manifest_sha256": sha256_file(
            implementation_package / "implementation_manifest.json"
        ),
    }


def validate_demo(
    submission: dict[str, Any], spec: dict[str, Any], live_report: dict[str, Any]
) -> dict[str, Any]:
    demo = submission.get("demo") if isinstance(submission.get("demo"), dict) else {}
    expected_command = spec.get("live_rerun", {}).get("verify_command")
    errors: list[dict[str, Any]] = []
    if demo.get("check_mode") is not True:
        errors.append({"field": "demo.check_mode", "expected": True})
    if demo.get("verify_command") != expected_command:
        errors.append({"field": "demo.verify_command", "expected": expected_command})
    if not isinstance(demo.get("steps"), list) or len(demo["steps"]) < 4:
        errors.append({"field": "demo.steps", "reason": "four or more steps required"})
    if demo.get("duration_minutes", 99) > spec.get("max_defense_minutes", 10):
        errors.append({"field": "demo.duration_minutes"})
    if live_report.get("valid") is not True:
        errors.append({"field": "live_rerun", "observed": live_report})
    return check(
        "live_demo_uses_check_mode_and_reproduces_reviewed_outputs",
        not errors,
        observed={
            "errors": errors,
            "return_code": live_report.get("return_code"),
            "matched_outputs": sum(row.get("match") is True for row in live_report.get("comparisons", [])),
        },
        expected="documented check mode plus byte-identical live implementation rerun",
        message="A screenshot cannot replace an executable check and observable rerun.",
    )


def scan_public_values(paths: list[Path], public_csv: Path | None = None) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in FORBIDDEN_PUBLIC_MARKERS:
            if marker in text:
                errors.append({"path": path.name, "marker": marker})
    if public_csv is not None and public_csv.is_file():
        _rows, fields = read_csv(public_csv)
        restricted = sorted(set(fields) & RESTRICTED_PUBLIC_COLUMNS)
        if restricted:
            errors.append({"path": public_csv.name, "restricted_columns": restricted})
    return errors


def validate_public_boundary(
    submission: dict[str, Any], packages: dict[str, Path], runner: Path
) -> dict[str, Any]:
    release = submission.get("public_release") if isinstance(submission.get("public_release"), dict) else {}
    errors: list[dict[str, Any]] = []
    if any(
        release.get(field) is not False
        for field in ("raw_sources_included", "pii_included", "secrets_included")
    ):
        errors.append({"field": "public_release", "observed": release})
    bad_raw = []
    for stage, definition in STAGE_DEFINITIONS.items():
        manifest_path = packages[stage] / definition["manifest"]
        if manifest_path.is_file() and read_json(manifest_path).get("raw_sources_copied") is True:
            bad_raw.append(stage)
    if bad_raw:
        errors.append({"field": "stage_manifests.raw_sources_copied", "stages": bad_raw})
    scan_paths = [runner, packages["data"] / "public_data_sample.csv"]
    errors.extend(
        scan_public_values(scan_paths, packages["data"] / "public_data_sample.csv")
    )
    return check(
        "public_package_excludes_raw_sensitive_and_secret_material",
        not errors,
        observed={"errors": errors, "sample_kind": release.get("sample_kind")},
        expected="aggregate or synthetic public sample with no raw source, PII or secrets",
        message="Portfolio publication cannot widen upstream data rights.",
    )


def build_rubric(checks: list[dict[str, Any]], stages_valid: bool) -> dict[str, Any]:
    by_id = {item["id"]: item["valid"] for item in checks}
    review_ready = by_id.get("peer_review_is_closed_for_exact_defense_input", False)
    defense_ready = all(
        by_id.get(check_id, False)
        for check_id in (
            "defense_brief_fits_time_and_covers_decision_story",
            "defense_claims_have_exact_evidence_and_bounded_language",
            "challenge_answers_cover_failure_classes_and_bound_uncertainty",
            "live_demo_uses_check_mode_and_reproduces_reviewed_outputs",
        )
    )
    scores = {
        "problem_framing": 3 if stages_valid else 0,
        "data_contract": 3 if stages_valid else 0,
        "method_and_baseline": 3 if stages_valid else 0,
        "verification": 4 if stages_valid else 0,
        "delivery_and_handoff": 4 if defense_ready else 0,
        "review_and_defense": 4 if review_ready and defense_ready else 0,
    }
    evidence = {
        "problem_framing": ["brief/capstone-brief.json#decision", "brief/risk-register.csv"],
        "data_contract": ["data/data-contract.json", "data/data-audit.json#checks"],
        "method_and_baseline": [
            "baseline/baseline-report.json",
            "verification/sensitivity-report.csv",
        ],
        "verification": [
            "verification/verification-report.json#summary",
            "verification/shadow-calculation.csv",
        ],
        "delivery_and_handoff": ["handoff/runbook.md", "manifest.json#outputs"],
        "review_and_defense": [
            "review/re-review-report.json#summary",
            "defense/live-rerun-report.json",
        ],
    }
    rationales = {
        "problem_framing": "Decision and scope are explicit; reference error cost is not production-calibrated.",
        "data_contract": "Grain, rights, privacy and defects are checked on an aggregate tiny sample.",
        "method_and_baseline": "The frozen gate retains baseline and reports threshold sensitivity.",
        "verification": "Clean-room, shadow, negative, sensitivity and claim checks all pass.",
        "delivery_and_handoff": "One package has a verify command, provenance, runbook and public boundary.",
        "review_and_defense": "Review is closed and defense includes rerun plus five challenge classes.",
    }
    names = dict(RUBRIC_DIMENSIONS)
    dimensions = [
        {
            "dimension_id": dimension_id,
            "name": names[dimension_id],
            "score": scores[dimension_id],
            "max_score": 4,
            "evidence_paths": evidence[dimension_id],
            "rationale": rationales[dimension_id],
        }
        for dimension_id, _name in RUBRIC_DIMENSIONS
    ]
    total = sum(item["score"] for item in dimensions)
    return {
        "version": PORTFOLIO_VERSION,
        "dimensions": dimensions,
        "summary": {"total_score": total, "max_score": 24},
    }


def rubric_outcome(rubric: dict[str, Any], blockers: list[str]) -> str:
    if blockers:
        return "revision_required"
    scores = {item["dimension_id"]: item["score"] for item in rubric["dimensions"]}
    total = rubric["summary"]["total_score"]
    distinction = min(scores.values()) >= 3 and total >= 22
    if distinction:
        return "passed_with_distinction"
    critical = ["data_contract", "method_and_baseline", "verification"]
    passed = (
        min(scores.values()) >= 2
        and all(scores[item] >= 3 for item in critical)
        and total >= 18
    )
    return "passed" if passed else "revision_required"


def audit_defense(
    *,
    packages: dict[str, Path],
    capstone_brief_path: Path,
    implementation_runner: Path,
    defense_spec_path: Path,
    defense_submission_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    before = {stage: directory_checksums(path) for stage, path in packages.items()}
    spec = read_json(defense_spec_path)
    submission = read_json(defense_submission_path)
    stage_checks: list[dict[str, Any]] = []
    manifests: dict[str, dict[str, Any]] = {}
    states: dict[str, dict[str, Any]] = {}
    for stage, package in packages.items():
        stage_check, manifest, state = validate_stage_package(stage, package)
        stage_checks.append(stage_check)
        manifests[stage] = manifest
        states[stage] = state
    chain_check = validate_stage_chain(packages, manifests, states)
    review_state = states.get("review", {})
    review_manifest_path = packages["review"] / "review_manifest.json"
    review_manifest_sha = sha256_file(review_manifest_path) if review_manifest_path.is_file() else ""
    spec_check = validate_defense_spec(
        spec, review_state, review_manifest_sha, implementation_runner
    )
    id_errors = []
    for field in ("project_id", "review_id", "defense_id", "reviewed_manifest_sha256"):
        if submission.get(field) != spec.get(field):
            id_errors.append(
                {"field": field, "expected": spec.get(field), "observed": submission.get(field)}
            )
    submission_check = check(
        "defense_submission_matches_predeclared_scope",
        not id_errors,
        observed={"errors": id_errors},
        expected="submission IDs and reviewed manifest match defense spec",
        message="Defense evidence cannot be moved between project or review versions.",
    )
    evaluator_check = validate_evaluator(submission)
    brief_check = validate_defense_brief(submission, spec)
    claim_check, challenge_check, claims = validate_claims_and_challenges(
        submission, packages, spec
    )
    review_check = validate_review_closure(packages["review"], submission)
    live_report = run_live_implementation_rerun(
        packages["implementation"],
        packages["baseline"],
        implementation_runner,
        spec.get("live_rerun", {}).get("timeout_seconds", 30),
    )
    demo_check = validate_demo(submission, spec, live_report)
    public_check = validate_public_boundary(submission, packages, implementation_runner)
    after = {stage: directory_checksums(path) for stage, path in packages.items()}
    mutated = [stage for stage in packages if before[stage] != after[stage]]
    boundary_check = check(
        "defense_does_not_mutate_reviewed_stage_packages",
        not mutated,
        observed={"mutated_stages": mutated},
        expected="all six source stage directories remain byte-identical",
        message="Defense adds a final package layer without rewriting project history.",
    )
    brief_source_check = check(
        "capstone_brief_source_is_present_and_matches_project",
        capstone_brief_path.is_file()
        and read_json(capstone_brief_path).get("project_id") == review_state.get("project_id"),
        observed={"path": capstone_brief_path.name, "exists": capstone_brief_path.is_file()},
        expected="exact source brief for the reviewed project",
        message="The final package must include the approved brief, not reconstruct it from state.",
    )
    checks = [
        *stage_checks,
        chain_check,
        spec_check,
        submission_check,
        evaluator_check,
        brief_source_check,
        brief_check,
        claim_check,
        challenge_check,
        review_check,
        demo_check,
        public_check,
        boundary_check,
    ]
    stages_valid = all(item["valid"] for item in stage_checks) and chain_check["valid"]
    rubric = build_rubric(checks, stages_valid)
    blockers = [item["id"] for item in checks if not item["valid"]]
    outcome = rubric_outcome(rubric, blockers)
    rubric["status"] = outcome
    rubric["summary"].update(
        {
            "blocking_errors": blockers,
            "all_dimensions_at_least_two": all(
                item["score"] >= 2 for item in rubric["dimensions"]
            ),
            "critical_dimensions_at_least_three": all(
                item["score"] >= 3
                for item in rubric["dimensions"]
                if item["dimension_id"]
                in {"data_contract", "method_and_baseline", "verification"}
            ),
            "distinction_threshold_met": all(
                item["score"] >= 3 for item in rubric["dimensions"]
            )
            and rubric["summary"]["total_score"] >= 22,
        }
    )
    report = {
        "version": PORTFOLIO_VERSION,
        "project_id": spec.get("project_id"),
        "review_id": spec.get("review_id"),
        "defense_id": spec.get("defense_id"),
        "status": outcome,
        "valid": outcome in {"passed", "passed_with_distinction"},
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "blocking_errors": blockers,
            "gate_sequence": ["review_ready", "defense_ready", outcome],
            "defense_duration_minutes": submission.get("defense_brief", {}).get(
                "duration_minutes"
            ),
            "challenge_classes": sorted(
                {
                    item.get("class")
                    for item in submission.get("challenge_questions", [])
                    if isinstance(item, dict)
                }
            ),
            "defense_claims": len(claims),
            "live_rerun_match": live_report.get("valid") is True,
            "rubric_score": rubric["summary"]["total_score"],
            "rubric_max": 24,
            "warnings": [
                "reference_profile_is_not_portfolio_evidence",
                "tiny_aggregate_sample_is_not_production_evidence",
                "candidate_did_not_clear_practical_threshold",
                "descriptive_ranking_is_not_causal_effect",
            ],
        },
    }
    return report, {
        "spec": spec,
        "submission": submission,
        "manifests": manifests,
        "states": states,
        "rubric": rubric,
        "live_report": live_report,
        "claims": claims,
    }


def copy_with_provenance(
    source: Path,
    destination: Path,
    *,
    stage: str,
    records: list[dict[str, Any]],
    package_root: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    records.append(
        {
            "stage": stage,
            "source_path": source.name,
            "source_sha256": sha256_file(source),
            "package_path": destination.relative_to(package_root).as_posix(),
            "package_sha256": sha256_file(destination),
        }
    )


def map_evidence_to_package(value: str) -> str:
    parsed = parse_stage_evidence(value)
    if parsed is None:
        return value
    stage, selector = parsed
    relative, *fragment = selector.split("#", 1)
    mapped = CANONICAL_STAGE_FILES.get(stage, {}).get(relative)
    if mapped is None:
        return value
    return f"{mapped}#{fragment[0]}" if fragment else mapped


def render_defense_brief(submission: dict[str, Any]) -> str:
    brief = submission["defense_brief"]
    sections = brief["sections"]
    lines = [
        "# Defense Brief",
        "",
        f"Planned duration: {brief['duration_minutes']} minutes.",
        "",
    ]
    for name in REQUIRED_BRIEF_SECTIONS:
        lines.extend([f"## {name.replace('_', ' ').title()}", "", sections[name], ""])
    return "\n".join(lines)


def render_demo_script(submission: dict[str, Any]) -> str:
    demo = submission["demo"]
    lines = [
        "# Live Demo Script",
        "",
        f"Duration: {demo['duration_minutes']} minutes.",
        "",
        "## Verify Command",
        "",
        "```bash",
        demo["verify_command"],
        "```",
        "",
        "## Steps",
        "",
    ]
    lines.extend(f"{index}. {step}" for index, step in enumerate(demo["steps"], start=1))
    return "\n".join(lines) + "\n"


def render_decision_report(submission: dict[str, Any], outcome: str, score: int) -> str:
    sections = submission["defense_brief"]["sections"]
    return "\n".join(
        [
            "# Decision Report",
            "",
            f"Final capstone status: `{outcome}`.",
            f"Rubric score: `{score}/24`.",
            "",
            "## Recommendation",
            "",
            sections["recommendation"],
            "",
            "## Evidence Boundary",
            "",
            sections["limitations"],
            "",
            "## Next Step",
            "",
            sections["next_step"],
            "",
        ]
    )


def render_handoff_readme(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Capstone Portfolio Package",
            "",
            f"Status: `{report['status']}`.",
            f"Project: `{report['project_id']}`.",
            "",
            "Start with `defense/decision-report.md`, then inspect `rubric-result.json` and "
            "run the verify command in `handoff/runbook.md`.",
            "",
            "The package contains only aggregate reference data. It is not production, "
            "causal, legal, security or SLA certification.",
            "",
        ]
    )


def render_runbook(spec: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Runbook",
            "",
            "## Verify Package",
            "",
            "```bash",
            spec["live_rerun"]["verify_command"],
            "```",
            "",
            "A non-zero exit code means the package is stale, incomplete, restricted, or "
            "inconsistent with its reviewed provenance.",
            "",
            "## Escalation",
            "",
            "Return to the earliest affected stage, rebuild downstream packages, repeat "
            "independent verification and request re-review before another defense.",
            "",
        ]
    )


def render_limitations(submission: dict[str, Any]) -> str:
    limitations = [claim["limitation"] for claim in submission["defense_claims"]]
    return "\n".join(
        [
            "# Limitations",
            "",
            submission["defense_brief"]["sections"]["limitations"],
            "",
            *[f"- {item}" for item in limitations],
            "",
        ]
    )


def render_assistance_disclosure(submission: dict[str, Any]) -> str:
    disclosure = submission["assistance_disclosure"]
    evaluator = submission["evaluator"]
    return "\n".join(
        [
            "# Assistance Disclosure",
            "",
            f"AI assistance used: `{str(disclosure['ai_assistance_used']).lower()}`.",
            "The author remains accountable for every claim, source, calculation and test.",
            f"Evaluator disclosure: {evaluator['assistance_disclosure']}",
            "",
        ]
    )


def build_final_state(
    review_state: dict[str, Any], report: dict[str, Any], package: Path
) -> dict[str, Any]:
    state = json.loads(json.dumps(review_state))
    state.update(
        {
            "defense_id": report.get("defense_id"),
            "current_stage": "defense",
            "stage_status": report["status"],
            "open_blockers": report["summary"]["blocking_errors"],
            "warnings": report["summary"]["warnings"],
            "updated_at": "2026-01-14T12:00:00Z",
        }
    )
    state["artifact_inventory"] = sorted(
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file()
    )
    state["evidence_links"] = [
        *state.get("evidence_links", []),
        {"stage": "defense", "path": "defense/defense-audit.json"},
        {"stage": "defense", "path": "defense/live-rerun-report.json"},
        {"stage": "defense", "path": "rubric-result.json"},
        {"stage": "defense", "path": "defense/decision-report.md"},
    ]
    state["output_checksums"] = {
        path.relative_to(package).as_posix(): sha256_file(path)
        for path in sorted(package.rglob("*"))
        if path.is_file() and path.name not in {"capstone-state.json", "manifest.json"}
    }
    return state


def build_portfolio_package(
    *,
    packages: dict[str, str | Path],
    capstone_brief_path: str | Path,
    implementation_runner: str | Path,
    defense_spec_path: str | Path,
    defense_submission_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    package_paths = {stage: Path(path) for stage, path in packages.items()}
    brief_source = Path(capstone_brief_path)
    runner = Path(implementation_runner)
    spec_path = Path(defense_spec_path)
    submission_path = Path(defense_submission_path)
    report, result = audit_defense(
        packages=package_paths,
        capstone_brief_path=brief_source,
        implementation_runner=runner,
        defense_spec_path=spec_path,
        defense_submission_path=submission_path,
    )
    output = Path(output_dir)
    package = output / PACKAGE_NAME
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True, exist_ok=True)
    provenance: list[dict[str, Any]] = []
    if brief_source.is_file():
        copy_with_provenance(
            brief_source,
            package / "brief" / "capstone-brief.json",
            stage="brief_source",
            records=provenance,
            package_root=package,
        )
    for stage, mapping in CANONICAL_STAGE_FILES.items():
        for source_name, destination_name in mapping.items():
            source = package_paths[stage] / source_name
            if source.is_file():
                copy_with_provenance(
                    source,
                    package / destination_name,
                    stage=stage,
                    records=provenance,
                    package_root=package,
                )
    fixture_root = package_paths["verification"] / "failure-fixtures"
    if fixture_root.is_dir():
        for source in sorted(fixture_root.glob("*.json")):
            copy_with_provenance(
                source,
                package / "verification" / "failure-fixtures" / source.name,
                stage="verification",
                records=provenance,
                package_root=package,
            )
    if runner.is_file():
        copy_with_provenance(
            runner,
            package / "implementation" / "src" / "implementation-runner.py",
            stage="implementation_source",
            records=provenance,
            package_root=package,
        )

    submission = result["submission"]
    write_json(package / "defense" / "defense-spec.json", result["spec"])
    write_text(package / "defense" / "defense-brief.md", render_defense_brief(submission))
    write_text(package / "defense" / "demo-script.md", render_demo_script(submission))
    write_json(
        package / "defense" / "challenge-questions.json",
        {"questions": submission.get("challenge_questions", [])},
    )
    write_text(
        package / "defense" / "decision-report.md",
        render_decision_report(
            submission, report["status"], result["rubric"]["summary"]["total_score"]
        ),
    )
    write_json(package / "defense" / "live-rerun-report.json", result["live_report"])
    write_json(package / "defense" / "defense-audit.json", report)
    write_text(package / "handoff" / "README.md", render_handoff_readme(report))
    write_text(package / "handoff" / "runbook.md", render_runbook(result["spec"]))
    write_text(package / "handoff" / "limitations.md", render_limitations(submission))
    write_text(
        package / "handoff" / "assistance-disclosure.md",
        render_assistance_disclosure(submission),
    )
    write_json(
        package / "handoff" / "stage-provenance.json",
        {"hash_algorithm": "sha256", "files": provenance},
    )
    claim_rows = [
        {
            "claim_id": claim["claim_id"],
            "statement": claim["statement"],
            "claim_type": claim["claim_type"],
            "package_evidence_path": map_evidence_to_package(claim["evidence_path"]),
            "limitation": claim["limitation"],
        }
        for claim in result["claims"]
    ]
    write_csv(
        package / "handoff" / "claim-evidence-index.csv",
        claim_rows,
        ["claim_id", "statement", "claim_type", "package_evidence_path", "limitation"],
    )
    write_json(package / "rubric-result.json", result["rubric"])
    final_state = build_final_state(result["states"].get("review", {}), report, package)
    write_json(package / "capstone-state.json", final_state)

    expected_without_manifest = [
        name for name in REQUIRED_PACKAGE_FILES if name != "manifest.json"
    ]
    missing_tree = [name for name in expected_without_manifest if not (package / name).is_file()]
    if missing_tree and report["valid"]:
        raise RuntimeError(f"builder omitted required files: {', '.join(missing_tree)}")
    outputs = {}
    for index, path in enumerate(
        sorted(item for item in package.rglob("*") if item.is_file()), start=1
    ):
        relative = path.relative_to(package).as_posix()
        outputs[f"file_{index:03d}"] = {
            "path": relative,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    manifest = {
        "version": PORTFOLIO_VERSION,
        "project_id": report.get("project_id"),
        "review_id": report.get("review_id"),
        "defense_id": report.get("defense_id"),
        "status": report["status"],
        "valid": report["valid"],
        "hash_algorithm": "sha256",
        "renderer_used": "capstone_portfolio_builder",
        "raw_sources_copied": False,
        "public_sample_kind": submission.get("public_release", {}).get("sample_kind"),
        "live_rerun_pass": result["live_report"].get("valid") is True,
        "review_closure_preserved": next(
            item["valid"]
            for item in report["checks"]
            if item["id"] == "peer_review_is_closed_for_exact_defense_input"
        ),
        "inputs": {
            **{
                f"{stage}_manifest": {
                    "path": f"{stage}/{definition['manifest']}",
                    "sha256": sha256_file(package_paths[stage] / definition["manifest"])
                    if (package_paths[stage] / definition["manifest"]).is_file()
                    else None,
                }
                for stage, definition in STAGE_DEFINITIONS.items()
            },
            "capstone_brief": {"path": brief_source.name, "sha256": sha256_file(brief_source)},
            "implementation_runner": {"path": runner.name, "sha256": sha256_file(runner)},
            "defense_spec": {"path": spec_path.name, "sha256": sha256_file(spec_path)},
            "defense_submission": {
                "path": submission_path.name,
                "sha256": sha256_file(submission_path),
            },
            "lock_file": {
                "path": "uv.lock",
                "sha256": sha256_file(REPO_ROOT / "uv.lock"),
            },
        },
        "outputs": outputs,
    }
    manifest_path = write_json(package / "manifest.json", manifest)
    validation_errors = validate_portfolio_package(package)
    return {
        "report": report,
        "rubric": result["rubric"],
        "state": final_state,
        "manifest": manifest,
        "package_dir": package,
        "manifest_path": manifest_path,
        "validation_errors": validation_errors,
        "valid": report["valid"] and not validation_errors,
    }


def validate_portfolio_package(package: str | Path) -> list[dict[str, Any]]:
    root = Path(package)
    required_root = [
        root / "manifest.json",
        root / "capstone-state.json",
        root / "rubric-result.json",
        root / "defense" / "defense-audit.json",
        root / "handoff" / "stage-provenance.json",
    ]
    missing_root = [path.relative_to(root).as_posix() for path in required_root if not path.is_file()]
    if missing_root:
        return [{"field": "required_root", "missing": missing_root}]
    manifest = read_json(root / "manifest.json")
    errors = manifest_output_errors(root, manifest)
    tracked = {
        str(entry.get("path"))
        for entry in manifest.get("outputs", {}).values()
        if isinstance(entry, dict)
    }
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if tracked != actual:
        errors.append(
            {
                "field": "outputs.coverage",
                "untracked": sorted(actual - tracked),
                "missing": sorted(tracked - actual),
            }
        )
    missing_required = [name for name in REQUIRED_PACKAGE_FILES if not (root / name).is_file()]
    if missing_required:
        errors.append({"field": "required_package_files", "missing": missing_required})
    state = read_json(root / "capstone-state.json")
    rubric = read_json(root / "rubric-result.json")
    audit = read_json(root / "defense" / "defense-audit.json")
    statuses = {manifest.get("status"), state.get("stage_status"), rubric.get("status"), audit.get("status")}
    if len(statuses) != 1:
        errors.append({"field": "status_consistency", "observed": sorted(str(item) for item in statuses)})
    provenance = read_json(root / "handoff" / "stage-provenance.json")
    for entry in provenance.get("files", []):
        target = root / str(entry.get("package_path"))
        if not target.is_file() or sha256_file(target) != entry.get("source_sha256"):
            errors.append(
                {
                    "field": "stage_provenance",
                    "path": entry.get("package_path"),
                    "expected": entry.get("source_sha256"),
                    "observed": sha256_file(target) if target.is_file() else None,
                }
            )
    text_paths = [path for path in root.rglob("*") if path.is_file()]
    errors.extend(
        {"field": "public_scan", **item}
        for item in scan_public_values(
            text_paths, root / "data" / "public-data-sample" / "data.csv"
        )
    )
    if manifest.get("raw_sources_copied") is not False:
        errors.append({"field": "raw_sources_copied", "observed": manifest.get("raw_sources_copied")})
    return errors


def load_brief_builder():
    path = PHASE_ROOT / "01-problem-selection" / "outputs" / "capstone_brief_validator.py"
    spec = importlib.util.spec_from_file_location("capstone_brief_validator_for_defense", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def copy_reference_stage(stage: str, target: Path) -> Path:
    definition = STAGE_DEFINITIONS[stage]
    source = PHASE_ROOT / {
        "brief": "01-problem-selection",
        "data": "02-data-contract",
        "baseline": "03-baseline",
        "implementation": "04-implementation",
        "verification": "05-verification",
        "review": "06-peer-review",
    }[stage] / "outputs"
    manifest = read_json(source / definition["manifest"])
    target.mkdir(parents=True, exist_ok=True)
    for entry in manifest.get("outputs", {}).values():
        relative = entry.get("path") if isinstance(entry, dict) else None
        if safe_relative_path(relative):
            destination = target / str(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / str(relative), destination)
    shutil.copy2(source / definition["manifest"], target / definition["manifest"])
    return target


def write_sample_inputs(root: str | Path) -> dict[str, Any]:
    target = Path(root)
    target.mkdir(parents=True, exist_ok=True)
    packages = {
        stage: copy_reference_stage(stage, target / f"{stage}-package")
        for stage in STAGE_DEFINITIONS
    }
    brief_builder = load_brief_builder()
    capstone_brief_path = brief_builder.write_example(target / "brief-source")
    review_state = read_json(packages["review"] / "capstone_state.json")
    defense_spec_path = write_json(
        target / "defense_spec.json",
        default_defense_spec(review_state, IMPLEMENTATION_RUNNER),
    )
    review_manifest_sha = sha256_file(packages["review"] / "review_manifest.json")
    defense_submission_path = write_json(
        target / "defense_submission.json",
        reference_defense_submission(review_manifest_sha),
    )
    return {
        "packages": packages,
        "capstone_brief_path": capstone_brief_path,
        "implementation_runner": IMPLEMENTATION_RUNNER,
        "defense_spec_path": defense_spec_path,
        "defense_submission_path": defense_submission_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and verify a stage-gated capstone portfolio defense package."
    )
    parser.add_argument("--brief-package", type=Path)
    parser.add_argument("--data-package", type=Path)
    parser.add_argument("--baseline-package", type=Path)
    parser.add_argument("--implementation-package", type=Path)
    parser.add_argument("--verification-package", type=Path)
    parser.add_argument("--review-package", type=Path)
    parser.add_argument("--capstone-brief", type=Path)
    parser.add_argument("--implementation-runner", type=Path)
    parser.add_argument("--defense-spec", type=Path)
    parser.add_argument("--defense-submission", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--write-example", type=Path)
    parser.add_argument("--verify-package", type=Path)
    parser.add_argument("--fail-on-invalid", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.verify_package:
        errors = validate_portfolio_package(args.verify_package)
        payload = {
            "status": "passed" if not errors else "revision_required",
            "valid": not errors,
            "package": str(args.verify_package),
            "errors": errors,
        }
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        if errors:
            raise SystemExit(1)
        return
    if args.output_dir is None:
        raise SystemExit("--output-dir is required when building a package")
    if args.write_example:
        inputs = write_sample_inputs(args.write_example)
    else:
        values = {
            "brief": args.brief_package,
            "data": args.data_package,
            "baseline": args.baseline_package,
            "implementation": args.implementation_package,
            "verification": args.verification_package,
            "review": args.review_package,
        }
        required = {
            **{f"--{stage}-package": value for stage, value in values.items()},
            "--capstone-brief": args.capstone_brief,
            "--implementation-runner": args.implementation_runner,
            "--defense-spec": args.defense_spec,
            "--defense-submission": args.defense_submission,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise SystemExit(f"missing required arguments: {', '.join(missing)}")
        inputs = {
            "packages": values,
            "capstone_brief_path": args.capstone_brief,
            "implementation_runner": args.implementation_runner,
            "defense_spec_path": args.defense_spec,
            "defense_submission_path": args.defense_submission,
        }
    result = build_portfolio_package(
        packages=inputs["packages"],
        capstone_brief_path=inputs["capstone_brief_path"],
        implementation_runner=inputs["implementation_runner"],
        defense_spec_path=inputs["defense_spec_path"],
        defense_submission_path=inputs["defense_submission_path"],
        output_dir=args.output_dir,
    )
    report = result["report"]
    print(
        json.dumps(
            {
                "status": report["status"],
                "valid": result["valid"],
                "defense_id": report["defense_id"],
                "rubric_score": report["summary"]["rubric_score"],
                "live_rerun_match": report["summary"]["live_rerun_match"],
                "challenge_classes": report["summary"]["challenge_classes"],
                "blocking_errors": report["summary"]["blocking_errors"],
                "package_dir": str(result["package_dir"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if args.fail_on_invalid and not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
