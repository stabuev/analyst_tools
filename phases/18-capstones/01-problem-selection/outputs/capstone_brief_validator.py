from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

BRIEF_VERSION = "1.0.0"
MIN_SCOPE_HOURS = 30
MAX_SCOPE_HOURS = 50
CORE_PHASES = tuple(range(8))
RISK_CATEGORIES = {
    "data_access",
    "privacy",
    "methodology",
    "compute",
    "delivery",
    "review",
}
MILESTONE_STAGES = (
    "problem_selection",
    "data_contract",
    "baseline",
    "implementation",
    "verification",
    "peer_review",
    "defense",
)
REQUIRED_FIELDS = {
    "project_id",
    "project_title",
    "profile_kind",
    "route",
    "route_variant",
    "decision_owner",
    "decision",
    "decision_options",
    "claim_type",
    "unit_of_decision",
    "population",
    "time_horizon",
    "scope",
    "completed_phases",
    "declared_prerequisites",
    "success_criteria",
    "risks",
    "milestones",
    "assistance_disclosure",
    "planning_as_of",
}
ROUTE_PROFILES: dict[str, dict[str, Any]] = {
    "core_analytics": {
        "variants": {"standard": list(CORE_PHASES) + [17]},
        "claim_types": {"descriptive", "associational"},
    },
    "product_experiments": {
        "variants": {"standard": list(range(11)) + [17]},
        "claim_types": {"product_decision", "experimental_causal"},
    },
    "data_analytics_engineering": {
        "variants": {"standard": list(CORE_PHASES) + [11, 12, 17]},
        "claim_types": {"data_quality", "lineage", "freshness", "performance"},
    },
    "decision_science": {
        "variants": {
            "causal": list(CORE_PHASES) + [13, 17],
            "forecast": list(CORE_PHASES) + [14, 17],
        },
        "claim_types": {"causal", "forecast"},
    },
    "machine_learning": {
        "variants": {
            "baseline": list(CORE_PHASES) + [15, 17],
            "strong_model": list(CORE_PHASES) + [15, 16, 17],
        },
        "claim_types": {"predictive", "decision_policy"},
    },
    "delivery_product": {
        "variants": {"standard": list(CORE_PHASES) + [17]},
        "claim_types": {"delivery_quality", "upstream_preserving"},
    },
}


class CapstoneBriefError(ValueError):
    """Raised when capstone brief inputs cannot be parsed."""


def non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def check(
    check_id: str,
    valid: bool,
    *,
    observed: Any,
    expected: Any,
    message: str,
    severity: str = "block",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": bool(valid),
        "observed": observed,
        "expected": expected,
        "message": message,
    }


def read_json(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CapstoneBriefError(f"{source} must contain a JSON object")
    return value


def write_json(path: str | Path, value: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def required_prerequisites(route: Any, variant: Any) -> list[int] | None:
    profile = ROUTE_PROFILES.get(route) if isinstance(route, str) else None
    if profile is None or not isinstance(variant, str):
        return None
    prerequisites = profile["variants"].get(variant)
    return list(prerequisites) if prerequisites is not None else None


def validate_required_fields(brief: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUIRED_FIELDS - set(brief))
    return check(
        "brief_required_fields",
        not missing,
        observed=missing,
        expected=sorted(REQUIRED_FIELDS),
        message="The project brief must be complete before methods or data are selected.",
    )


def validate_identity(brief: dict[str, Any]) -> dict[str, Any]:
    fields = ("project_id", "project_title", "planning_as_of")
    invalid = [field for field in fields if not non_empty_text(brief.get(field))]
    profile_kind = brief.get("profile_kind")
    if profile_kind not in {"reference_tiny", "student_project"}:
        invalid.append("profile_kind")
    return check(
        "project_identity_is_explicit",
        not invalid,
        observed={field: brief.get(field) for field in fields + ("profile_kind",)},
        expected="non-empty identity fields and profile_kind reference_tiny|student_project",
        message="Stable project identity makes every downstream artifact traceable.",
    )


def validate_decision(brief: dict[str, Any]) -> dict[str, Any]:
    owner = brief.get("decision_owner")
    options = brief.get("decision_options")
    errors: list[dict[str, Any]] = []
    if not non_empty_text(brief.get("decision")):
        errors.append({"field": "decision", "reason": "decision question is required"})
    if not isinstance(owner, dict):
        errors.append({"field": "decision_owner", "reason": "owner object is required"})
    else:
        if not non_empty_text(owner.get("role")):
            errors.append({"field": "decision_owner.role", "reason": "owner role is required"})
        if owner.get("accountable") is not True:
            errors.append(
                {"field": "decision_owner.accountable", "reason": "one role must be accountable"}
            )
    option_ids: list[str] = []
    if not isinstance(options, list):
        errors.append({"field": "decision_options", "reason": "option list required"})
    else:
        if len(options) < 2:
            errors.append({"field": "decision_options", "reason": "at least two actions required"})
        for position, option in enumerate(options):
            if not isinstance(option, dict) or not non_empty_text(option.get("id")):
                errors.append(
                    {"field": f"decision_options[{position}]", "reason": "option id required"}
                )
                continue
            option_ids.append(option["id"])
            if not non_empty_text(option.get("description")):
                errors.append(
                    {
                        "field": f"decision_options[{position}].description",
                        "reason": "description required",
                    }
                )
        if len(option_ids) != len(set(option_ids)):
            errors.append({"field": "decision_options", "reason": "option ids must be unique"})
        if "no_action" not in option_ids:
            errors.append(
                {"field": "decision_options", "reason": "no_action must remain available"}
            )
    return check(
        "decision_precedes_analysis",
        not errors,
        observed={"owner": owner, "option_ids": option_ids, "errors": errors},
        expected=(
            "accountable owner, explicit decision and at least two unique options "
            "including no_action"
        ),
        message="A capstone exists to support a decision, not to demonstrate a favorite tool.",
    )


def validate_route_readiness(brief: dict[str, Any]) -> dict[str, Any]:
    route = brief.get("route")
    variant = brief.get("route_variant")
    required = required_prerequisites(route, variant)
    declared = brief.get("declared_prerequisites")
    completed = brief.get("completed_phases")
    errors: list[dict[str, Any]] = []
    if required is None:
        errors.append(
            {
                "field": "route/route_variant",
                "observed": [route, variant],
                "expected_routes": {
                    key: sorted(profile["variants"]) for key, profile in ROUTE_PROFILES.items()
                },
            }
        )
        required = []
    if not isinstance(declared, list) or any(not isinstance(item, int) for item in declared):
        errors.append({"field": "declared_prerequisites", "reason": "integer phase list required"})
        declared_values: set[int] = set()
    else:
        declared_values = set(declared)
        if declared_values != set(required):
            errors.append(
                {
                    "field": "declared_prerequisites",
                    "missing": sorted(set(required) - declared_values),
                    "unnecessary": sorted(declared_values - set(required)),
                }
            )
    if not isinstance(completed, list) or any(not isinstance(item, int) for item in completed):
        errors.append({"field": "completed_phases", "reason": "integer phase list required"})
        completed_values: set[int] = set()
    else:
        completed_values = set(completed)
        missing_completed = sorted(set(required) - completed_values)
        if missing_completed:
            errors.append({"field": "completed_phases", "missing": missing_completed})
    return check(
        "route_prerequisites_are_minimal_and_complete",
        not errors,
        observed={
            "route": route,
            "variant": variant,
            "required": required,
            "declared": sorted(declared_values),
            "completed": sorted(completed_values),
            "errors": errors,
        },
        expected="declared prerequisites exactly match the selected route and all are completed",
        message="A route may require its own methods without forcing unrelated specializations.",
    )


def validate_claim_boundary(brief: dict[str, Any]) -> dict[str, Any]:
    route = brief.get("route")
    variant = brief.get("route_variant")
    claim_type = brief.get("claim_type")
    profile = ROUTE_PROFILES.get(route) if isinstance(route, str) else None
    allowed = sorted(profile["claim_types"]) if profile else []
    errors: list[dict[str, Any]] = []
    if claim_type not in allowed:
        errors.append({"field": "claim_type", "observed": claim_type, "allowed": allowed})
    if route == "decision_science" and variant != claim_type:
        errors.append(
            {
                "field": "route_variant/claim_type",
                "observed": [variant, claim_type],
                "expected": "causal/causal or forecast/forecast",
            }
        )
    if route == "delivery_product":
        if not non_empty_text(brief.get("upstream_package_id")):
            errors.append(
                {"field": "upstream_package_id", "reason": "verified evidence package required"}
            )
        if not non_empty_text(brief.get("upstream_claim_type")):
            errors.append(
                {"field": "upstream_claim_type", "reason": "upstream claim boundary required"}
            )
    return check(
        "claim_matches_route_boundary",
        not errors,
        observed={"route": route, "variant": variant, "claim_type": claim_type, "errors": errors},
        expected={"allowed_claim_types": allowed},
        message="The selected route limits what the final project may claim.",
    )


def validate_decision_context(brief: dict[str, Any]) -> dict[str, Any]:
    horizon = brief.get("time_horizon")
    errors: list[dict[str, Any]] = []
    for field in ("unit_of_decision", "population"):
        if not non_empty_text(brief.get(field)):
            errors.append({"field": field, "reason": "non-empty text required"})
    if not isinstance(horizon, dict):
        errors.append({"field": "time_horizon", "reason": "object required"})
    else:
        value = horizon.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            errors.append({"field": "time_horizon.value", "reason": "positive number required"})
        if horizon.get("unit") not in {"days", "weeks", "months"}:
            errors.append({"field": "time_horizon.unit", "reason": "days|weeks|months required"})
    return check(
        "decision_unit_population_and_horizon_are_explicit",
        not errors,
        observed={
            "unit_of_decision": brief.get("unit_of_decision"),
            "population": brief.get("population"),
            "time_horizon": horizon,
            "errors": errors,
        },
        expected="decision unit, population and positive time horizon",
        message="A decision without a unit, population and horizon cannot be verified later.",
    )


def validate_scope(brief: dict[str, Any]) -> dict[str, Any]:
    scope = brief.get("scope")
    errors: list[dict[str, Any]] = []
    if not isinstance(scope, dict):
        return check(
            "scope_fits_capstone_budget",
            False,
            observed=scope,
            expected=f"scope object with {MIN_SCOPE_HOURS}-{MAX_SCOPE_HOURS} hours",
            message=(
                "The capstone must be small enough to finish and large enough "
                "to integrate the route."
            ),
        )
    hours = scope.get("estimated_hours")
    if (
        not isinstance(hours, (int, float))
        or isinstance(hours, bool)
        or not MIN_SCOPE_HOURS <= hours <= MAX_SCOPE_HOURS
    ):
        errors.append(
            {
                "field": "scope.estimated_hours",
                "observed": hours,
                "expected": [MIN_SCOPE_HOURS, MAX_SCOPE_HOURS],
            }
        )
    for field, minimum in (
        ("in_scope", 2),
        ("non_goals", 2),
        ("stop_conditions", 2),
        ("deliverables", 4),
    ):
        value = scope.get(field)
        if (
            not isinstance(value, list)
            or len(value) < minimum
            or any(not non_empty_text(item) for item in value)
        ):
            errors.append({"field": f"scope.{field}", "reason": f"at least {minimum} items"})
    return check(
        "scope_fits_capstone_budget",
        not errors,
        observed={"scope": scope, "errors": errors},
        expected=(
            f"{MIN_SCOPE_HOURS}-{MAX_SCOPE_HOURS} hours with in-scope, non-goals, "
            "stop conditions and deliverables"
        ),
        message="Explicit non-goals and stop conditions prevent an endless portfolio project.",
    )


def validate_success_criteria(brief: dict[str, Any]) -> dict[str, Any]:
    criteria = brief.get("success_criteria")
    errors: list[dict[str, Any]] = []
    ids: list[str] = []
    if not isinstance(criteria, list) or len(criteria) < 2:
        errors.append({"field": "success_criteria", "reason": "at least two criteria required"})
    else:
        for position, criterion in enumerate(criteria):
            if not isinstance(criterion, dict):
                errors.append({"position": position, "reason": "criterion must be an object"})
                continue
            for field in ("id", "description", "acceptance_test"):
                if not non_empty_text(criterion.get(field)):
                    errors.append({"position": position, "field": field, "reason": "required"})
            if non_empty_text(criterion.get("id")):
                ids.append(criterion["id"])
        if len(ids) != len(set(ids)):
            errors.append({"field": "success_criteria.id", "reason": "ids must be unique"})
    return check(
        "success_criteria_are_testable",
        not errors,
        observed={"count": len(criteria) if isinstance(criteria, list) else 0, "errors": errors},
        expected="at least two unique criteria with explicit acceptance tests",
        message="Success must be checkable before the result is known.",
    )


def validate_risks(brief: dict[str, Any]) -> dict[str, Any]:
    risks = brief.get("risks")
    errors: list[dict[str, Any]] = []
    ids: list[str] = []
    categories: set[str] = set()
    if not isinstance(risks, list):
        errors.append({"field": "risks", "reason": "risk list required"})
    else:
        for position, risk in enumerate(risks):
            if not isinstance(risk, dict):
                errors.append({"position": position, "reason": "risk must be an object"})
                continue
            for field in ("id", "category", "description", "mitigation", "owner", "trigger"):
                if not non_empty_text(risk.get(field)):
                    errors.append({"position": position, "field": field, "reason": "required"})
            if risk.get("likelihood") not in {"low", "medium", "high"}:
                errors.append(
                    {"position": position, "field": "likelihood", "reason": "low|medium|high"}
                )
            if risk.get("impact") not in {"low", "medium", "high"}:
                errors.append(
                    {"position": position, "field": "impact", "reason": "low|medium|high"}
                )
            if risk.get("status") not in {"open", "mitigated", "accepted"}:
                errors.append(
                    {"position": position, "field": "status", "reason": "open|mitigated|accepted"}
                )
            if non_empty_text(risk.get("id")):
                ids.append(risk["id"])
            if non_empty_text(risk.get("category")):
                categories.add(risk["category"])
        if len(ids) != len(set(ids)):
            errors.append({"field": "risks.id", "reason": "ids must be unique"})
        missing_categories = sorted(RISK_CATEGORIES - categories)
        if missing_categories:
            errors.append({"field": "risks.category", "missing": missing_categories})
    return check(
        "risk_register_covers_capstone_lifecycle",
        not errors,
        observed={
            "categories": sorted(categories),
            "count": len(risks) if isinstance(risks, list) else 0,
            "errors": errors,
        },
        expected=sorted(RISK_CATEGORIES),
        message=(
            "Risk planning covers data access, privacy, methodology, compute, delivery and review."
        ),
    )


def validate_milestones(brief: dict[str, Any]) -> dict[str, Any]:
    milestones = brief.get("milestones")
    scope = brief.get("scope")
    errors: list[dict[str, Any]] = []
    stages: list[str] = []
    ids: list[str] = []
    total_hours = 0.0
    if not isinstance(milestones, list):
        errors.append({"field": "milestones", "reason": "milestone list required"})
    else:
        for position, milestone in enumerate(milestones):
            if not isinstance(milestone, dict):
                errors.append({"position": position, "reason": "milestone must be an object"})
                continue
            milestone_id = milestone.get("id")
            stage = milestone.get("stage")
            if not non_empty_text(milestone_id):
                errors.append({"position": position, "field": "id", "reason": "required"})
            else:
                ids.append(milestone_id)
            if not non_empty_text(stage):
                errors.append({"position": position, "field": "stage", "reason": "required"})
            else:
                stages.append(stage)
            hours = milestone.get("estimated_hours")
            if not isinstance(hours, (int, float)) or isinstance(hours, bool) or hours <= 0:
                errors.append(
                    {"position": position, "field": "estimated_hours", "reason": "positive number"}
                )
            else:
                total_hours += float(hours)
            for field in ("artifact", "acceptance_gate"):
                if not non_empty_text(milestone.get(field)):
                    errors.append({"position": position, "field": field, "reason": "required"})
            depends_on = milestone.get("depends_on")
            expected_dependency = (
                [] if position == 0 else [ids[position - 1]] if len(ids) >= position else []
            )
            if depends_on != expected_dependency:
                errors.append(
                    {
                        "position": position,
                        "field": "depends_on",
                        "observed": depends_on,
                        "expected": expected_dependency,
                    }
                )
        if tuple(stages) != MILESTONE_STAGES:
            errors.append(
                {
                    "field": "milestones.stage",
                    "observed": stages,
                    "expected": list(MILESTONE_STAGES),
                }
            )
        if len(ids) != len(set(ids)):
            errors.append({"field": "milestones.id", "reason": "ids must be unique"})
    expected_hours = scope.get("estimated_hours") if isinstance(scope, dict) else None
    if isinstance(expected_hours, (int, float)) and abs(total_hours - float(expected_hours)) > 1e-9:
        errors.append(
            {
                "field": "milestones.estimated_hours",
                "observed": total_hours,
                "expected": expected_hours,
            }
        )
    return check(
        "milestones_cover_all_stage_gates",
        not errors,
        observed={"stages": stages, "total_hours": total_hours, "errors": errors},
        expected={"stages": list(MILESTONE_STAGES), "total_hours": expected_hours},
        message=(
            "Every stage needs an artifact, acceptance gate, dependency and honest time budget."
        ),
    )


def validate_assistance_disclosure(brief: dict[str, Any]) -> dict[str, Any]:
    disclosure = brief.get("assistance_disclosure")
    errors: list[dict[str, Any]] = []
    if not isinstance(disclosure, dict):
        errors.append({"field": "assistance_disclosure", "reason": "object required"})
    else:
        if not isinstance(disclosure.get("ai_assistance_allowed"), bool):
            errors.append({"field": "ai_assistance_allowed", "reason": "boolean required"})
        if disclosure.get("disclosure_required") is not True:
            errors.append({"field": "disclosure_required", "reason": "must be true"})
        if not non_empty_text(disclosure.get("author_accountability")):
            errors.append({"field": "author_accountability", "reason": "statement required"})
        prohibited = disclosure.get("prohibited_uses")
        if not isinstance(prohibited, list) or "unverified_claims" not in prohibited:
            errors.append(
                {"field": "prohibited_uses", "reason": "unverified_claims must be prohibited"}
            )
    return check(
        "assistance_is_disclosed_without_delegating_accountability",
        not errors,
        observed={"disclosure": disclosure, "errors": errors},
        expected="AI assistance policy, mandatory disclosure and author accountability",
        message=(
            "Tools may assist the work, but the student remains responsible for claims and checks."
        ),
    )


def validate_reference_profile(brief: dict[str, Any]) -> dict[str, Any]:
    is_reference = brief.get("profile_kind") == "reference_tiny"
    return check(
        "reference_profile_is_not_portfolio_evidence",
        not is_reference,
        observed=brief.get("profile_kind"),
        expected="student_project for final portfolio submission",
        message=(
            "The tiny reference brief teaches the contract and must be replaced for final defense."
        ),
        severity="warning",
    )


def validate_capstone_brief(brief: dict[str, Any]) -> dict[str, Any]:
    checks = [
        validate_required_fields(brief),
        validate_identity(brief),
        validate_decision(brief),
        validate_route_readiness(brief),
        validate_claim_boundary(brief),
        validate_decision_context(brief),
        validate_scope(brief),
        validate_success_criteria(brief),
        validate_risks(brief),
        validate_milestones(brief),
        validate_assistance_disclosure(brief),
        validate_reference_profile(brief),
    ]
    blocking_errors = [
        item["id"] for item in checks if not item["valid"] and item["severity"] == "block"
    ]
    warnings = [
        item["id"] for item in checks if not item["valid"] and item["severity"] == "warning"
    ]
    valid = not blocking_errors
    required = required_prerequisites(brief.get("route"), brief.get("route_variant")) or []
    return {
        "version": BRIEF_VERSION,
        "project_id": brief.get("project_id"),
        "status": "ready_for_data_contract" if valid else "brief_revision_required",
        "valid": valid,
        "checks": checks,
        "summary": {
            "blocking_errors": blocking_errors,
            "warnings": warnings,
            "check_count": len(checks),
            "route": brief.get("route"),
            "route_variant": brief.get("route_variant"),
            "claim_type": brief.get("claim_type"),
            "required_prerequisites": required,
            "estimated_hours": (brief.get("scope") or {}).get("estimated_hours")
            if isinstance(brief.get("scope"), dict)
            else None,
            "risk_count": len(brief.get("risks", []))
            if isinstance(brief.get("risks"), list)
            else 0,
            "milestone_count": len(brief.get("milestones", []))
            if isinstance(brief.get("milestones"), list)
            else 0,
            "next_stage": "data_contract" if valid else "problem_selection",
        },
    }


def default_capstone_brief() -> dict[str, Any]:
    prerequisites = list(CORE_PHASES) + [17]
    stages = [
        ("m01", "problem_selection", 4, "capstone brief package"),
        ("m02", "data_contract", 6, "data contract package"),
        ("m03", "baseline", 5, "baseline package"),
        ("m04", "implementation", 12, "route implementation package"),
        ("m05", "verification", 7, "independent verification package"),
        ("m06", "peer_review", 5, "peer review package"),
        ("m07", "defense", 5, "capstone portfolio package"),
    ]
    milestones = []
    for position, (milestone_id, stage, hours, artifact) in enumerate(stages):
        milestones.append(
            {
                "id": milestone_id,
                "stage": stage,
                "estimated_hours": hours,
                "artifact": artifact,
                "acceptance_gate": f"{stage} contract passes with no blocking findings",
                "depends_on": [] if position == 0 else [stages[position - 1][0]],
            }
        )
    risk_rows = [
        (
            "r01",
            "data_access",
            "Reference event extract may be unavailable",
            "Confirm synthetic fallback before data-contract work",
        ),
        (
            "r02",
            "privacy",
            "User-level fields may enter a public sample",
            "Publish only aggregated or synthetic rows",
        ),
        (
            "r03",
            "methodology",
            "Descriptive evidence may be written as causal",
            "Block causal wording in claim review",
        ),
        (
            "r04",
            "compute",
            "Implementation may exceed a laptop budget",
            "Keep a deterministic tiny profile and bounded sample",
        ),
        (
            "r05",
            "delivery",
            "Consumer artifact may be stale or hard to rerun",
            "Require freshness marker and one-command build",
        ),
        (
            "r06",
            "review",
            "Independent review may arrive after the defense date",
            "Reserve review slot before implementation",
        ),
    ]
    risks = [
        {
            "id": risk_id,
            "category": category,
            "description": description,
            "likelihood": "medium",
            "impact": "high" if category in {"data_access", "privacy", "methodology"} else "medium",
            "mitigation": mitigation,
            "owner": "capstone-author",
            "trigger": f"{category} gate fails or evidence is missing",
            "status": "open",
        }
        for risk_id, category, description, mitigation in risk_rows
    ]
    return {
        "project_id": "weekly-retention-decision-core",
        "project_title": "Weekly retention decision diagnostic",
        "profile_kind": "reference_tiny",
        "route": "core_analytics",
        "route_variant": "standard",
        "decision_owner": {"role": "head_of_support_operations", "accountable": True},
        "decision": (
            "Should support operations keep the current weekly retention review "
            "or prioritize a defined at-risk segment for manual review?"
        ),
        "decision_options": [
            {
                "id": "no_action",
                "description": "Keep the current weekly review without a new targeting rule.",
            },
            {
                "id": "targeted_manual_review",
                "description": (
                    "Prioritize a predeclared at-risk segment for manual support review."
                ),
            },
        ],
        "claim_type": "descriptive",
        "unit_of_decision": "weekly_retention_policy_review",
        "population": "eligible trial users with complete seven-day observation windows",
        "time_horizon": {"value": 7, "unit": "days"},
        "scope": {
            "estimated_hours": 44,
            "in_scope": [
                "audit activation and support-load evidence for the eligible population",
                "compare a no-action baseline with one predeclared manual-review policy",
                "ship a reproducible decision package with independent verification",
            ],
            "non_goals": [
                "claim a causal effect of support outreach",
                "build an online production service or automated account action",
            ],
            "stop_conditions": [
                "required source cannot be published or replaced with a synthetic equivalent",
                "decision owner cannot choose between the declared actions",
                "a blocking quality gate remains unresolved after the verification budget",
            ],
            "deliverables": [
                "capstone brief and risk register",
                "data contract and audit",
                "manual baseline and complexity budget",
                "route implementation and evidence ledger",
                "verification and review closure",
                "defense brief and portfolio package",
            ],
        },
        "completed_phases": list(range(18)),
        "declared_prerequisites": prerequisites,
        "success_criteria": [
            {
                "id": "decision_traceability",
                "description": (
                    "Every recommendation is linked to a declared action and evidence item."
                ),
                "acceptance_test": "claim-evidence audit has zero unresolved links",
            },
            {
                "id": "reproducible_handoff",
                "description": "A reviewer can rebuild the public package from allowed inputs.",
                "acceptance_test": "clean-room command exits zero and manifest hashes match",
            },
        ],
        "risks": risks,
        "milestones": milestones,
        "assistance_disclosure": {
            "ai_assistance_allowed": True,
            "disclosure_required": True,
            "author_accountability": (
                "The author verifies every claim, source, calculation and test."
            ),
            "prohibited_uses": [
                "unverified_claims",
                "fabricated_sources",
                "hidden_answer_generation",
            ],
        },
        "planning_as_of": "2026-01-05T00:00:00Z",
    }


def write_example(root: str | Path) -> Path:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    return write_json(root_path / "capstone_brief.json", default_capstone_brief())


def write_csv_rows(path: Path, rows: Any, fieldnames: list[str]) -> Path:
    normalized_rows = rows if isinstance(rows, list) else []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in normalized_rows:
            source = row if isinstance(row, dict) else {}
            normalized = {field: source.get(field, "") for field in fieldnames}
            if isinstance(normalized.get("depends_on"), list):
                normalized["depends_on"] = "|".join(normalized["depends_on"])
            writer.writerow(normalized)
    return path


def build_capstone_brief_package(
    *,
    brief_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    source_path = Path(brief_path)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    brief = read_json(source_path)
    report = validate_capstone_brief(brief)

    risk_path = write_csv_rows(
        output_path / "risk_register.csv",
        brief.get("risks"),
        [
            "id",
            "category",
            "description",
            "likelihood",
            "impact",
            "mitigation",
            "owner",
            "trigger",
            "status",
        ],
    )
    milestone_path = write_csv_rows(
        output_path / "milestone_plan.csv",
        brief.get("milestones"),
        ["id", "stage", "estimated_hours", "artifact", "acceptance_gate", "depends_on"],
    )
    audit_path = write_json(output_path / "capstone_brief_audit.json", report)
    tracked_outputs = {
        "audit": audit_path,
        "risk_register": risk_path,
        "milestone_plan": milestone_path,
    }
    state = {
        "version": BRIEF_VERSION,
        "project_id": brief.get("project_id"),
        "project_title": brief.get("project_title"),
        "route": brief.get("route"),
        "route_variant": brief.get("route_variant"),
        "route_prerequisites": report["summary"]["required_prerequisites"],
        "decision_owner": brief.get("decision_owner"),
        "decision": brief.get("decision"),
        "decision_options": brief.get("decision_options"),
        "claim_type": brief.get("claim_type"),
        "scope": brief.get("scope"),
        "non_goals": (brief.get("scope") or {}).get("non_goals", [])
        if isinstance(brief.get("scope"), dict)
        else [],
        "data_contract_id": None,
        "baseline_id": None,
        "implementation_id": None,
        "verification_id": None,
        "review_id": None,
        "defense_id": None,
        "current_stage": "problem_selection",
        "stage_status": report["status"],
        "open_blockers": report["summary"]["blocking_errors"],
        "warnings": report["summary"]["warnings"],
        "artifact_inventory": [path.name for path in tracked_outputs.values()],
        "evidence_links": [],
        "input_checksums": {source_path.name: sha256_file(source_path)},
        "output_checksums": {path.name: sha256_file(path) for path in tracked_outputs.values()},
        "assistance_disclosure": brief.get("assistance_disclosure"),
        "updated_at": brief.get("planning_as_of"),
    }
    state_path = write_json(output_path / "capstone_state.json", state)
    tracked_outputs["capstone_state"] = state_path
    manifest = {
        "version": BRIEF_VERSION,
        "project_id": brief.get("project_id"),
        "status": report["status"],
        "valid": report["valid"],
        "hash_algorithm": "sha256",
        "renderer_used": "capstone_brief_validator",
        "inputs": {
            "capstone_brief": {
                "path": source_path.name,
                "sha256": sha256_file(source_path),
                "bytes": source_path.stat().st_size,
            }
        },
        "outputs": {
            name: {
                "path": path.name,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for name, path in tracked_outputs.items()
        },
    }
    manifest_path = write_json(output_path / "brief_manifest.json", manifest)
    return {
        "report": report,
        "output_dir": output_path,
        "audit_path": audit_path,
        "risk_register_path": risk_path,
        "milestone_plan_path": milestone_path,
        "state_path": state_path,
        "manifest_path": manifest_path,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a capstone brief before data-contract work begins.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--brief", type=Path, help="Path to capstone_brief.json.")
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Directory for audit outputs."
    )
    parser.add_argument(
        "--write-example", type=Path, help="Write a deterministic reference brief here."
    )
    parser.add_argument(
        "--fail-on-invalid", action="store_true", help="Return exit code 1 for a blocked brief."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    brief_path = parsed.brief
    if parsed.write_example:
        example_path = write_example(parsed.write_example)
        brief_path = brief_path or example_path
    if brief_path is None:
        payload = {
            "version": BRIEF_VERSION,
            "status": "system_error",
            "valid": False,
            "error": {"code": "missing_brief", "message": "--brief or --write-example is required"},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    try:
        result = build_capstone_brief_package(
            brief_path=brief_path,
            output_dir=parsed.output_dir,
        )
    except (OSError, json.JSONDecodeError, CapstoneBriefError) as error:
        payload = {
            "version": BRIEF_VERSION,
            "status": "system_error",
            "valid": False,
            "error": {"code": "invalid_input", "message": str(error)},
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 2
    report = result["report"]
    payload = {
        "status": report["status"],
        "valid": report["valid"],
        "project_id": report["project_id"],
        "route": report["summary"]["route"],
        "claim_type": report["summary"]["claim_type"],
        "blocking_errors": report["summary"]["blocking_errors"],
        "warnings": report["summary"]["warnings"],
        "output_dir": str(result["output_dir"]),
        "manifest": str(result["manifest_path"]),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if parsed.fail_on_invalid and not report["valid"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
