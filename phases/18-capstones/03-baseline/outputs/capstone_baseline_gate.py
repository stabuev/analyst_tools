from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

BASELINE_VERSION = "1.0.0"
PUBLIC_SAMPLE_FIELDS = (
    "as_of_week",
    "segment_id",
    "users",
    "activated_users",
    "activation_rate",
    "support_ticket_count",
    "churned_users",
)
METRIC_FIELDS = (
    "as_of_week",
    "segment_id",
    "users",
    "activated_users",
    "activation_rate",
    "support_ticket_count",
    "support_tickets_per_user",
    "churned_users",
    "churn_rate",
    "rank",
    "selected",
)
REQUIRED_SPEC_FIELDS = {
    "baseline_id",
    "project_id",
    "contract_id",
    "version",
    "route",
    "route_variant",
    "decision_question",
    "input_contract",
    "baseline_policy",
    "manual_reconciliation",
    "acceptance_metric",
    "complexity_budget",
    "created_before_implementation",
}
FORBIDDEN_RESULT_FIELDS = {
    "candidate_value",
    "candidate_pass",
    "implementation_score",
    "test_score",
    "final_model_metric",
}
ROUTE_BASELINE_PROFILES: dict[tuple[str, str], dict[str, str]] = {
    ("core_analytics", "standard"): {
        "baseline_kind": "segment_rate_rule",
        "acceptance_metric": "captured_churn_recall",
        "direction": "maximize",
        "claim_boundary": "descriptive_observed_priority_not_intervention_effect",
    },
    ("product_experiments", "standard"): {
        "baseline_kind": "unadjusted_assignment_mean_difference",
        "acceptance_metric": "decision_loss",
        "direction": "minimize",
        "claim_boundary": "randomized_difference_only_after_design_gates",
    },
    ("data_analytics_engineering", "standard"): {
        "baseline_kind": "direct_query_quality_benchmark",
        "acceptance_metric": "contract_pass_rate",
        "direction": "maximize",
        "claim_boundary": "correctness_freshness_performance_not_user_impact",
    },
    ("decision_science", "causal"): {
        "baseline_kind": "unadjusted_outcome_difference",
        "acceptance_metric": "identification_robustness",
        "direction": "maximize",
        "claim_boundary": "unadjusted_baseline_is_not_a_causal_effect",
    },
    ("decision_science", "forecast"): {
        "baseline_kind": "seasonal_naive_forecast",
        "acceptance_metric": "mae",
        "direction": "minimize",
        "claim_boundary": "forecast_accuracy_within_declared_horizon",
    },
    ("machine_learning", "baseline"): {
        "baseline_kind": "dummy_or_rate_rule",
        "acceptance_metric": "expected_decision_cost",
        "direction": "minimize",
        "claim_boundary": "predictive_priority_not_intervention_effect",
    },
    ("machine_learning", "strong_model"): {
        "baseline_kind": "dummy_or_rate_rule",
        "acceptance_metric": "expected_decision_cost",
        "direction": "minimize",
        "claim_boundary": "predictive_priority_not_intervention_effect",
    },
    ("delivery_product", "standard"): {
        "baseline_kind": "static_verified_package",
        "acceptance_metric": "successful_consumer_task_rate",
        "direction": "maximize",
        "claim_boundary": "delivery_quality_without_upstream_claim_amplification",
    },
}


class BaselineGateError(ValueError):
    """Raised when baseline inputs cannot be parsed."""


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
        raise BaselineGateError(f"{source} must contain a JSON object")
    return value


def write_json(path: str | Path, value: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def read_csv(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    with Path(path).open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: str | Path, rows: list[dict[str, Any]], fields: list[str]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)
    return target


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_data_builder():
    artifact = (
        Path(__file__).resolve().parents[2]
        / "02-data-contract"
        / "outputs"
        / "capstone_data_contract_auditor.py"
    )
    spec = importlib.util.spec_from_file_location("capstone_data_contract_auditor", artifact)
    if spec is None or spec.loader is None:
        raise BaselineGateError(f"cannot load upstream data builder: {artifact}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def route_profile(route: str, variant: str) -> dict[str, str]:
    profile = ROUTE_BASELINE_PROFILES.get((route, variant))
    if profile is None:
        raise BaselineGateError(f"unsupported route/variant: {route}/{variant}")
    return dict(profile)


def default_baseline_spec(state: dict[str, Any]) -> dict[str, Any]:
    route = str(state.get("route"))
    variant = str(state.get("route_variant"))
    profile = route_profile(route, variant)
    return {
        "baseline_id": "weekly-retention-segment-baseline-v1",
        "project_id": state.get("project_id"),
        "contract_id": state.get("data_contract_id"),
        "version": BASELINE_VERSION,
        "route": route,
        "route_variant": variant,
        "decision_question": state.get("decision"),
        "input_contract": {
            "path": "public_data_sample.csv",
            "publication_class": "aggregated",
            "grain": ["as_of_week", "segment_id"],
            "required_fields": list(PUBLIC_SAMPLE_FIELDS),
        },
        "baseline_policy": {
            "baseline_kind": profile["baseline_kind"],
            "ranking_metric": "churn_rate",
            "ranking_direction": "maximize",
            "tie_breakers": ["support_tickets_per_user", "segment_id"],
            "max_selected_segments": 1,
            "action_on_selection": "targeted_manual_review",
            "fallback_action": "no_action",
            "claim_boundary": profile["claim_boundary"],
            "no_causal_claim": True,
        },
        "manual_reconciliation": {
            "slice": {
                "as_of_week": "2026-01-05T00:00:00Z",
                "segment_id": "high_touch",
            },
            "expected_inputs": {
                "users": 4,
                "activated_users": 2,
                "support_ticket_count": 6,
                "churned_users": 2,
            },
            "expected_metrics": {
                "activation_rate": 0.5,
                "support_tickets_per_user": 1.5,
                "churn_rate": 0.5,
            },
            "tolerance": 0.000001,
            "independent_formula": "counts divided directly by users on one declared row",
        },
        "acceptance_metric": {
            "metric_id": profile["acceptance_metric"],
            "direction": profile["direction"],
            "practical_improvement": 0.1,
            "tolerance": 0.000001,
            "capacity_metric": "reviewed_users",
            "max_capacity": 4,
            "evaluation_policy": "candidate_must_meet_target_without_new_blockers",
        },
        "complexity_budget": {
            "max_new_runtime_dependencies": 1,
            "max_runtime_seconds": 30,
            "max_config_parameters": 8,
            "max_implementation_hours": 12,
            "allowed_gain_dimensions": [
                "decision_utility",
                "reliability",
                "runtime",
                "maintainability",
            ],
            "fallback_action": "retain_baseline",
            "stop_rule": "do_not_implement_complex_candidate_without_practical_gain",
        },
        "created_before_implementation": True,
    }


def write_sample_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    data_builder = load_data_builder()
    data_inputs = data_builder.write_sample_inputs(root_path / "data-inputs")
    upstream = data_builder.build_data_contract_package(
        upstream_brief_package=data_inputs["upstream_brief_package"],
        data_contract_path=data_inputs["data_contract_path"],
        dataset_manifest_path=data_inputs["dataset_manifest_path"],
        source_root=data_inputs["source_root"],
        output_dir=root_path / "upstream-data-package",
    )
    state = read_json(upstream["state_path"])
    baseline_spec_path = write_json(root_path / "baseline_spec.json", default_baseline_spec(state))
    return {
        "upstream_data_package": upstream["output_dir"],
        "baseline_spec_path": baseline_spec_path,
    }


def validate_upstream_data_package(
    package: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]], list[str], dict[str, Any]]:
    required = {
        "capstone_state.json",
        "data_audit.json",
        "data_contract.json",
        "public_data_sample.csv",
        "data_package_manifest.json",
    }
    missing = sorted(name for name in required if not (package / name).is_file())
    if missing:
        return (
            {},
            {},
            [],
            [],
            check(
                "upstream_data_package_is_ready_and_untampered",
                False,
                observed={"missing": missing},
                expected=sorted(required),
                message="Baseline work starts from a passing checksum-verified data package.",
            ),
        )
    state = read_json(package / "capstone_state.json")
    audit = read_json(package / "data_audit.json")
    contract = read_json(package / "data_contract.json")
    manifest = read_json(package / "data_package_manifest.json")
    rows, fields = read_csv(package / "public_data_sample.csv")
    errors: list[dict[str, Any]] = []
    output_entries = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    for key, filename in (
        ("capstone_state", "capstone_state.json"),
        ("data_audit", "data_audit.json"),
        ("data_contract", "data_contract.json"),
        ("public_data_sample", "public_data_sample.csv"),
    ):
        expected = (output_entries.get(key) or {}).get("sha256")
        actual = sha256_file(package / filename)
        if expected != actual:
            errors.append(
                {"field": f"outputs.{key}.sha256", "expected": expected, "actual": actual}
            )
    if manifest.get("valid") is not True or manifest.get("status") != "data_ready":
        errors.append({"field": "data_package_manifest", "reason": "not data_ready"})
    if manifest.get("raw_sources_copied") is not False:
        errors.append({"field": "raw_sources_copied", "expected": False})
    if audit.get("valid") is not True or audit.get("status") != "data_ready":
        errors.append({"field": "data_audit", "reason": "not data_ready"})
    if state.get("current_stage") != "data_contract" or state.get("stage_status") != "data_ready":
        errors.append(
            {
                "field": "capstone_state.stage",
                "observed": [state.get("current_stage"), state.get("stage_status")],
            }
        )
    project_ids = {
        state.get("project_id"),
        audit.get("project_id"),
        contract.get("project_id"),
        manifest.get("project_id"),
    }
    contract_ids = {
        state.get("data_contract_id"),
        audit.get("contract_id"),
        contract.get("contract_id"),
        manifest.get("contract_id"),
    }
    if len(project_ids) != 1:
        errors.append(
            {"field": "project_id", "observed": sorted(str(item) for item in project_ids)}
        )
    if len(contract_ids) != 1:
        errors.append(
            {"field": "contract_id", "observed": sorted(str(item) for item in contract_ids)}
        )
    return (
        state,
        contract,
        rows,
        fields,
        check(
            "upstream_data_package_is_ready_and_untampered",
            not errors,
            observed={
                "project_id": state.get("project_id"),
                "contract_id": state.get("data_contract_id"),
                "errors": errors,
            },
            expected="passing data audit, matching IDs and exact hashes for required inputs",
            message="Changed data evidence invalidates the baseline and every later stage.",
        ),
    )


def validate_spec_structure(spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        errors.append({"field": "baseline_spec", "missing": missing})
    for field in ("baseline_id", "project_id", "contract_id", "decision_question"):
        if not non_empty_text(spec.get(field)):
            errors.append({"field": field, "reason": "non-empty text required"})
    if spec.get("project_id") != state.get("project_id"):
        errors.append({"field": "project_id", "reason": "upstream mismatch"})
    if spec.get("contract_id") != state.get("data_contract_id"):
        errors.append({"field": "contract_id", "reason": "upstream mismatch"})
    if spec.get("decision_question") != state.get("decision"):
        errors.append({"field": "decision_question", "reason": "upstream mismatch"})
    input_contract = spec.get("input_contract")
    if not isinstance(input_contract, dict):
        errors.append({"field": "input_contract", "reason": "object required"})
    else:
        if input_contract.get("path") != "public_data_sample.csv":
            errors.append({"field": "input_contract.path", "reason": "aggregate sample required"})
        if input_contract.get("publication_class") != "aggregated":
            errors.append({"field": "input_contract.publication_class", "expected": "aggregated"})
        if input_contract.get("grain") != ["as_of_week", "segment_id"]:
            errors.append({"field": "input_contract.grain", "reason": "unexpected grain"})
        if input_contract.get("required_fields") != list(PUBLIC_SAMPLE_FIELDS):
            errors.append({"field": "input_contract.required_fields", "reason": "field drift"})
    return check(
        "baseline_spec_matches_decision_and_data_contract",
        not errors,
        observed={"baseline_id": spec.get("baseline_id"), "errors": errors},
        expected="complete spec tied to the same project, decision and aggregate data contract",
        message="A baseline is part of the decision contract, not an exploratory afterthought.",
    )


def normalize_public_sample(
    rows: list[dict[str, str]], fields: list[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    if fields != list(PUBLIC_SAMPLE_FIELDS):
        errors.append(
            {"field": "columns", "actual": fields, "expected": list(PUBLIC_SAMPLE_FIELDS)}
        )
    grain_seen: set[tuple[str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        grain = (row.get("as_of_week", ""), row.get("segment_id", ""))
        if not all(grain) or grain in grain_seen:
            errors.append({"row": row_number, "field": "grain", "value": grain})
        grain_seen.add(grain)
        try:
            users = int(row.get("users", ""))
            activated = int(row.get("activated_users", ""))
            tickets = int(row.get("support_ticket_count", ""))
            churned = int(row.get("churned_users", ""))
            published_activation = float(row.get("activation_rate", ""))
        except ValueError:
            errors.append({"row": row_number, "field": "numeric", "reason": "invalid value"})
            continue
        if users <= 0 or not 0 <= activated <= users or not 0 <= churned <= users or tickets < 0:
            errors.append({"row": row_number, "field": "counts", "reason": "invalid bounds"})
            continue
        activation_rate = activated / users
        if abs(activation_rate - published_activation) > 0.000001:
            errors.append(
                {
                    "row": row_number,
                    "field": "activation_rate",
                    "published": published_activation,
                    "recomputed": activation_rate,
                }
            )
        normalized.append(
            {
                "as_of_week": grain[0],
                "segment_id": grain[1],
                "users": users,
                "activated_users": activated,
                "activation_rate": round(activation_rate, 6),
                "support_ticket_count": tickets,
                "support_tickets_per_user": round(tickets / users, 6),
                "churned_users": churned,
                "churn_rate": round(churned / users, 6),
            }
        )
    restricted_names = {"user_id", "ticket_id", "email", "phone", "name"}
    leaked = sorted(restricted_names & set(fields))
    if leaked:
        errors.append({"field": "restricted_columns", "observed": leaked})
    return normalized, check(
        "aggregate_input_has_valid_grain_counts_and_rates",
        bool(normalized) and not errors,
        observed={"rows": len(normalized), "errors": errors},
        expected="unique week-segment rows, bounded counts and independently reconciled rates",
        message="Even an approved public sample must be rechecked before it becomes evidence.",
    )


def validate_route_profile(spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    route = state.get("route")
    variant = state.get("route_variant")
    expected = ROUTE_BASELINE_PROFILES.get((route, variant))
    policy = spec.get("baseline_policy")
    acceptance = spec.get("acceptance_metric")
    errors: list[dict[str, Any]] = []
    if expected is None:
        errors.append({"field": "route/variant", "observed": [route, variant]})
        expected = {}
    if spec.get("route") != route or spec.get("route_variant") != variant:
        errors.append(
            {"field": "spec.route", "observed": [spec.get("route"), spec.get("route_variant")]}
        )
    if not isinstance(policy, dict) or not isinstance(acceptance, dict):
        errors.append({"field": "baseline_policy/acceptance_metric", "reason": "objects required"})
    else:
        if policy.get("baseline_kind") != expected.get("baseline_kind"):
            errors.append({"field": "baseline_kind", "expected": expected.get("baseline_kind")})
        if policy.get("claim_boundary") != expected.get("claim_boundary"):
            errors.append({"field": "claim_boundary", "expected": expected.get("claim_boundary")})
        if policy.get("no_causal_claim") is not True:
            errors.append({"field": "no_causal_claim", "expected": True})
        if acceptance.get("metric_id") != expected.get("acceptance_metric"):
            errors.append(
                {
                    "field": "acceptance_metric.metric_id",
                    "expected": expected.get("acceptance_metric"),
                }
            )
        if acceptance.get("direction") != expected.get("direction"):
            errors.append(
                {"field": "acceptance_metric.direction", "expected": expected.get("direction")}
            )
    return check(
        "route_baseline_is_minimal_and_claim_safe",
        not errors,
        observed={"route": route, "variant": variant, "errors": errors},
        expected=expected,
        message="Each route needs a simple comparator without borrowing a stronger claim.",
    )


def build_baseline_decision(
    spec: dict[str, Any], metrics: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    policy = spec.get("baseline_policy") if isinstance(spec.get("baseline_policy"), dict) else {}
    errors: list[dict[str, Any]] = []
    expected_policy = {
        "ranking_metric": "churn_rate",
        "ranking_direction": "maximize",
        "tie_breakers": ["support_tickets_per_user", "segment_id"],
        "max_selected_segments": 1,
        "action_on_selection": "targeted_manual_review",
        "fallback_action": "no_action",
    }
    for field, expected in expected_policy.items():
        if policy.get(field) != expected:
            errors.append({"field": field, "observed": policy.get(field), "expected": expected})
    ranked = sorted(
        metrics,
        key=lambda row: (
            -float(row["churn_rate"]),
            -float(row["support_tickets_per_user"]),
            str(row["segment_id"]),
        ),
    )
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
        row["selected"] = str(rank == 1).lower()
    selected = ranked[:1]
    total_churned = sum(int(row["churned_users"]) for row in ranked)
    captured = sum(int(row["churned_users"]) for row in selected)
    reviewed_users = sum(int(row["users"]) for row in selected)
    captured_recall = captured / total_churned if total_churned else 0.0
    decision = {
        "baseline_id": spec.get("baseline_id"),
        "decision_question": spec.get("decision_question"),
        "selected_action": policy.get("action_on_selection")
        if selected
        else policy.get("fallback_action"),
        "selected_segments": [row["segment_id"] for row in selected],
        "ranking_metric": policy.get("ranking_metric"),
        "ranking_direction": policy.get("ranking_direction"),
        "observed_evidence": {
            "total_churned_users": total_churned,
            "captured_churned_users": captured,
            "captured_churn_recall": round(captured_recall, 6),
            "reviewed_users": reviewed_users,
        },
        "claim_boundary": policy.get("claim_boundary"),
        "causal_effect_claimed": False,
        "recommendation_policy": "retain_baseline_until_candidate_meets_predeclared_gate",
    }
    if not selected:
        errors.append({"field": "selected_segments", "reason": "no eligible segment"})
    return (
        decision,
        check(
            "decision_rule_is_deterministic_and_decision_relevant",
            not errors,
            observed={"selected_segments": decision["selected_segments"], "errors": errors},
            expected=expected_policy,
            message=(
                "The baseline must produce a reproducible action, not only a descriptive table."
            ),
        ),
        ranked,
    )


def build_manual_reconciliation(
    spec: dict[str, Any], metrics: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manual = spec.get("manual_reconciliation")
    if not isinstance(manual, dict):
        return [], check(
            "manual_reconciliation_matches_tiny_slice",
            False,
            observed={"errors": [{"field": "manual_reconciliation", "reason": "object required"}]},
            expected="one declared slice with independent inputs, formulas and tolerance",
            message="A manual cross-check must be independent and inspectable.",
        )
    slice_spec = manual.get("slice") if isinstance(manual.get("slice"), dict) else {}
    selected = next(
        (
            row
            for row in metrics
            if row.get("as_of_week") == slice_spec.get("as_of_week")
            and row.get("segment_id") == slice_spec.get("segment_id")
        ),
        None,
    )
    tolerance = manual.get("tolerance")
    errors: list[dict[str, Any]] = []
    if selected is None:
        errors.append({"field": "slice", "reason": "not found"})
    if not isinstance(tolerance, (int, float)) or not 0 < tolerance <= 0.01:
        errors.append({"field": "tolerance", "observed": tolerance})
        tolerance = 0.0
    rows: list[dict[str, Any]] = []
    expected_inputs = (
        manual.get("expected_inputs") if isinstance(manual.get("expected_inputs"), dict) else {}
    )
    expected_metrics = (
        manual.get("expected_metrics") if isinstance(manual.get("expected_metrics"), dict) else {}
    )
    formulas = {
        "activation_rate": "activated_users / users",
        "support_tickets_per_user": "support_ticket_count / users",
        "churn_rate": "churned_users / users",
    }
    if selected is not None:
        for metric in ("users", "activated_users", "support_ticket_count", "churned_users"):
            expected = expected_inputs.get(metric)
            observed = selected.get(metric)
            valid = expected == observed
            rows.append(
                {
                    "metric": metric,
                    "formula": "direct input readback",
                    "expected": expected,
                    "observed": observed,
                    "delta": 0 if valid else "mismatch",
                    "tolerance": 0,
                    "valid": str(valid).lower(),
                }
            )
            if not valid:
                errors.append(
                    {
                        "field": f"expected_inputs.{metric}",
                        "expected": expected,
                        "observed": observed,
                    }
                )
        users = int(selected["users"])
        manual_values = {
            "activation_rate": int(selected["activated_users"]) / users,
            "support_tickets_per_user": int(selected["support_ticket_count"]) / users,
            "churn_rate": int(selected["churned_users"]) / users,
        }
        for metric, observed in manual_values.items():
            expected = expected_metrics.get(metric)
            delta = abs(observed - expected) if isinstance(expected, (int, float)) else None
            valid = delta is not None and delta <= tolerance
            rows.append(
                {
                    "metric": metric,
                    "formula": formulas[metric],
                    "expected": expected,
                    "observed": round(observed, 6),
                    "delta": round(delta, 6) if delta is not None else "missing",
                    "tolerance": tolerance,
                    "valid": str(valid).lower(),
                }
            )
            if not valid:
                errors.append(
                    {
                        "field": f"expected_metrics.{metric}",
                        "expected": expected,
                        "observed": observed,
                    }
                )
    if not non_empty_text(manual.get("independent_formula")):
        errors.append({"field": "independent_formula", "reason": "required"})
    return rows, check(
        "manual_reconciliation_matches_tiny_slice",
        not errors and bool(rows),
        observed={"slice": slice_spec, "rows": len(rows), "errors": errors},
        expected="declared counts and three independently recomputed rates within tolerance",
        message="A second arithmetic path catches denominator and aggregation mistakes.",
    )


def build_acceptance_gate(
    spec: dict[str, Any], decision: dict[str, Any], profile: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    acceptance = spec.get("acceptance_metric")
    errors: list[dict[str, Any]] = []
    if not isinstance(acceptance, dict):
        acceptance = {}
        errors.append({"field": "acceptance_metric", "reason": "object required"})
    baseline_value = (decision.get("observed_evidence") or {}).get("captured_churn_recall")
    improvement = acceptance.get("practical_improvement")
    tolerance = acceptance.get("tolerance")
    max_capacity = acceptance.get("max_capacity")
    if acceptance.get("metric_id") != profile.get("acceptance_metric"):
        errors.append({"field": "metric_id", "expected": profile.get("acceptance_metric")})
    if acceptance.get("direction") != profile.get("direction"):
        errors.append({"field": "direction", "expected": profile.get("direction")})
    if not isinstance(improvement, (int, float)) or not 0 < improvement <= 0.5:
        errors.append({"field": "practical_improvement", "observed": improvement})
        improvement = 0.0
    if not isinstance(tolerance, (int, float)) or not 0 < tolerance <= 0.01:
        errors.append({"field": "tolerance", "observed": tolerance})
        tolerance = 0.0
    if not isinstance(max_capacity, int) or max_capacity <= 0:
        errors.append({"field": "max_capacity", "observed": max_capacity})
    if acceptance.get("capacity_metric") != "reviewed_users":
        errors.append({"field": "capacity_metric", "expected": "reviewed_users"})
    if acceptance.get("evaluation_policy") != "candidate_must_meet_target_without_new_blockers":
        errors.append({"field": "evaluation_policy", "reason": "unexpected policy"})
    if not isinstance(baseline_value, (int, float)):
        errors.append({"field": "baseline_value", "reason": "cannot derive"})
        baseline_value = 0.0
    if profile.get("direction") == "maximize":
        target = baseline_value + improvement
        operator = ">="
    else:
        target = baseline_value - improvement
        operator = "<="
    gate = {
        "metric_id": acceptance.get("metric_id"),
        "direction": acceptance.get("direction"),
        "baseline_value": round(baseline_value, 6),
        "practical_improvement": improvement,
        "candidate_threshold": round(target, 6),
        "threshold_operator": operator,
        "tolerance": tolerance,
        "capacity_metric": acceptance.get("capacity_metric"),
        "max_capacity": max_capacity,
        "candidate_value": None,
        "candidate_pass": None,
        "status": "predeclared_for_implementation",
        "fallback_action": "retain_baseline",
    }
    return gate, check(
        "acceptance_metric_threshold_and_tolerance_are_predeclared",
        not errors,
        observed={"gate": gate, "errors": errors},
        expected="metric, direction, practical delta, tolerance and capacity before implementation",
        message="A complex candidate must beat a frozen useful threshold, not a moving target.",
    )


def validate_complexity_budget(spec: dict[str, Any]) -> dict[str, Any]:
    budget = spec.get("complexity_budget")
    errors: list[dict[str, Any]] = []
    if not isinstance(budget, dict):
        budget = {}
        errors.append({"field": "complexity_budget", "reason": "object required"})
    limits = {
        "max_new_runtime_dependencies": (0, 3),
        "max_runtime_seconds": (1, 300),
        "max_config_parameters": (0, 20),
        "max_implementation_hours": (1, 12),
    }
    for field, (minimum, maximum) in limits.items():
        value = budget.get(field)
        if not isinstance(value, int) or not minimum <= value <= maximum:
            errors.append({"field": field, "observed": value, "range": [minimum, maximum]})
    allowed = budget.get("allowed_gain_dimensions")
    valid_dimensions = {"decision_utility", "reliability", "runtime", "maintainability"}
    if not isinstance(allowed, list) or not allowed or not set(allowed) <= valid_dimensions:
        errors.append({"field": "allowed_gain_dimensions", "observed": allowed})
    if budget.get("fallback_action") != "retain_baseline":
        errors.append({"field": "fallback_action", "expected": "retain_baseline"})
    if budget.get("stop_rule") != "do_not_implement_complex_candidate_without_practical_gain":
        errors.append({"field": "stop_rule", "reason": "baseline retention must be explicit"})
    return check(
        "complexity_budget_limits_candidate_cost_and_has_a_stop_rule",
        not errors,
        observed={"budget": budget, "errors": errors},
        expected="bounded dependencies/runtime/config/hours and explicit retain-baseline fallback",
        message="Complexity is admitted only in exchange for a declared practical gain.",
    )


def nested_forbidden_fields(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in FORBIDDEN_RESULT_FIELDS:
                found.append(path)
            found.extend(nested_forbidden_fields(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(nested_forbidden_fields(nested, f"{prefix}[{index}]"))
    return found


def validate_stage_isolation(
    spec: dict[str, Any], state: dict[str, Any], package_manifest: dict[str, Any]
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if spec.get("created_before_implementation") is not True:
        errors.append({"field": "created_before_implementation", "expected": True})
    forbidden = nested_forbidden_fields(spec)
    if forbidden:
        errors.append({"field": "future_results", "paths": forbidden})
    for field in ("implementation_id", "verification_id", "review_id", "defense_id"):
        if state.get(field) is not None:
            errors.append({"field": f"capstone_state.{field}", "observed": state.get(field)})
    if package_manifest.get("raw_sources_copied") is not False:
        errors.append({"field": "raw_sources_copied", "expected": False})
    return check(
        "baseline_is_isolated_from_implementation_and_future_results",
        not errors,
        observed={"errors": errors},
        expected="aggregate input only, no candidate result and no later-stage identifiers",
        message="The comparator must be frozen before the complex candidate is observed.",
    )


def audit_baseline(
    *, upstream_data_package: str | Path, baseline_spec_path: str | Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    package = Path(upstream_data_package)
    spec = read_json(baseline_spec_path)
    state, _contract, raw_rows, fields, upstream_check = validate_upstream_data_package(package)
    package_manifest = (
        read_json(package / "data_package_manifest.json")
        if (package / "data_package_manifest.json").is_file()
        else {}
    )
    metrics, aggregate_check = normalize_public_sample(raw_rows, fields)
    route = str(state.get("route"))
    variant = str(state.get("route_variant"))
    profile = ROUTE_BASELINE_PROFILES.get((route, variant), {})
    decision, decision_check, ranked_metrics = build_baseline_decision(spec, metrics)
    manual_rows, manual_check = build_manual_reconciliation(spec, metrics)
    acceptance_gate, acceptance_check = build_acceptance_gate(spec, decision, profile)
    checks = [
        upstream_check,
        validate_spec_structure(spec, state),
        aggregate_check,
        validate_route_profile(spec, state),
        decision_check,
        manual_check,
        acceptance_check,
        validate_complexity_budget(spec),
        validate_stage_isolation(spec, state, package_manifest),
    ]
    blocking_errors = [
        item["id"] for item in checks if not item["valid"] and item["severity"] == "block"
    ]
    upstream_warnings = state.get("warnings", []) if isinstance(state.get("warnings"), list) else []
    warnings = list(
        dict.fromkeys(
            upstream_warnings
            + ["tiny_baseline_sample_expected", "observed_priority_is_not_intervention_effect"]
        )
    )
    valid = not blocking_errors
    report = {
        "version": BASELINE_VERSION,
        "baseline_id": spec.get("baseline_id"),
        "project_id": spec.get("project_id"),
        "contract_id": spec.get("contract_id"),
        "status": "baseline_ready" if valid else "baseline_block",
        "valid": valid,
        "checks": checks,
        "summary": {
            "blocking_errors": blocking_errors,
            "warnings": warnings,
            "check_count": len(checks),
            "metric_rows": len(ranked_metrics),
            "selected_segments": decision.get("selected_segments", []),
            "baseline_value": acceptance_gate.get("baseline_value"),
            "candidate_threshold": acceptance_gate.get("candidate_threshold"),
            "next_stage": "implementation" if valid else "baseline",
        },
    }
    result = {
        "spec": spec,
        "state": state,
        "metrics": ranked_metrics,
        "decision": decision,
        "manual_rows": manual_rows,
        "acceptance_gate": acceptance_gate,
        "complexity_budget": spec.get("complexity_budget", {}),
    }
    return report, result, package_manifest


def build_baseline_package(
    *,
    upstream_data_package: str | Path,
    baseline_spec_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report, result, _upstream_manifest = audit_baseline(
        upstream_data_package=upstream_data_package,
        baseline_spec_path=baseline_spec_path,
    )
    generated = {
        "baseline_spec": write_json(output / "baseline_spec.json", result["spec"]),
        "baseline_report": write_json(output / "baseline_report.json", report),
        "baseline_metrics": write_csv(
            output / "baseline_metrics.csv", result["metrics"], list(METRIC_FIELDS)
        ),
        "baseline_decision": write_json(output / "baseline_decision.json", result["decision"]),
        "manual_reconciliation": write_csv(
            output / "manual_reconciliation.csv",
            result["manual_rows"],
            ["metric", "formula", "expected", "observed", "delta", "tolerance", "valid"],
        ),
        "acceptance_gate": write_json(output / "acceptance_gate.json", result["acceptance_gate"]),
        "complexity_budget": write_json(
            output / "complexity_budget.json", result["complexity_budget"]
        ),
    }
    state = dict(result["state"])
    old_warnings = state.get("warnings", []) if isinstance(state.get("warnings"), list) else []
    state.update(
        {
            "baseline_id": result["spec"].get("baseline_id"),
            "current_stage": "baseline",
            "stage_status": report["status"],
            "open_blockers": report["summary"]["blocking_errors"],
            "warnings": list(dict.fromkeys(old_warnings + report["summary"]["warnings"])),
            "artifact_inventory": list(
                dict.fromkeys(
                    state.get("artifact_inventory", []) + [path.name for path in generated.values()]
                )
            ),
            "evidence_links": [
                {"stage": "baseline", "path": "baseline_report.json"},
                {"stage": "baseline", "path": "baseline_decision.json"},
                {"stage": "baseline", "path": "manual_reconciliation.csv"},
                {"stage": "baseline", "path": "acceptance_gate.json"},
            ],
            "input_checksums": {
                **state.get("input_checksums", {}),
                Path(baseline_spec_path).name: sha256_file(baseline_spec_path),
                "upstream_capstone_state.json": sha256_file(
                    Path(upstream_data_package) / "capstone_state.json"
                ),
                "upstream_public_data_sample.csv": sha256_file(
                    Path(upstream_data_package) / "public_data_sample.csv"
                ),
            },
            "output_checksums": {path.name: sha256_file(path) for path in generated.values()},
            "updated_at": state.get("updated_at"),
        }
    )
    state_path = write_json(output / "capstone_state.json", state)
    generated["capstone_state"] = state_path
    manifest = {
        "version": BASELINE_VERSION,
        "project_id": result["spec"].get("project_id"),
        "contract_id": result["spec"].get("contract_id"),
        "baseline_id": result["spec"].get("baseline_id"),
        "status": report["status"],
        "valid": report["valid"],
        "hash_algorithm": "sha256",
        "renderer_used": "capstone_baseline_gate",
        "raw_sources_copied": False,
        "candidate_results_observed": False,
        "inputs": {
            "upstream_data_manifest": {
                "path": "upstream-data-package/data_package_manifest.json",
                "sha256": sha256_file(Path(upstream_data_package) / "data_package_manifest.json"),
            },
            "upstream_public_data_sample": {
                "path": "upstream-data-package/public_data_sample.csv",
                "sha256": sha256_file(Path(upstream_data_package) / "public_data_sample.csv"),
            },
            "baseline_spec": {
                "path": Path(baseline_spec_path).name,
                "sha256": sha256_file(baseline_spec_path),
            },
        },
        "outputs": {
            name: {"path": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for name, path in generated.items()
        },
    }
    manifest_path = write_json(output / "baseline_manifest.json", manifest)
    return {
        "report": report,
        "output_dir": output,
        "state_path": state_path,
        "manifest_path": manifest_path,
        "decision_path": generated["baseline_decision"],
        "acceptance_path": generated["acceptance_gate"],
        "manual_path": generated["manual_reconciliation"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze and audit the simplest decision-relevant capstone baseline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--upstream-data-package", type=Path, help="Passing data package from lesson 18/02."
    )
    parser.add_argument("--baseline-spec", type=Path, help="Path to baseline_spec.json.")
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Directory for the baseline package."
    )
    parser.add_argument(
        "--write-example", type=Path, help="Write deterministic upstream data and spec here."
    )
    parser.add_argument(
        "--fail-on-invalid",
        action="store_true",
        help="Return exit code 1 for a blocked baseline.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    upstream = parsed.upstream_data_package
    baseline_spec = parsed.baseline_spec
    if parsed.write_example:
        sample = write_sample_inputs(parsed.write_example)
        upstream = upstream or sample["upstream_data_package"]
        baseline_spec = baseline_spec or sample["baseline_spec_path"]
    missing = [
        name
        for name, value in (
            ("--upstream-data-package", upstream),
            ("--baseline-spec", baseline_spec),
        )
        if value is None
    ]
    if missing:
        print(
            json.dumps(
                {
                    "version": BASELINE_VERSION,
                    "status": "system_error",
                    "valid": False,
                    "error": {"code": "missing_inputs", "message": ", ".join(missing)},
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    try:
        result = build_baseline_package(
            upstream_data_package=upstream,
            baseline_spec_path=baseline_spec,
            output_dir=parsed.output_dir,
        )
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, BaselineGateError) as error:
        print(
            json.dumps(
                {
                    "version": BASELINE_VERSION,
                    "status": "system_error",
                    "valid": False,
                    "error": {"code": "invalid_input", "message": str(error)},
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    report = result["report"]
    payload = {
        "status": report["status"],
        "valid": report["valid"],
        "project_id": report["project_id"],
        "baseline_id": report["baseline_id"],
        "selected_segments": report["summary"]["selected_segments"],
        "baseline_value": report["summary"]["baseline_value"],
        "candidate_threshold": report["summary"]["candidate_threshold"],
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
