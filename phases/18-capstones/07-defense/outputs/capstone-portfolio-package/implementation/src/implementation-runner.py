from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

IMPLEMENTATION_VERSION = "1.0.0"
BASELINE_METRIC_FIELDS = (
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
CANDIDATE_METRIC_FIELDS = (
    "as_of_week",
    "segment_id",
    "users",
    "churned_users",
    "churn_rate",
    "activation_gap",
    "support_tickets_per_user",
    "churn_component",
    "activation_gap_component",
    "support_load_component",
    "candidate_score",
    "candidate_rank",
    "candidate_selected",
)
REQUIRED_SPEC_FIELDS = {
    "implementation_id",
    "project_id",
    "contract_id",
    "baseline_id",
    "version",
    "route",
    "route_variant",
    "route_adapter",
    "frozen_config",
    "candidate_policy",
    "evidence_claims",
    "reproducible_command",
    "environment",
    "created_before_candidate_run",
}
FORBIDDEN_PREDECLARATION_FIELDS = {
    "candidate_value",
    "candidate_pass",
    "selected_method",
    "final_score",
    "test_score",
    "verification_status",
}
ROUTE_ADAPTER_PROFILES: dict[tuple[str, str], dict[str, str]] = {
    ("core_analytics", "standard"): {
        "adapter_kind": "weighted_segment_priority",
        "primary_output": "candidate_decision.json",
        "claim_boundary": "descriptive_observed_priority_not_intervention_effect",
    },
    ("product_experiments", "standard"): {
        "adapter_kind": "randomized_assignment_analysis",
        "primary_output": "candidate_decision.json",
        "claim_boundary": "experimental_claim_only_after_design_and_srm_gates",
    },
    ("data_analytics_engineering", "standard"): {
        "adapter_kind": "contracted_mart_build",
        "primary_output": "candidate_decision.json",
        "claim_boundary": "correctness_lineage_freshness_performance_not_user_impact",
    },
    ("decision_science", "causal"): {
        "adapter_kind": "identified_estimand_workflow",
        "primary_output": "candidate_decision.json",
        "claim_boundary": "causal_estimand_with_declared_identification_assumptions",
    },
    ("decision_science", "forecast"): {
        "adapter_kind": "rolling_origin_forecast_workflow",
        "primary_output": "candidate_decision.json",
        "claim_boundary": "forecast_accuracy_within_declared_origin_and_horizon",
    },
    ("machine_learning", "baseline"): {
        "adapter_kind": "locked_prediction_pipeline",
        "primary_output": "candidate_decision.json",
        "claim_boundary": "predictive_priority_not_intervention_effect",
    },
    ("machine_learning", "strong_model"): {
        "adapter_kind": "tracked_tuning_and_prediction_pipeline",
        "primary_output": "candidate_decision.json",
        "claim_boundary": "predictive_priority_not_intervention_effect",
    },
    ("delivery_product", "standard"): {
        "adapter_kind": "verified_evidence_delivery_workflow",
        "primary_output": "candidate_decision.json",
        "claim_boundary": "delivery_quality_without_upstream_claim_amplification",
    },
}


class ImplementationError(ValueError):
    """Raised when implementation inputs cannot be parsed."""


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
        raise ImplementationError(f"{source} must contain a JSON object")
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


def load_baseline_builder():
    artifact = (
        Path(__file__).resolve().parents[2]
        / "03-baseline"
        / "outputs"
        / "capstone_baseline_gate.py"
    )
    spec = importlib.util.spec_from_file_location("capstone_baseline_gate", artifact)
    if spec is None or spec.loader is None:
        raise ImplementationError(f"cannot load upstream baseline builder: {artifact}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def route_adapter_profile(route: str, variant: str) -> dict[str, str]:
    profile = ROUTE_ADAPTER_PROFILES.get((route, variant))
    if profile is None:
        raise ImplementationError(f"unsupported route/variant: {route}/{variant}")
    return dict(profile)


def default_implementation_spec(state: dict[str, Any]) -> dict[str, Any]:
    route = str(state.get("route"))
    variant = str(state.get("route_variant"))
    profile = route_adapter_profile(route, variant)
    return {
        "implementation_id": "weekly-retention-core-implementation-v1",
        "project_id": state.get("project_id"),
        "contract_id": state.get("data_contract_id"),
        "baseline_id": state.get("baseline_id"),
        "version": IMPLEMENTATION_VERSION,
        "route": route,
        "route_variant": variant,
        "route_adapter": {
            "adapter_id": "core-weighted-segment-priority-v1",
            "adapter_kind": profile["adapter_kind"],
            "input_path": "baseline_metrics.csv",
            "output_grain": ["as_of_week", "segment_id"],
            "primary_output": profile["primary_output"],
            "claim_boundary": profile["claim_boundary"],
        },
        "frozen_config": {
            "score_weights": {
                "churn_rate": 0.6,
                "activation_gap": 0.2,
                "support_load": 0.2,
            },
            "normalization": "min_max_zero_when_constant",
            "ranking_direction": "maximize",
            "tie_breakers": ["churn_rate", "segment_id"],
            "max_selected_segments": 1,
            "seed_policy": "not_required_deterministic_adapter",
        },
        "candidate_policy": {
            "metric_id": "captured_churn_recall",
            "threshold_source": "acceptance_gate.json",
            "capacity_source": "acceptance_gate.json",
            "retain_baseline_when_gate_fails": True,
            "no_causal_claim": True,
            "evaluation_scope": "aggregate_public_sample_only",
        },
        "evidence_claims": [
            {
                "claim_id": "implementation-claim-01",
                "claim_text": "The predeclared weighted adapter ranks high_touch first.",
                "claim_type": "descriptive",
                "evidence_path": "candidate_metrics.csv",
                "evidence_fields": ["segment_id", "candidate_score", "candidate_rank"],
                "limitation": "Ranking is based on two aggregate reference segments.",
            },
            {
                "claim_id": "implementation-claim-02",
                "claim_text": "The candidate does not clear the frozen practical threshold.",
                "claim_type": "descriptive",
                "evidence_path": "candidate_acceptance.json",
                "evidence_fields": ["candidate_value", "candidate_threshold", "candidate_pass"],
                "limitation": "The tiny profile is behavioral evidence, not a production estimate.",
            },
            {
                "claim_id": "implementation-claim-03",
                "claim_text": "The retain-baseline stop rule selects the baseline method.",
                "claim_type": "descriptive",
                "evidence_path": "candidate_decision.json",
                "evidence_fields": ["selected_method", "decision_status"],
                "limitation": "No causal effect of manual review is claimed.",
            },
        ],
        "reproducible_command": (
            "uv run --locked python "
            "phases/18-capstones/04-implementation/outputs/"
            "capstone_route_implementation.py "
            "--upstream-baseline-package path/to/baseline-package "
            "--implementation-spec path/to/implementation_spec.json "
            "--output-dir path/to/implementation-package --fail-on-invalid"
        ),
        "environment": {
            "manager": "uv",
            "lock_file": "uv.lock",
            "standard_library_only": True,
            "new_runtime_dependencies": [],
            "runtime_check": "behavioral_test_timeout",
        },
        "created_before_candidate_run": True,
    }


def write_sample_inputs(root: str | Path) -> dict[str, Path]:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    baseline_builder = load_baseline_builder()
    baseline_inputs = baseline_builder.write_sample_inputs(root_path / "baseline-inputs")
    upstream = baseline_builder.build_baseline_package(
        upstream_data_package=baseline_inputs["upstream_data_package"],
        baseline_spec_path=baseline_inputs["baseline_spec_path"],
        output_dir=root_path / "upstream-baseline-package",
    )
    state = read_json(upstream["state_path"])
    implementation_spec_path = write_json(
        root_path / "implementation_spec.json", default_implementation_spec(state)
    )
    return {
        "upstream_baseline_package": upstream["output_dir"],
        "implementation_spec_path": implementation_spec_path,
    }


def validate_upstream_baseline_package(
    package: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, str]],
    list[str],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    required = {
        "capstone_state.json",
        "baseline_report.json",
        "baseline_metrics.csv",
        "baseline_decision.json",
        "acceptance_gate.json",
        "complexity_budget.json",
        "baseline_manifest.json",
    }
    missing = sorted(name for name in required if not (package / name).is_file())
    if missing:
        return (
            {},
            [],
            [],
            {},
            {},
            check(
                "upstream_baseline_is_ready_immutable_and_untampered",
                False,
                observed={"missing": missing},
                expected=sorted(required),
                message="Implementation starts only from a frozen passing baseline package.",
            ),
        )
    state = read_json(package / "capstone_state.json")
    report = read_json(package / "baseline_report.json")
    read_json(package / "baseline_decision.json")
    acceptance = read_json(package / "acceptance_gate.json")
    complexity = read_json(package / "complexity_budget.json")
    manifest = read_json(package / "baseline_manifest.json")
    metrics, fields = read_csv(package / "baseline_metrics.csv")
    errors: list[dict[str, Any]] = []
    entries = manifest.get("outputs") if isinstance(manifest.get("outputs"), dict) else {}
    for key, filename in (
        ("capstone_state", "capstone_state.json"),
        ("baseline_report", "baseline_report.json"),
        ("baseline_metrics", "baseline_metrics.csv"),
        ("baseline_decision", "baseline_decision.json"),
        ("acceptance_gate", "acceptance_gate.json"),
        ("complexity_budget", "complexity_budget.json"),
    ):
        expected = (entries.get(key) or {}).get("sha256")
        actual = sha256_file(package / filename)
        if expected != actual:
            errors.append(
                {"field": f"outputs.{key}.sha256", "expected": expected, "actual": actual}
            )
    if manifest.get("valid") is not True or manifest.get("status") != "baseline_ready":
        errors.append({"field": "baseline_manifest", "reason": "not baseline_ready"})
    if manifest.get("raw_sources_copied") is not False:
        errors.append({"field": "raw_sources_copied", "expected": False})
    if manifest.get("candidate_results_observed") is not False:
        errors.append({"field": "candidate_results_observed", "expected": False})
    if report.get("valid") is not True or report.get("status") != "baseline_ready":
        errors.append({"field": "baseline_report", "reason": "not baseline_ready"})
    if state.get("current_stage") != "baseline" or state.get("stage_status") != "baseline_ready":
        errors.append(
            {
                "field": "capstone_state.stage",
                "observed": [state.get("current_stage"), state.get("stage_status")],
            }
        )
    if (
        acceptance.get("candidate_value") is not None
        or acceptance.get("candidate_pass") is not None
    ):
        errors.append({"field": "acceptance_gate", "reason": "candidate already observed"})
    identifiers = {
        "project_id": {
            state.get("project_id"),
            report.get("project_id"),
            manifest.get("project_id"),
        },
        "contract_id": {
            state.get("data_contract_id"),
            report.get("contract_id"),
            manifest.get("contract_id"),
        },
        "baseline_id": {
            state.get("baseline_id"),
            report.get("baseline_id"),
            manifest.get("baseline_id"),
        },
    }
    for name, values in identifiers.items():
        if len(values) != 1:
            errors.append({"field": name, "observed": sorted(str(item) for item in values)})
    return (
        state,
        metrics,
        fields,
        acceptance,
        complexity,
        check(
            "upstream_baseline_is_ready_immutable_and_untampered",
            not errors,
            observed={
                "project_id": state.get("project_id"),
                "baseline_id": state.get("baseline_id"),
                "errors": errors,
            },
            expected="passing baseline, frozen candidate gate and exact hashes for all inputs",
            message="An upstream change invalidates the implementation run and its evidence.",
        ),
    )


def validate_spec_structure(spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        errors.append({"field": "implementation_spec", "missing": missing})
    for field in ("implementation_id", "project_id", "contract_id", "baseline_id"):
        if not non_empty_text(spec.get(field)):
            errors.append({"field": field, "reason": "non-empty text required"})
    upstream_fields = {
        "project_id": "project_id",
        "contract_id": "data_contract_id",
        "baseline_id": "baseline_id",
        "route": "route",
        "route_variant": "route_variant",
    }
    for spec_field, state_field in upstream_fields.items():
        if spec.get(spec_field) != state.get(state_field):
            errors.append(
                {
                    "field": spec_field,
                    "spec": spec.get(spec_field),
                    "upstream": state.get(state_field),
                }
            )
    for field in ("route_adapter", "frozen_config", "candidate_policy", "environment"):
        if not isinstance(spec.get(field), dict):
            errors.append({"field": field, "reason": "object required"})
    if not isinstance(spec.get("evidence_claims"), list) or not spec["evidence_claims"]:
        errors.append({"field": "evidence_claims", "reason": "non-empty list required"})
    return check(
        "implementation_spec_matches_frozen_upstream_contracts",
        not errors,
        observed={"implementation_id": spec.get("implementation_id"), "errors": errors},
        expected="same project, contract, baseline, route and complete implementation spec",
        message="Implementation is a consumer of approved upstream contracts.",
    )


def validate_route_adapter(spec: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    route = state.get("route")
    variant = state.get("route_variant")
    expected = ROUTE_ADAPTER_PROFILES.get((route, variant))
    adapter = spec.get("route_adapter")
    errors: list[dict[str, Any]] = []
    if expected is None:
        errors.append({"field": "route/variant", "observed": [route, variant]})
        expected = {}
    if not isinstance(adapter, dict):
        errors.append({"field": "route_adapter", "reason": "object required"})
        adapter = {}
    if adapter.get("adapter_kind") != expected.get("adapter_kind"):
        errors.append({"field": "adapter_kind", "expected": expected.get("adapter_kind")})
    if adapter.get("primary_output") != expected.get("primary_output"):
        errors.append({"field": "primary_output", "expected": expected.get("primary_output")})
    if adapter.get("claim_boundary") != expected.get("claim_boundary"):
        errors.append({"field": "claim_boundary", "expected": expected.get("claim_boundary")})
    if not non_empty_text(adapter.get("adapter_id")):
        errors.append({"field": "adapter_id", "reason": "required"})
    if adapter.get("input_path") != "baseline_metrics.csv":
        errors.append({"field": "input_path", "expected": "baseline_metrics.csv"})
    if adapter.get("output_grain") != ["as_of_week", "segment_id"]:
        errors.append({"field": "output_grain", "reason": "unexpected grain"})
    return check(
        "route_adapter_is_explicit_and_respects_claim_boundary",
        not errors,
        observed={"route": route, "variant": variant, "adapter": adapter, "errors": errors},
        expected=expected,
        message="Route logic stays replaceable without changing the evidence package layer.",
    )


def nested_forbidden_fields(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in FORBIDDEN_PREDECLARATION_FIELDS:
                found.append(path)
            found.extend(nested_forbidden_fields(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(nested_forbidden_fields(nested, f"{prefix}[{index}]"))
    return found


def validate_frozen_config(
    spec: dict[str, Any], complexity_budget: dict[str, Any]
) -> dict[str, Any]:
    config = spec.get("frozen_config")
    policy = spec.get("candidate_policy")
    errors: list[dict[str, Any]] = []
    if not isinstance(config, dict) or not isinstance(policy, dict):
        errors.append({"field": "frozen_config/candidate_policy", "reason": "objects required"})
        config = {}
        policy = {}
    weights = config.get("score_weights")
    expected_weight_keys = {"churn_rate", "activation_gap", "support_load"}
    if not isinstance(weights, dict) or set(weights) != expected_weight_keys:
        errors.append({"field": "score_weights", "expected": sorted(expected_weight_keys)})
        weights = {}
    elif any(not isinstance(value, (int, float)) or value < 0 for value in weights.values()):
        errors.append({"field": "score_weights", "reason": "non-negative numeric values required"})
    elif abs(sum(weights.values()) - 1.0) > 0.000001:
        errors.append({"field": "score_weights", "reason": "weights must sum to one"})
    expected_config = {
        "normalization": "min_max_zero_when_constant",
        "ranking_direction": "maximize",
        "tie_breakers": ["churn_rate", "segment_id"],
        "max_selected_segments": 1,
        "seed_policy": "not_required_deterministic_adapter",
    }
    for field, expected in expected_config.items():
        if config.get(field) != expected:
            errors.append({"field": field, "observed": config.get(field), "expected": expected})
    expected_policy = {
        "metric_id": "captured_churn_recall",
        "threshold_source": "acceptance_gate.json",
        "capacity_source": "acceptance_gate.json",
        "retain_baseline_when_gate_fails": True,
        "no_causal_claim": True,
        "evaluation_scope": "aggregate_public_sample_only",
    }
    for field, expected in expected_policy.items():
        if policy.get(field) != expected:
            errors.append({"field": f"candidate_policy.{field}", "expected": expected})
    forbidden = nested_forbidden_fields(spec)
    if forbidden:
        errors.append({"field": "future_results", "paths": forbidden})
    if spec.get("created_before_candidate_run") is not True:
        errors.append({"field": "created_before_candidate_run", "expected": True})
    parameter_count = len(weights) + len(config.get("tie_breakers", [])) + 2
    max_parameters = complexity_budget.get("max_config_parameters")
    if not isinstance(max_parameters, int) or parameter_count > max_parameters:
        errors.append(
            {
                "field": "config_parameter_count",
                "observed": parameter_count,
                "maximum": max_parameters,
            }
        )
    return check(
        "config_policy_and_threshold_sources_are_frozen_before_run",
        not errors,
        observed={"parameter_count": parameter_count, "errors": errors},
        expected="weights sum to one, deterministic ranking and no observed candidate fields",
        message="Candidate choices are fixed before candidate performance is visible.",
    )


def parse_baseline_metrics(
    rows: list[dict[str, str]], fields: list[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    parsed: list[dict[str, Any]] = []
    if fields != list(BASELINE_METRIC_FIELDS):
        errors.append(
            {"field": "columns", "actual": fields, "expected": list(BASELINE_METRIC_FIELDS)}
        )
    grain_seen: set[tuple[str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        grain = (row.get("as_of_week", ""), row.get("segment_id", ""))
        if not all(grain) or grain in grain_seen:
            errors.append({"row": row_number, "field": "grain", "value": grain})
        grain_seen.add(grain)
        try:
            users = int(row.get("users", ""))
            churned = int(row.get("churned_users", ""))
            churn_rate = float(row.get("churn_rate", ""))
            activation_rate = float(row.get("activation_rate", ""))
            support_load = float(row.get("support_tickets_per_user", ""))
        except ValueError:
            errors.append({"row": row_number, "field": "numeric", "reason": "invalid value"})
            continue
        if (
            users <= 0
            or not 0 <= churned <= users
            or not 0 <= activation_rate <= 1
            or support_load < 0
        ):
            errors.append({"row": row_number, "field": "bounds", "reason": "invalid value"})
            continue
        if abs(churn_rate - churned / users) > 0.000001:
            errors.append({"row": row_number, "field": "churn_rate", "reason": "count mismatch"})
        parsed.append(
            {
                "as_of_week": grain[0],
                "segment_id": grain[1],
                "users": users,
                "churned_users": churned,
                "churn_rate": churn_rate,
                "activation_rate": activation_rate,
                "support_tickets_per_user": support_load,
            }
        )
    return parsed, check(
        "adapter_input_preserves_approved_aggregate_grain_and_metrics",
        bool(parsed) and not errors,
        observed={"rows": len(parsed), "errors": errors},
        expected="exact aggregate baseline schema, unique grain and reconciled churn rate",
        message="The route adapter cannot silently reinterpret its immutable input.",
    )


def min_max(values: list[float]) -> list[float]:
    minimum = min(values)
    maximum = max(values)
    if abs(maximum - minimum) <= 0.000000001:
        return [0.0 for _value in values]
    return [(value - minimum) / (maximum - minimum) for value in values]


def run_core_adapter(
    spec: dict[str, Any], metrics: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    config = spec.get("frozen_config") if isinstance(spec.get("frozen_config"), dict) else {}
    weights = config.get("score_weights") if isinstance(config.get("score_weights"), dict) else {}
    churn_components = min_max([float(row["churn_rate"]) for row in metrics]) if metrics else []
    activation_components = (
        min_max([1.0 - float(row["activation_rate"]) for row in metrics]) if metrics else []
    )
    support_components = (
        min_max([float(row["support_tickets_per_user"]) for row in metrics]) if metrics else []
    )
    candidates: list[dict[str, Any]] = []
    for row, churn_component, activation_component, support_component in zip(
        metrics, churn_components, activation_components, support_components, strict=True
    ):
        score = (
            float(weights.get("churn_rate", 0)) * churn_component
            + float(weights.get("activation_gap", 0)) * activation_component
            + float(weights.get("support_load", 0)) * support_component
        )
        candidates.append(
            {
                "as_of_week": row["as_of_week"],
                "segment_id": row["segment_id"],
                "users": row["users"],
                "churned_users": row["churned_users"],
                "churn_rate": round(float(row["churn_rate"]), 6),
                "activation_gap": round(1.0 - float(row["activation_rate"]), 6),
                "support_tickets_per_user": round(float(row["support_tickets_per_user"]), 6),
                "churn_component": round(churn_component, 6),
                "activation_gap_component": round(activation_component, 6),
                "support_load_component": round(support_component, 6),
                "candidate_score": round(score, 6),
            }
        )
    ranked = sorted(
        candidates,
        key=lambda row: (
            -float(row["candidate_score"]),
            -float(row["churn_rate"]),
            str(row["segment_id"]),
        ),
    )
    maximum_selected = config.get("max_selected_segments", 1)
    for rank, row in enumerate(ranked, start=1):
        row["candidate_rank"] = rank
        row["candidate_selected"] = str(rank <= maximum_selected).lower()
    selected = ranked[:maximum_selected] if isinstance(maximum_selected, int) else []
    total_churned = sum(int(row["churned_users"]) for row in ranked)
    captured_churned = sum(int(row["churned_users"]) for row in selected)
    reviewed_users = sum(int(row["users"]) for row in selected)
    candidate_value = captured_churned / total_churned if total_churned else 0.0
    decision = {
        "implementation_id": spec.get("implementation_id"),
        "adapter_id": (spec.get("route_adapter") or {}).get("adapter_id"),
        "selected_segments": [row["segment_id"] for row in selected],
        "candidate_value": round(candidate_value, 6),
        "reviewed_users": reviewed_users,
        "captured_churned_users": captured_churned,
        "total_churned_users": total_churned,
        "causal_effect_claimed": False,
    }
    errors: list[dict[str, Any]] = []
    if not selected:
        errors.append({"field": "selected_segments", "reason": "no candidate selected"})
    if any(not 0 <= float(row["candidate_score"]) <= 1 for row in ranked):
        errors.append({"field": "candidate_score", "reason": "outside normalized range"})
    return (
        ranked,
        decision,
        check(
            "route_adapter_produces_deterministic_bounded_candidate_outputs",
            not errors,
            observed={"selected_segments": decision["selected_segments"], "errors": errors},
            expected="stable ranking, scores in [0,1], one selected segment and no causal claim",
            message=(
                "The candidate is executable, inspectable and constrained by its adapter contract."
            ),
        ),
    )


def evaluate_candidate(
    decision: dict[str, Any], acceptance_gate: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    candidate_value = decision.get("candidate_value")
    threshold = acceptance_gate.get("candidate_threshold")
    tolerance = acceptance_gate.get("tolerance")
    direction = acceptance_gate.get("direction")
    reviewed_users = decision.get("reviewed_users")
    max_capacity = acceptance_gate.get("max_capacity")
    if not all(
        isinstance(value, (int, float)) for value in (candidate_value, threshold, tolerance)
    ):
        errors.append(
            {"field": "candidate/threshold/tolerance", "reason": "numeric values required"}
        )
        metric_pass = False
    elif direction == "maximize":
        metric_pass = candidate_value + tolerance >= threshold
    elif direction == "minimize":
        metric_pass = candidate_value - tolerance <= threshold
    else:
        errors.append({"field": "direction", "observed": direction})
        metric_pass = False
    capacity_pass = (
        isinstance(reviewed_users, int)
        and isinstance(max_capacity, int)
        and reviewed_users <= max_capacity
    )
    if not capacity_pass:
        errors.append(
            {"field": "capacity", "reviewed_users": reviewed_users, "maximum": max_capacity}
        )
    candidate_pass = metric_pass and capacity_pass and not errors
    selected_method = "candidate" if candidate_pass else "baseline"
    result = {
        "metric_id": acceptance_gate.get("metric_id"),
        "direction": direction,
        "baseline_value": acceptance_gate.get("baseline_value"),
        "candidate_value": candidate_value,
        "candidate_threshold": threshold,
        "tolerance": tolerance,
        "metric_pass": metric_pass,
        "reviewed_users": reviewed_users,
        "max_capacity": max_capacity,
        "capacity_pass": capacity_pass,
        "candidate_pass": candidate_pass,
        "selected_method": selected_method,
        "decision_status": (
            "candidate_selected" if candidate_pass else "candidate_rejected_keep_baseline"
        ),
        "threshold_source": "immutable_upstream_acceptance_gate",
    }
    return result, check(
        "candidate_is_compared_to_the_frozen_acceptance_and_capacity_gate",
        not errors,
        observed={"result": result, "errors": errors},
        expected=(
            "exact upstream threshold comparison with explicit candidate or baseline selection"
        ),
        message="Failure to beat the baseline is a valid result; moving the gate is not.",
    )


def validate_complexity_and_environment(
    spec: dict[str, Any], complexity_budget: dict[str, Any]
) -> dict[str, Any]:
    environment = spec.get("environment")
    config = spec.get("frozen_config")
    errors: list[dict[str, Any]] = []
    if not isinstance(environment, dict) or not isinstance(config, dict):
        errors.append({"field": "environment/frozen_config", "reason": "objects required"})
        environment = {}
        config = {}
    dependencies = environment.get("new_runtime_dependencies")
    max_dependencies = complexity_budget.get("max_new_runtime_dependencies")
    if (
        not isinstance(dependencies, list)
        or not isinstance(max_dependencies, int)
        or len(dependencies) > max_dependencies
    ):
        errors.append({"field": "new_runtime_dependencies", "observed": dependencies})
    if environment.get("manager") != "uv" or environment.get("lock_file") != "uv.lock":
        errors.append({"field": "environment_lock", "reason": "uv/uv.lock required"})
    if environment.get("standard_library_only") is not True:
        errors.append({"field": "standard_library_only", "expected": True})
    if environment.get("runtime_check") != "behavioral_test_timeout":
        errors.append({"field": "runtime_check", "reason": "explicit verification mode required"})
    implementation_hours = 8
    max_hours = complexity_budget.get("max_implementation_hours")
    if not isinstance(max_hours, int) or implementation_hours > max_hours:
        errors.append(
            {
                "field": "implementation_hours",
                "observed": implementation_hours,
                "maximum": max_hours,
            }
        )
    runtime_limit = complexity_budget.get("max_runtime_seconds")
    if not isinstance(runtime_limit, int) or runtime_limit <= 0:
        errors.append({"field": "max_runtime_seconds", "observed": runtime_limit})
    return check(
        "implementation_stays_within_complexity_and_locked_environment_budget",
        not errors,
        observed={
            "new_runtime_dependencies": len(dependencies)
            if isinstance(dependencies, list)
            else None,
            "implementation_hours": implementation_hours,
            "runtime_limit_seconds": runtime_limit,
            "errors": errors,
        },
        expected="locked uv environment, no undeclared dependency and budgeted hours/runtime",
        message="The implementation cannot buy complexity outside the approved baseline budget.",
    )


def build_evidence_ledger(
    spec: dict[str, Any], state: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    claims = spec.get("evidence_claims")
    errors: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    allowed_paths = {
        "candidate_metrics.csv",
        "candidate_acceptance.json",
        "candidate_decision.json",
    }
    ids: list[str] = []
    for position, claim in enumerate(claims if isinstance(claims, list) else []):
        if not isinstance(claim, dict):
            errors.append({"position": position, "reason": "claim must be object"})
            continue
        claim_id = claim.get("claim_id")
        ids.append(str(claim_id))
        required_text = ("claim_id", "claim_text", "claim_type", "evidence_path", "limitation")
        for field in required_text:
            if not non_empty_text(claim.get(field)):
                errors.append({"claim_id": claim_id, "field": field, "reason": "required"})
        evidence_fields = claim.get("evidence_fields")
        if not isinstance(evidence_fields, list) or not evidence_fields:
            errors.append({"claim_id": claim_id, "field": "evidence_fields", "reason": "required"})
        if claim.get("evidence_path") not in allowed_paths:
            errors.append({"claim_id": claim_id, "field": "evidence_path", "reason": "unsupported"})
        if claim.get("claim_type") != state.get("claim_type"):
            errors.append(
                {
                    "claim_id": claim_id,
                    "field": "claim_type",
                    "observed": claim.get("claim_type"),
                    "allowed": state.get("claim_type"),
                }
            )
        rows.append(
            {
                "claim_id": claim_id,
                "claim_text": claim.get("claim_text"),
                "claim_type": claim.get("claim_type"),
                "evidence_path": claim.get("evidence_path"),
                "evidence_fields": "|".join(evidence_fields or []),
                "limitation": claim.get("limitation"),
                "status": "evidence_linked",
            }
        )
    if len(ids) != len(set(ids)):
        errors.append({"field": "claim_id", "reason": "must be unique"})
    if len(rows) < 3:
        errors.append({"field": "evidence_claims", "reason": "at least three claims required"})
    return rows, check(
        "evidence_ledger_links_every_claim_to_output_and_limitation",
        not errors,
        observed={"claims": len(rows), "errors": errors},
        expected="three or more unique claim-evidence-limitation rows within route claim type",
        message="A public claim without a precise evidence link is not an implementation result.",
    )


def validate_reproducible_command(spec: dict[str, Any]) -> dict[str, Any]:
    command = spec.get("reproducible_command")
    errors: list[dict[str, Any]] = []
    required_markers = (
        "uv run --locked python",
        "capstone_route_implementation.py",
        "--upstream-baseline-package",
        "--implementation-spec",
        "--output-dir",
        "--fail-on-invalid",
    )
    if not non_empty_text(command):
        errors.append({"field": "reproducible_command", "reason": "required"})
        command = ""
    for marker in required_markers:
        if marker not in command:
            errors.append({"field": "reproducible_command", "missing": marker})
    if command.startswith("/") or "/Users/" in command or "TemporaryDirectory" in command:
        errors.append({"field": "reproducible_command", "reason": "machine-local path forbidden"})
    return check(
        "one_locked_relative_command_rebuilds_the_complete_package",
        not errors,
        observed={"command": command, "errors": errors},
        expected=list(required_markers),
        message="A documented command is part of the result, not an optional note.",
    )


def validate_public_boundary(
    candidate_metrics: list[dict[str, Any]], state: dict[str, Any]
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    forbidden_columns = {"user_id", "ticket_id", "email", "phone", "name", "secret"}
    columns = set(candidate_metrics[0]) if candidate_metrics else set()
    leaked = sorted(columns & forbidden_columns)
    if leaked:
        errors.append({"field": "candidate_metrics", "restricted_columns": leaked})
    if state.get("implementation_id") is not None:
        errors.append(
            {"field": "upstream.implementation_id", "reason": "later stage already present"}
        )
    for field in ("verification_id", "review_id", "defense_id"):
        if state.get(field) is not None:
            errors.append({"field": f"upstream.{field}", "observed": state.get(field)})
    return check(
        "implementation_outputs_remain_aggregate_public_and_stop_at_current_stage",
        not errors,
        observed={"columns": sorted(columns), "errors": errors},
        expected="aggregate candidate outputs, no restricted IDs and no later-stage evidence",
        message="Implementation cannot widen data rights or manufacture verification evidence.",
    )


def run_trace_rows(
    spec: dict[str, Any], candidate_acceptance: dict[str, Any]
) -> list[dict[str, Any]]:
    events = [
        (1, "validate_upstream", "baseline_manifest.json", "upstream hashes verified"),
        (2, "load_frozen_config", "implementation_spec.json", "config loaded before run"),
        (3, "execute_route_adapter", "baseline_metrics.csv", "candidate_metrics.csv"),
        (4, "compare_acceptance_gate", "acceptance_gate.json", "candidate_acceptance.json"),
        (5, "link_evidence", "evidence_claims", "evidence_ledger.csv"),
        (6, "package_outputs", "generated outputs", "implementation_manifest.json"),
    ]
    return [
        {
            "sequence": sequence,
            "event": event,
            "status": "completed",
            "input": input_value,
            "output": output_value,
            "implementation_id": spec.get("implementation_id"),
            "selected_method": candidate_acceptance.get("selected_method", "pending"),
        }
        for sequence, event, input_value, output_value in events
    ]


def audit_implementation(
    *, upstream_baseline_package: str | Path, implementation_spec_path: str | Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    package = Path(upstream_baseline_package)
    spec = read_json(implementation_spec_path)
    state, raw_metrics, fields, acceptance_gate, complexity_budget, upstream_check = (
        validate_upstream_baseline_package(package)
    )
    metrics, input_check = parse_baseline_metrics(raw_metrics, fields)
    route = str(state.get("route"))
    variant = str(state.get("route_variant"))
    if (route, variant) == ("core_analytics", "standard"):
        candidate_metrics, candidate_decision, candidate_check = run_core_adapter(spec, metrics)
    else:
        candidate_metrics, candidate_decision = [], {}
        candidate_check = check(
            "route_adapter_produces_deterministic_bounded_candidate_outputs",
            False,
            observed={"route": route, "variant": variant},
            expected="reference executable currently implements core_analytics/standard",
            message="Replace the reference adapter with the selected route implementation.",
        )
    candidate_acceptance, acceptance_check = evaluate_candidate(candidate_decision, acceptance_gate)
    evidence_rows, evidence_check = build_evidence_ledger(spec, state)
    checks = [
        upstream_check,
        validate_spec_structure(spec, state),
        validate_route_adapter(spec, state),
        validate_frozen_config(spec, complexity_budget),
        input_check,
        candidate_check,
        acceptance_check,
        validate_complexity_and_environment(spec, complexity_budget),
        evidence_check,
        validate_reproducible_command(spec),
        validate_public_boundary(candidate_metrics, state),
    ]
    blocking_errors = [
        item["id"] for item in checks if not item["valid"] and item["severity"] == "block"
    ]
    upstream_warnings = state.get("warnings", []) if isinstance(state.get("warnings"), list) else []
    result_warnings = []
    if (
        candidate_acceptance.get("candidate_pass") is False
        and not acceptance_check["observed"]["errors"]
    ):
        result_warnings.append("candidate_did_not_clear_practical_threshold")
    result_warnings.extend(
        ["tiny_implementation_sample_expected", "candidate_ranking_is_not_causal_effect"]
    )
    warnings = list(dict.fromkeys(upstream_warnings + result_warnings))
    valid = not blocking_errors
    report = {
        "version": IMPLEMENTATION_VERSION,
        "implementation_id": spec.get("implementation_id"),
        "project_id": spec.get("project_id"),
        "contract_id": spec.get("contract_id"),
        "baseline_id": spec.get("baseline_id"),
        "status": "implementation_ready" if valid else "implementation_block",
        "valid": valid,
        "checks": checks,
        "summary": {
            "blocking_errors": blocking_errors,
            "warnings": warnings,
            "check_count": len(checks),
            "candidate_rows": len(candidate_metrics),
            "selected_segments": candidate_decision.get("selected_segments", []),
            "candidate_value": candidate_acceptance.get("candidate_value"),
            "candidate_threshold": candidate_acceptance.get("candidate_threshold"),
            "candidate_pass": candidate_acceptance.get("candidate_pass"),
            "selected_method": candidate_acceptance.get("selected_method"),
            "next_stage": "verification" if valid else "implementation",
        },
    }
    return report, {
        "spec": spec,
        "state": state,
        "candidate_metrics": candidate_metrics,
        "candidate_decision": {
            **candidate_decision,
            "selected_method": candidate_acceptance.get("selected_method"),
            "decision_status": candidate_acceptance.get("decision_status"),
            "claim_boundary": (spec.get("route_adapter") or {}).get("claim_boundary"),
        },
        "candidate_acceptance": candidate_acceptance,
        "evidence_rows": evidence_rows,
        "complexity_budget": complexity_budget,
    }


def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def build_implementation_package(
    *,
    upstream_baseline_package: str | Path,
    implementation_spec_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    report, result = audit_implementation(
        upstream_baseline_package=upstream_baseline_package,
        implementation_spec_path=implementation_spec_path,
    )
    environment = dict(result["spec"].get("environment", {}))
    lock_path = project_root() / "uv.lock"
    environment.update(
        {
            "lock_file_sha256": sha256_file(lock_path) if lock_path.is_file() else None,
            "lock_file_present": lock_path.is_file(),
            "reproducible_command": result["spec"].get("reproducible_command"),
        }
    )
    route_report = {
        "adapter": result["spec"].get("route_adapter"),
        "config": result["spec"].get("frozen_config"),
        "candidate_policy": result["spec"].get("candidate_policy"),
        "candidate_rows": len(result["candidate_metrics"]),
        "selected_segments": result["candidate_decision"].get("selected_segments", []),
        "status": "executed" if report["valid"] else "blocked",
    }
    generated = {
        "implementation_spec": write_json(output / "implementation_spec.json", result["spec"]),
        "implementation_report": write_json(output / "implementation_report.json", report),
        "implementation_config": write_json(output / "implementation_config.json", environment),
        "route_adapter_report": write_json(output / "route_adapter_report.json", route_report),
        "candidate_metrics": write_csv(
            output / "candidate_metrics.csv",
            result["candidate_metrics"],
            list(CANDIDATE_METRIC_FIELDS),
        ),
        "candidate_decision": write_json(
            output / "candidate_decision.json", result["candidate_decision"]
        ),
        "candidate_acceptance": write_json(
            output / "candidate_acceptance.json", result["candidate_acceptance"]
        ),
        "evidence_ledger": write_csv(
            output / "evidence_ledger.csv",
            result["evidence_rows"],
            [
                "claim_id",
                "claim_text",
                "claim_type",
                "evidence_path",
                "evidence_fields",
                "limitation",
                "status",
            ],
        ),
    }
    trace = run_trace_rows(result["spec"], result["candidate_acceptance"])
    generated["run_trace"] = write_csv(
        output / "run_trace.csv",
        trace,
        ["sequence", "event", "status", "input", "output", "implementation_id", "selected_method"],
    )
    state = dict(result["state"])
    old_warnings = state.get("warnings", []) if isinstance(state.get("warnings"), list) else []
    state.update(
        {
            "implementation_id": result["spec"].get("implementation_id"),
            "current_stage": "implementation",
            "stage_status": report["status"],
            "open_blockers": report["summary"]["blocking_errors"],
            "warnings": list(dict.fromkeys(old_warnings + report["summary"]["warnings"])),
            "artifact_inventory": list(
                dict.fromkeys(
                    state.get("artifact_inventory", []) + [path.name for path in generated.values()]
                )
            ),
            "evidence_links": [
                {"stage": "implementation", "path": "implementation_report.json"},
                {"stage": "implementation", "path": "candidate_acceptance.json"},
                {"stage": "implementation", "path": "evidence_ledger.csv"},
                {"stage": "implementation", "path": "run_trace.csv"},
            ],
            "input_checksums": {
                **state.get("input_checksums", {}),
                Path(implementation_spec_path).name: sha256_file(implementation_spec_path),
                "upstream_baseline_manifest.json": sha256_file(
                    Path(upstream_baseline_package) / "baseline_manifest.json"
                ),
                "upstream_acceptance_gate.json": sha256_file(
                    Path(upstream_baseline_package) / "acceptance_gate.json"
                ),
            },
            "output_checksums": {path.name: sha256_file(path) for path in generated.values()},
        }
    )
    state_path = write_json(output / "capstone_state.json", state)
    generated["capstone_state"] = state_path
    manifest = {
        "version": IMPLEMENTATION_VERSION,
        "project_id": result["spec"].get("project_id"),
        "contract_id": result["spec"].get("contract_id"),
        "baseline_id": result["spec"].get("baseline_id"),
        "implementation_id": result["spec"].get("implementation_id"),
        "status": report["status"],
        "valid": report["valid"],
        "hash_algorithm": "sha256",
        "renderer_used": "capstone_route_implementation",
        "raw_sources_copied": False,
        "upstream_inputs_mutated": False,
        "selected_method": report["summary"]["selected_method"],
        "candidate_pass": report["summary"]["candidate_pass"],
        "inputs": {
            "upstream_baseline_manifest": {
                "path": "upstream-baseline-package/baseline_manifest.json",
                "sha256": sha256_file(Path(upstream_baseline_package) / "baseline_manifest.json"),
            },
            "upstream_acceptance_gate": {
                "path": "upstream-baseline-package/acceptance_gate.json",
                "sha256": sha256_file(Path(upstream_baseline_package) / "acceptance_gate.json"),
            },
            "implementation_spec": {
                "path": Path(implementation_spec_path).name,
                "sha256": sha256_file(implementation_spec_path),
            },
            "lock_file": {
                "path": "uv.lock",
                "sha256": environment["lock_file_sha256"],
            },
        },
        "outputs": {
            name: {"path": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for name, path in generated.items()
        },
    }
    manifest_path = write_json(output / "implementation_manifest.json", manifest)
    return {
        "report": report,
        "output_dir": output,
        "state_path": state_path,
        "manifest_path": manifest_path,
        "acceptance_path": generated["candidate_acceptance"],
        "evidence_path": generated["evidence_ledger"],
        "trace_path": generated["run_trace"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an immutable route-specific capstone implementation package.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--upstream-baseline-package",
        type=Path,
        help="Passing baseline package from lesson 18/03.",
    )
    parser.add_argument(
        "--implementation-spec", type=Path, help="Path to implementation_spec.json."
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Directory for implementation package."
    )
    parser.add_argument(
        "--write-example", type=Path, help="Write deterministic upstream package and spec here."
    )
    parser.add_argument(
        "--fail-on-invalid",
        action="store_true",
        help="Return exit code 1 for a blocked implementation.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parsed = parse_args(argv)
    upstream = parsed.upstream_baseline_package
    implementation_spec = parsed.implementation_spec
    if parsed.write_example:
        sample = write_sample_inputs(parsed.write_example)
        upstream = upstream or sample["upstream_baseline_package"]
        implementation_spec = implementation_spec or sample["implementation_spec_path"]
    missing = [
        name
        for name, value in (
            ("--upstream-baseline-package", upstream),
            ("--implementation-spec", implementation_spec),
        )
        if value is None
    ]
    if missing:
        print(
            json.dumps(
                {
                    "version": IMPLEMENTATION_VERSION,
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
        result = build_implementation_package(
            upstream_baseline_package=upstream,
            implementation_spec_path=implementation_spec,
            output_dir=parsed.output_dir,
        )
    except (OSError, UnicodeError, csv.Error, json.JSONDecodeError, ImplementationError) as error:
        print(
            json.dumps(
                {
                    "version": IMPLEMENTATION_VERSION,
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
        "implementation_id": report["implementation_id"],
        "selected_segments": report["summary"]["selected_segments"],
        "candidate_value": report["summary"]["candidate_value"],
        "candidate_threshold": report["summary"]["candidate_threshold"],
        "candidate_pass": report["summary"]["candidate_pass"],
        "selected_method": report["summary"]["selected_method"],
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
