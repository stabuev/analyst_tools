from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BUILDER_VERSION = "1.0.0"
ALLOWED_QUALITY_STATUSES = {"pass", "warn", "block"}
FORBIDDEN_OVERCLAIM_PATTERNS = [
    r"\bcaused\b",
    r"\bcauses\b",
    r"\bproves\b",
    r"\bproven\b",
    r"\bbecause of the release\b",
    r"\bdue to the release\b",
    r"\bdriven by the release\b",
    r"\bcausal effect\b",
    r"\bcausal impact\b",
    r"\bcausal lift\b",
    r"\bcausally\b",
    r"\btriggered by\b",
    r"вызвал",
    r"вызвала",
    r"вызвало",
    r"доказал",
    r"доказала",
    r"доказано",
    r"причинный эффект",
    r"причинное влияние",
    r"из-за релиза",
    r"релиз привел",
]
REQUIRED_SPEC_FIELDS = {
    "memo_id",
    "title",
    "audience",
    "decision_owner",
    "primary_question",
    "allowed_decisions",
    "recommended_decision",
    "decision_options",
    "recommendation",
    "claim_boundary",
    "claims",
    "limitations",
    "next_steps",
}
REQUIRED_CLAIM_FIELDS = {
    "claim_id",
    "statement",
    "claim_type",
    "evidence_ids",
    "supports_decision",
    "limitation",
}
REQUIRED_EVIDENCE_FIELDS = {
    "evidence_id",
    "artifact_path",
    "metric_id",
    "finding",
    "evidence_type",
    "quality_status",
    "claim_scope",
    "limitation",
    "freshness",
}
REQUIRED_GATE_FIELDS = {"gate_id", "gate_name", "status", "evidence_id", "message"}
MEMO_REQUIRED_SECTIONS = [
    "## Question",
    "## Decision Options",
    "## Recommendation",
    "## Evidence",
    "## Limitations",
    "## Next Step",
]


@dataclass(frozen=True)
class MemoBuildResult:
    output_dir: Path
    memo_path: Path
    matrix_path: Path
    audit_path: Path
    manifest_path: Path
    audit: dict[str, Any]
    matrix: list[dict[str, Any]]


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(
    check_id: str,
    valid: bool,
    *,
    severity: str = "block",
    observed: Any = None,
    expected: Any = None,
    message: str = "",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": bool(valid),
        "severity": severity,
        "observed": observed,
        "expected": expected,
        "message": message,
    }


def text_has_forbidden_overclaim(text: str) -> bool:
    lowered = f" {text.lower()} "
    return any(re.search(pattern, lowered) for pattern in FORBIDDEN_OVERCLAIM_PATTERNS)


def sample_spec() -> dict[str, Any]:
    return {
        "memo_id": "trial-onboarding-risk-memo",
        "title": "Decision memo: onboarding rollout risk",
        "audience": "Growth weekly decision review",
        "decision_owner": "Head of Growth",
        "decision_due": "2026-05-22",
        "primary_question": (
            "Should the team continue the automatic onboarding rollout while support "
            "and cancellation guardrails are above the agreed threshold?"
        ),
        "allowed_decisions": [
            "continue_rollout",
            "pause_rollout",
            "rollback",
            "run_experiment",
        ],
        "recommended_decision": "pause_rollout",
        "recommendation": (
            "Pause automatic rollout for one week, inspect support and cancellation "
            "reasons, then choose rollback or experiment with a clean guardrail plan."
        ),
        "decision_options": [
            {
                "option_id": "continue_rollout",
                "label": "Continue automatic rollout",
                "status": "rejected",
                "reason": "Support and cancellation guardrails are above threshold.",
            },
            {
                "option_id": "pause_rollout",
                "label": "Pause rollout and investigate",
                "status": "recommended",
                "reason": "Risk is visible, but the current evidence is observational.",
            },
            {
                "option_id": "rollback",
                "label": "Rollback immediately",
                "status": "not_enough_evidence",
                "reason": "The memo has risk evidence but no causal design.",
            },
            {
                "option_id": "run_experiment",
                "label": "Run a holdout experiment",
                "status": "next_after_cleanup",
                "reason": "Useful after checking instrumentation and support reasons.",
            },
        ],
        "claim_boundary": {
            "causal_claims_allowed": False,
            "scope": "observational analytics with quality gates",
            "safe_wording": "associated with, observed in, consistent with",
        },
        "claims": [
            {
                "claim_id": "guardrails-above-threshold",
                "statement": (
                    "Support ticket rate and subscription cancellation rate are above "
                    "the pre-agreed guardrail thresholds in the current observation slice."
                ),
                "claim_type": "observation",
                "evidence_ids": ["support-ticket-rate", "cancel-rate"],
                "supports_decision": True,
                "limitation": "Guardrail breaches indicate decision risk, not a mechanism.",
            },
            {
                "claim_id": "quality-gates-usable",
                "statement": (
                    "Freshness and duplicate checks passed, while support reason coverage "
                    "is incomplete and must be disclosed."
                ),
                "claim_type": "quality",
                "evidence_ids": ["freshness-check", "support-reason-coverage"],
                "supports_decision": True,
                "limitation": "A warning is acceptable for a pause decision, not for a final root cause.",
            },
            {
                "claim_id": "calendar-context-only",
                "statement": (
                    "The Android release calendar overlaps the metric movement and should "
                    "guide investigation priorities."
                ),
                "claim_type": "context",
                "evidence_ids": ["release-calendar"],
                "supports_decision": False,
                "limitation": "Calendar overlap is context and does not establish attribution.",
            },
        ],
        "limitations": [
            {
                "limitation_id": "observational-design",
                "text": "The memo uses observational monitoring data, not an experiment.",
                "severity": "high",
            },
            {
                "limitation_id": "partial-support-taxonomy",
                "text": "Support reason coverage is below target, so root-cause labels are provisional.",
                "severity": "medium",
            },
        ],
        "next_steps": [
            {
                "step_id": "support-and-cancel-reason-review",
                "owner": "Support analytics",
                "due": "2026-05-24",
                "action": (
                    "Review top support reasons and cancellation comments for Android users "
                    "in the affected release window."
                ),
            },
            {
                "step_id": "holdout-plan",
                "owner": "Growth PM",
                "due": "2026-05-27",
                "action": "Prepare rollback or holdout experiment plan after the reason review.",
            },
        ],
    }


def sample_evidence_rows() -> list[dict[str, str]]:
    return [
        {
            "evidence_id": "support-ticket-rate",
            "artifact_path": "metrics/guardrails.csv",
            "metric_id": "support_ticket_rate_7d",
            "finding": "1.8% current versus 1.0% threshold",
            "evidence_type": "metric",
            "quality_status": "pass",
            "claim_scope": "observational",
            "limitation": "Threshold breach does not identify the product mechanism.",
            "freshness": "2026-05-21",
        },
        {
            "evidence_id": "cancel-rate",
            "artifact_path": "metrics/guardrails.csv",
            "metric_id": "subscription_cancel_rate_14d",
            "finding": "3.1% current versus 2.4% threshold",
            "evidence_type": "metric",
            "quality_status": "pass",
            "claim_scope": "observational",
            "limitation": "Cancellation movement may include mix and billing-cycle effects.",
            "freshness": "2026-05-21",
        },
        {
            "evidence_id": "freshness-check",
            "artifact_path": "audits/event-quality.json",
            "metric_id": "__data_quality__",
            "finding": "Last complete event date is within SLA.",
            "evidence_type": "quality_gate",
            "quality_status": "pass",
            "claim_scope": "quality",
            "limitation": "Fresh data can still be observational.",
            "freshness": "2026-05-21",
        },
        {
            "evidence_id": "support-reason-coverage",
            "artifact_path": "audits/event-quality.json",
            "metric_id": "support_reason_coverage",
            "finding": "74% support tickets have a normalized reason; target is 90%.",
            "evidence_type": "quality_gate",
            "quality_status": "warn",
            "claim_scope": "quality",
            "limitation": "Reason taxonomy is not complete enough for final attribution.",
            "freshness": "2026-05-21",
        },
        {
            "evidence_id": "release-calendar",
            "artifact_path": "context/release-calendar.md",
            "metric_id": "__context__",
            "finding": "Android release R002 overlaps the first support-ticket increase.",
            "evidence_type": "context",
            "quality_status": "pass",
            "claim_scope": "context",
            "limitation": "Calendar overlap is not causal evidence.",
            "freshness": "2026-05-21",
        },
    ]


def sample_quality_gate_rows() -> list[dict[str, str]]:
    return [
        {
            "gate_id": "freshness",
            "gate_name": "Freshness SLA",
            "status": "pass",
            "evidence_id": "freshness-check",
            "message": "Observation slice is fresh enough for the decision review.",
        },
        {
            "gate_id": "deduplication",
            "gate_name": "Duplicate event rate",
            "status": "pass",
            "evidence_id": "freshness-check",
            "message": "Duplicate event rate is below the warning threshold.",
        },
        {
            "gate_id": "support-reason-coverage",
            "gate_name": "Support reason coverage",
            "status": "warn",
            "evidence_id": "support-reason-coverage",
            "message": "Coverage warning must be disclosed in limitations.",
        },
    ]


def write_sample_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    spec_path = root_path / "memo_spec.json"
    evidence_path = root_path / "evidence.csv"
    gates_path = root_path / "quality_gates.csv"
    write_json(spec_path, sample_spec())
    write_csv(evidence_path, sample_evidence_rows(), sorted(REQUIRED_EVIDENCE_FIELDS))
    write_csv(gates_path, sample_quality_gate_rows(), sorted(REQUIRED_GATE_FIELDS))
    return {
        "spec_path": spec_path,
        "evidence_path": evidence_path,
        "quality_gates_path": gates_path,
    }


def evidence_by_id(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row.get("evidence_id", ""): row for row in rows if row.get("evidence_id")}


def build_claim_evidence_matrix(
    spec: dict[str, Any], evidence_rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    by_id = evidence_by_id(evidence_rows)
    matrix: list[dict[str, Any]] = []
    for claim in spec.get("claims", []):
        evidence_ids = claim.get("evidence_ids") or [""]
        for evidence_id in evidence_ids:
            evidence = by_id.get(str(evidence_id), {})
            quality_status = evidence.get("quality_status", "missing")
            if not evidence_id:
                decision_impact = "uncited_claim"
            elif not evidence:
                decision_impact = "unresolved_evidence"
            elif quality_status == "block":
                decision_impact = "blocks_decision"
            elif quality_status == "warn":
                decision_impact = "usable_with_disclosure"
            else:
                decision_impact = "usable"
            matrix.append(
                {
                    "claim_id": claim.get("claim_id", ""),
                    "claim": claim.get("statement", ""),
                    "claim_type": claim.get("claim_type", ""),
                    "supports_decision": str(claim.get("supports_decision", False)).lower(),
                    "evidence_id": evidence_id,
                    "artifact_path": evidence.get("artifact_path", ""),
                    "metric_id": evidence.get("metric_id", ""),
                    "finding": evidence.get("finding", ""),
                    "quality_status": quality_status,
                    "claim_scope": evidence.get("claim_scope", ""),
                    "claim_limitation": claim.get("limitation", ""),
                    "evidence_limitation": evidence.get("limitation", ""),
                    "decision_impact": decision_impact,
                }
            )
    return matrix


def validate_decision_memo(
    spec: dict[str, Any],
    evidence_rows: list[dict[str, str]],
    gate_rows: list[dict[str, str]],
    matrix: list[dict[str, Any]],
    memo_text: str,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    spec_fields = set(spec)
    missing_spec_fields = sorted(REQUIRED_SPEC_FIELDS - spec_fields)
    checks.append(
        check(
            "spec_has_required_fields",
            not missing_spec_fields,
            observed=missing_spec_fields,
            expected=[],
            message="Memo spec must contain all fields needed by a decision reader.",
        )
    )

    claim_missing: list[str] = []
    for claim in spec.get("claims", []):
        missing = REQUIRED_CLAIM_FIELDS - set(claim)
        if missing:
            claim_missing.append(f"{claim.get('claim_id', '<missing-id>')}:{','.join(sorted(missing))}")
    checks.append(
        check(
            "claims_have_required_fields",
            not claim_missing,
            observed=claim_missing,
            expected=[],
            message="Each claim needs id, statement, type, evidence, decision flag and limitation.",
        )
    )

    evidence_missing = [
        row.get("evidence_id", f"row-{position}")
        for position, row in enumerate(evidence_rows, start=1)
        if REQUIRED_EVIDENCE_FIELDS - set(row)
    ]
    checks.append(
        check(
            "evidence_has_required_fields",
            not evidence_missing,
            observed=evidence_missing,
            expected=[],
            message="Evidence rows need artifact, metric, finding, quality and scope fields.",
        )
    )

    gate_missing = [
        row.get("gate_id", f"row-{position}")
        for position, row in enumerate(gate_rows, start=1)
        if REQUIRED_GATE_FIELDS - set(row)
    ]
    checks.append(
        check(
            "quality_gates_have_required_fields",
            not gate_missing,
            observed=gate_missing,
            expected=[],
            message="Quality gate rows must be machine-readable.",
        )
    )

    allowed_decisions = spec.get("allowed_decisions", [])
    recommended_decision = spec.get("recommended_decision")
    checks.append(
        check(
            "decision_is_allowed",
            isinstance(allowed_decisions, list) and recommended_decision in allowed_decisions,
            observed=recommended_decision,
            expected=allowed_decisions,
            message="Recommendation must be one of the pre-declared decision options.",
        )
    )

    recommended_options = [
        option.get("option_id")
        for option in spec.get("decision_options", [])
        if option.get("status") == "recommended"
    ]
    checks.append(
        check(
            "recommended_option_is_marked",
            recommended_options == [recommended_decision],
            observed=recommended_options,
            expected=[recommended_decision],
            message="Exactly one decision option should be marked as recommended.",
        )
    )

    uncited_claims = [
        claim.get("claim_id", "<missing-id>")
        for claim in spec.get("claims", [])
        if not claim.get("evidence_ids")
    ]
    checks.append(
        check(
            "claims_have_evidence",
            not uncited_claims,
            observed=uncited_claims,
            expected=[],
            message="Claims without evidence do not belong in a decision memo.",
        )
    )

    by_id = evidence_by_id(evidence_rows)
    unresolved = sorted(
        {
            str(evidence_id)
            for claim in spec.get("claims", [])
            for evidence_id in claim.get("evidence_ids", [])
            if str(evidence_id) not in by_id
        }
    )
    checks.append(
        check(
            "claim_evidence_ids_resolve",
            not unresolved,
            observed=unresolved,
            expected=[],
            message="Every evidence_id referenced by a claim must exist in evidence.csv.",
        )
    )

    claims_without_limitation = [
        claim.get("claim_id", "<missing-id>")
        for claim in spec.get("claims", [])
        if not str(claim.get("limitation", "")).strip()
    ]
    checks.append(
        check(
            "claims_have_limitations",
            not claims_without_limitation,
            observed=claims_without_limitation,
            expected=[],
            message="Each claim needs a limitation so it cannot silently become stronger.",
        )
    )

    invalid_evidence_quality = sorted(
        {
            row.get("evidence_id", "<missing-id>")
            for row in evidence_rows
            if row.get("quality_status") not in ALLOWED_QUALITY_STATUSES
        }
    )
    checks.append(
        check(
            "evidence_quality_statuses_are_known",
            not invalid_evidence_quality,
            observed=invalid_evidence_quality,
            expected=sorted(ALLOWED_QUALITY_STATUSES),
            message="Unknown quality statuses make memo readiness ambiguous.",
        )
    )

    invalid_gate_status = sorted(
        {
            row.get("gate_id", "<missing-id>")
            for row in gate_rows
            if row.get("status") not in ALLOWED_QUALITY_STATUSES
        }
    )
    checks.append(
        check(
            "quality_gate_statuses_are_known",
            not invalid_gate_status,
            observed=invalid_gate_status,
            expected=sorted(ALLOWED_QUALITY_STATUSES),
            message="Unknown gate statuses make memo readiness ambiguous.",
        )
    )

    blocked_gate_ids = sorted(
        row.get("gate_id", "<missing-id>")
        for row in gate_rows
        if row.get("status") == "block"
    )
    checks.append(
        check(
            "quality_gates_do_not_block_memo",
            not blocked_gate_ids,
            observed=blocked_gate_ids,
            expected=[],
            message="A blocking quality gate stops publication of the memo.",
        )
    )

    warning_gate_ids = sorted(
        row.get("gate_id", "<missing-id>")
        for row in gate_rows
        if row.get("status") == "warn"
    )
    checks.append(
        check(
            "quality_gate_warnings_are_visible",
            not warning_gate_ids,
            severity="warn",
            observed=warning_gate_ids,
            expected=[],
            message="Warnings are allowed, but they must remain visible in audit and memo.",
        )
    )

    blocked_evidence_ids = sorted(
        {
            row["evidence_id"]
            for row in matrix
            if row.get("supports_decision") == "true" and row.get("quality_status") == "block"
        }
    )
    checks.append(
        check(
            "supporting_claims_have_usable_evidence",
            not blocked_evidence_ids,
            observed=blocked_evidence_ids,
            expected=[],
            message="A supporting claim cannot rely on blocked evidence.",
        )
    )

    warning_evidence_ids = sorted(
        {
            row["evidence_id"]
            for row in matrix
            if row.get("supports_decision") == "true" and row.get("quality_status") == "warn"
        }
    )
    checks.append(
        check(
            "evidence_quality_warnings_are_disclosed",
            not warning_evidence_ids,
            severity="warn",
            observed=warning_evidence_ids,
            expected=[],
            message="Warn-level supporting evidence must be disclosed in limitations.",
        )
    )

    causal_allowed = bool(spec.get("claim_boundary", {}).get("causal_claims_allowed", False))
    overclaimed_claims = [
        claim.get("claim_id", "<missing-id>")
        for claim in spec.get("claims", [])
        if text_has_forbidden_overclaim(str(claim.get("statement", "")))
    ]
    recommendation_overclaims = text_has_forbidden_overclaim(str(spec.get("recommendation", "")))
    checks.append(
        check(
            "no_unsupported_overclaim_wording",
            causal_allowed or (not overclaimed_claims and not recommendation_overclaims),
            observed={
                "claims": overclaimed_claims,
                "recommendation": recommendation_overclaims,
            },
            expected={"claims": [], "recommendation": False},
            message="Observational memos must not use causal or proof wording.",
        )
    )

    next_steps_without_owner = [
        step.get("step_id", "<missing-id>")
        for step in spec.get("next_steps", [])
        if not str(step.get("owner", "")).strip()
    ]
    checks.append(
        check(
            "next_steps_have_owner",
            bool(spec.get("next_steps")) and not next_steps_without_owner,
            observed=next_steps_without_owner,
            expected=[],
            message="Decision memo must leave a named next action owner.",
        )
    )

    missing_sections = [section for section in MEMO_REQUIRED_SECTIONS if section not in memo_text]
    checks.append(
        check(
            "memo_has_required_sections",
            not missing_sections,
            observed=missing_sections,
            expected=[],
            message="The rendered memo should be skimmable by a decision owner.",
        )
    )
    return checks


def build_audit(
    spec: dict[str, Any],
    evidence_rows: list[dict[str, str]],
    gate_rows: list[dict[str, str]],
    matrix: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    blockers = [item["id"] for item in checks if not item["valid"] and item["severity"] == "block"]
    warnings = [item["id"] for item in checks if not item["valid"] and item["severity"] == "warn"]
    if blockers:
        readiness = "blocked"
    elif warnings:
        readiness = "ready_with_warnings"
    else:
        readiness = "ready"
    return {
        "version": BUILDER_VERSION,
        "valid": not blockers,
        "readiness_status": readiness,
        "memo_id": spec.get("memo_id"),
        "recommended_decision": spec.get("recommended_decision"),
        "summary": {
            "claim_count": len(spec.get("claims", [])),
            "evidence_row_count": len(evidence_rows),
            "quality_gate_count": len(gate_rows),
            "matrix_row_count": len(matrix),
            "blocking_errors": blockers,
            "warnings": warnings,
        },
        "checks": checks,
    }


def render_memo(
    spec: dict[str, Any],
    matrix: list[dict[str, Any]],
    audit: dict[str, Any] | None = None,
) -> str:
    audit_status = audit["readiness_status"] if audit else "not_audited"
    lines = [
        f"# {spec.get('title', 'Decision memo')}",
        "",
        f"Memo ID: `{spec.get('memo_id', '')}`",
        f"Audience: {spec.get('audience', '')}",
        f"Decision owner: {spec.get('decision_owner', '')}",
    ]
    if spec.get("decision_due"):
        lines.append(f"Decision due: {spec['decision_due']}")
    lines.extend(
        [
            f"Audit status: `{audit_status}`",
            "",
            "## Question",
            "",
            str(spec.get("primary_question", "")),
            "",
            "## Decision Options",
            "",
        ]
    )
    for option in spec.get("decision_options", []):
        lines.append(
            f"- `{option.get('option_id', '')}` ({option.get('status', '')}): "
            f"{option.get('label', '')}. {option.get('reason', '')}"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"Recommended decision: `{spec.get('recommended_decision', '')}`.",
            "",
            str(spec.get("recommendation", "")),
            "",
            "## Evidence",
            "",
            "| Claim | Evidence | Metric | Quality | Finding |",
            "|---|---|---|---|---|",
        ]
    )
    for row in matrix:
        lines.append(
            "| {claim_id} | {evidence_id} | {metric_id} | {quality_status} | {finding} |".format(
                claim_id=row.get("claim_id", ""),
                evidence_id=row.get("evidence_id", ""),
                metric_id=row.get("metric_id", ""),
                quality_status=row.get("quality_status", ""),
                finding=str(row.get("finding", "")).replace("|", "/"),
            )
        )
    lines.extend(["", "## Limitations", ""])
    for limitation in spec.get("limitations", []):
        lines.append(
            f"- `{limitation.get('limitation_id', '')}` ({limitation.get('severity', '')}): "
            f"{limitation.get('text', '')}"
        )
    claim_boundary = spec.get("claim_boundary", {})
    lines.extend(
        [
            "",
            f"Causal claims allowed: `{str(claim_boundary.get('causal_claims_allowed', False)).lower()}`.",
            f"Scope: {claim_boundary.get('scope', '')}.",
            "",
            "## Next Step",
            "",
        ]
    )
    for step in spec.get("next_steps", []):
        lines.append(
            f"- `{step.get('step_id', '')}`: {step.get('action', '')} "
            f"Owner: {step.get('owner', '')}. Due: {step.get('due', '')}."
        )
    lines.append("")
    return "\n".join(lines)


def build_manifest(
    *,
    spec_path: Path,
    evidence_path: Path,
    quality_gates_path: Path,
    output_paths: dict[str, Path],
) -> dict[str, Any]:
    return {
        "version": BUILDER_VERSION,
        "hash_algorithm": "sha256",
        "inputs": {
            "memo_spec": {"path": str(spec_path), "sha256": sha256_file(spec_path)},
            "evidence": {"path": str(evidence_path), "sha256": sha256_file(evidence_path)},
            "quality_gates": {
                "path": str(quality_gates_path),
                "sha256": sha256_file(quality_gates_path),
            },
        },
        "outputs": {
            name: {"path": path.name, "sha256": sha256_file(path)}
            for name, path in sorted(output_paths.items())
        },
    }


def build_decision_memo(
    *,
    spec_path: str | Path,
    evidence_path: str | Path,
    quality_gates_path: str | Path,
    output_dir: str | Path,
) -> MemoBuildResult:
    spec_file = Path(spec_path)
    evidence_file = Path(evidence_path)
    gates_file = Path(quality_gates_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    spec = read_json(spec_file)
    evidence_rows = read_csv(evidence_file)
    gate_rows = read_csv(gates_file)
    matrix = build_claim_evidence_matrix(spec, evidence_rows)
    draft_memo = render_memo(spec, matrix)
    checks = validate_decision_memo(spec, evidence_rows, gate_rows, matrix, draft_memo)
    audit = build_audit(spec, evidence_rows, gate_rows, matrix, checks)
    memo_text = render_memo(spec, matrix, audit)

    memo_path = out / "executive_memo.md"
    matrix_path = out / "claim_evidence_matrix.csv"
    audit_path = out / "memo_audit.json"
    manifest_path = out / "manifest.json"
    memo_path.write_text(memo_text, encoding="utf-8")
    write_csv(
        matrix_path,
        matrix,
        [
            "claim_id",
            "claim",
            "claim_type",
            "supports_decision",
            "evidence_id",
            "artifact_path",
            "metric_id",
            "finding",
            "quality_status",
            "claim_scope",
            "claim_limitation",
            "evidence_limitation",
            "decision_impact",
        ],
    )
    write_json(audit_path, audit)
    manifest = build_manifest(
        spec_path=spec_file,
        evidence_path=evidence_file,
        quality_gates_path=gates_file,
        output_paths={
            "executive_memo": memo_path,
            "claim_evidence_matrix": matrix_path,
            "memo_audit": audit_path,
        },
    )
    write_json(manifest_path, manifest)
    return MemoBuildResult(
        output_dir=out,
        memo_path=memo_path,
        matrix_path=matrix_path,
        audit_path=audit_path,
        manifest_path=manifest_path,
        audit=audit,
        matrix=matrix,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a decision memo delivery package.")
    parser.add_argument("--spec", type=Path, help="Path to memo_spec.json.")
    parser.add_argument("--evidence", type=Path, help="Path to evidence.csv.")
    parser.add_argument("--quality-gates", type=Path, help="Path to quality_gates.csv.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for memo outputs.")
    parser.add_argument(
        "--write-example",
        type=Path,
        help="Write sample inputs to this directory before building.",
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Return a non-zero exit code when the memo is only ready with warnings.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    if args.write_example:
        sample_paths = write_sample_inputs(args.write_example)
        spec_path = sample_paths["spec_path"]
        evidence_path = sample_paths["evidence_path"]
        gates_path = sample_paths["quality_gates_path"]
    else:
        missing = [
            name
            for name, value in (
                ("--spec", args.spec),
                ("--evidence", args.evidence),
                ("--quality-gates", args.quality_gates),
            )
            if value is None
        ]
        if missing:
            parser.error("missing required arguments without --write-example: " + ", ".join(missing))
        spec_path = args.spec
        evidence_path = args.evidence
        gates_path = args.quality_gates
    result = build_decision_memo(
        spec_path=spec_path,
        evidence_path=evidence_path,
        quality_gates_path=gates_path,
        output_dir=args.output_dir,
    )
    report = {
        "valid": result.audit["valid"],
        "readiness_status": result.audit["readiness_status"],
        "recommended_decision": result.audit["recommended_decision"],
        "memo_path": str(result.memo_path),
        "matrix_path": str(result.matrix_path),
        "audit_path": str(result.audit_path),
        "manifest_path": str(result.manifest_path),
        "blocking_errors": result.audit["summary"]["blocking_errors"],
        "warnings": result.audit["summary"]["warnings"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not result.audit["valid"]:
        return 2
    if args.fail_on_warning and result.audit["readiness_status"] == "ready_with_warnings":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
