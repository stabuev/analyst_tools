from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

ALLOWED_BASELINE_TIMINGS = {"baseline"}
FORBIDDEN_ROLES = {
    "assignment_mechanism",
    "mediator",
    "collider",
    "selection",
    "outcome",
}
STATUS_PRIORITY = [
    "invalid_unknown_variable",
    "invalid_multiple_bad_controls",
    "invalid_outcome_leakage",
    "invalid_selection_bias",
    "invalid_opens_collider_bias",
    "invalid_blocks_total_effect",
    "invalid_post_treatment_descendant",
    "invalid_changes_treatment_definition",
    "invalid_contains_unmeasured_variable",
    "insufficient_measured_backdoors_open",
    "allowed_pre_treatment_adjustment_with_unmeasured_limitation",
    "allowed_pre_treatment_adjustment",
]


def read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def make_check(
    check_id: str,
    valid: bool,
    message: str,
    *,
    severity: str = "error",
    sample: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": check_id,
        "valid": valid,
        "severity": severity,
        "message": message,
    }
    if sample is not None:
        payload["sample"] = sample
    return payload


def load_dag_tools(path: str | Path | None = None):
    if path is None:
        phase_root = Path(__file__).resolve().parents[2]
        path = phase_root / "02-causal-dags" / "outputs" / "causal_dag_validator.py"
    spec = importlib.util.spec_from_file_location("causal_dag_validator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load DAG validator from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def node_map(dag: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in dag.get("nodes", [])}


def edge_tuples(dag: dict[str, Any]) -> list[tuple[str, str]]:
    return [(edge.get("source"), edge.get("target")) for edge in dag.get("edges", [])]


def directed_children(dag: dict[str, Any]) -> dict[str, set[str]]:
    children = {node["id"]: set() for node in dag.get("nodes", [])}
    for source, target in edge_tuples(dag):
        children.setdefault(source, set()).add(target)
        children.setdefault(target, set())
    return children


def descendants_of(dag: dict[str, Any], source: str) -> set[str]:
    children = directed_children(dag)
    descendants: set[str] = set()
    stack = list(children.get(source, set()))
    while stack:
        node = stack.pop()
        if node in descendants:
            continue
        descendants.add(node)
        stack.extend(children.get(node, set()))
    return descendants


def enumerate_directed_paths(
    dag: dict[str, Any],
    source: str,
    target: str,
    *,
    max_paths: int = 100,
) -> list[list[str]]:
    children = directed_children(dag)
    paths: list[list[str]] = []
    stack: list[tuple[str, list[str]]] = [(source, [source])]
    while stack:
        node, path = stack.pop()
        if node == target:
            paths.append(path)
            if len(paths) >= max_paths:
                break
            continue
        for child in sorted(children.get(node, set()), reverse=True):
            if child in path:
                continue
            stack.append((child, path + [child]))
    return paths


def data_contract_fields(data_contract: dict[str, Any]) -> set[tuple[str, str]]:
    fields: set[tuple[str, str]] = set()
    for table, table_spec in data_contract.get("tables", {}).items():
        for field in table_spec.get("columns", {}):
            fields.add((table, field))
    return fields


def path_key(path: list[str]) -> tuple[str, ...]:
    return tuple(path)


def path_signature(path: list[str]) -> str:
    return " -- ".join(path)


def directed_path_signature(path: list[str]) -> str:
    return " -> ".join(path)


def path_contains_unobserved(dag: dict[str, Any], path: list[str]) -> bool:
    nodes = node_map(dag)
    return any(nodes[node].get("observed") is False for node in path[1:-1])


def path_report(
    dag: dict[str, Any],
    paths: list[list[str]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    nodes = node_map(dag)
    report: list[dict[str, Any]] = []
    for path in paths[:limit]:
        intermediates = path[1:-1]
        report.append(
            {
                "path": path,
                "path_text": path_signature(path),
                "contains_unmeasured": any(
                    nodes[node].get("observed") is False for node in intermediates
                ),
                "intermediate_roles": {node: nodes[node].get("role") for node in intermediates},
            }
        )
    return report


def directed_path_report(
    paths: list[list[str]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    return [{"path": path, "path_text": directed_path_signature(path)} for path in paths[:limit]]


def conditioning_variables(candidate: dict[str, Any]) -> list[str]:
    variables = list(candidate.get("variables", []))
    for variable in candidate.get("filter_variables", []):
        if variable not in variables:
            variables.append(variable)
    return variables


def expected_graph_bad_controls(
    dag: dict[str, Any],
    treatment: str,
) -> set[str]:
    descendants = descendants_of(dag, treatment)
    expected: set[str] = set()
    for variable, node in node_map(dag).items():
        if variable == treatment:
            continue
        role = node.get("role")
        if role in FORBIDDEN_ROLES or (
            variable in descendants and node.get("timing") not in ALLOWED_BASELINE_TIMINGS
        ):
            expected.add(variable)
    return expected


def core_status_for_variable(
    dag: dict[str, Any],
    variable: str,
    treatment: str,
    outcome: str,
) -> str:
    nodes = node_map(dag)
    if variable not in nodes:
        return "invalid_unknown_variable"
    node = nodes[variable]
    role = node.get("role")
    timing = node.get("timing")
    if node.get("observed") is False:
        return "invalid_contains_unmeasured_variable"
    if role == "outcome" or variable == outcome:
        return "invalid_outcome_leakage"
    if role == "selection":
        return "invalid_selection_bias"
    if role == "collider":
        return "invalid_opens_collider_bias"
    if role == "mediator":
        return "invalid_blocks_total_effect"
    if variable in descendants_of(dag, treatment) and timing not in ALLOWED_BASELINE_TIMINGS:
        return "invalid_post_treatment_descendant"
    if role == "assignment_mechanism":
        return "invalid_changes_treatment_definition"
    return "allowed_pre_treatment_adjustment"


def classify_variable(
    dag: dict[str, Any],
    variable: str,
    treatment: str,
    outcome: str,
) -> dict[str, Any]:
    nodes = node_map(dag)
    if variable not in nodes:
        return {
            "variable": variable,
            "known": False,
            "core_status": "invalid_unknown_variable",
            "bad_control_reasons": ["unknown_variable"],
        }

    node = nodes[variable]
    descendants = descendants_of(dag, treatment)
    directed_effect_paths = enumerate_directed_paths(dag, treatment, outcome)
    on_directed_total_effect_path = any(variable in path[1:-1] for path in directed_effect_paths)
    reasons: list[str] = []

    role = node.get("role")
    timing = node.get("timing")
    if node.get("observed") is False:
        reasons.append("unobserved_variable")
    if role == "assignment_mechanism":
        reasons.append("assignment_mechanism_changes_treatment_definition")
    if role == "mediator":
        reasons.append("mediator_blocks_total_effect_path")
    if role == "collider":
        reasons.append("collider_opens_noncausal_path")
    if role == "selection":
        reasons.append("post_treatment_selection_changes_population")
    if role == "outcome" or variable == outcome:
        reasons.append("outcome_leakage")
    if variable in descendants and variable != outcome:
        reasons.append("descendant_of_treatment")
    if timing not in ALLOWED_BASELINE_TIMINGS and variable != treatment:
        reasons.append("nonbaseline_or_post_treatment_timing")

    return {
        "variable": variable,
        "known": True,
        "role": role,
        "timing": timing,
        "observed": node.get("observed"),
        "is_descendant_of_treatment": variable in descendants,
        "on_directed_total_effect_path": on_directed_total_effect_path,
        "core_status": core_status_for_variable(dag, variable, treatment, outcome),
        "bad_control_reasons": reasons,
    }


def mechanism_examples(
    dag: dict[str, Any],
    variable: str,
    treatment: str,
    outcome: str,
    dag_tools: Any,
    directed_effect_paths: list[list[str]],
) -> list[dict[str, Any]]:
    status = core_status_for_variable(dag, variable, treatment, outcome)
    if status == "invalid_blocks_total_effect":
        paths = [path for path in directed_effect_paths if variable in path[1:-1]]
        return directed_path_report(paths, limit=5)
    if status in {"invalid_opens_collider_bias", "invalid_selection_bias"}:
        paths = [
            path
            for path in dag_tools.enumerate_simple_paths(dag, treatment, outcome)
            if variable in path[1:-1]
            and not dag_tools.is_path_active(dag, path, set())
            and dag_tools.is_path_active(dag, path, {variable})
        ]
        return path_report(dag, paths, limit=5)
    return []


def calculate_candidate_status(
    variable_classifications: list[dict[str, Any]],
    open_measured_backdoor_paths: list[list[str]],
    open_unmeasured_backdoor_paths: list[list[str]],
    candidate: dict[str, Any],
) -> str:
    statuses = [
        item["core_status"]
        for item in variable_classifications
        if item["core_status"] != "allowed_pre_treatment_adjustment"
    ]
    if any(status == "invalid_unknown_variable" for status in statuses):
        return "invalid_unknown_variable"

    invalid_statuses = [status for status in statuses if status.startswith("invalid_")]
    invalid_variables = [
        item for item in variable_classifications if item["core_status"].startswith("invalid_")
    ]
    if len(invalid_variables) > 1:
        return "invalid_multiple_bad_controls"
    if invalid_statuses:
        return sorted(invalid_statuses, key=STATUS_PRIORITY.index)[0]
    if open_measured_backdoor_paths:
        return "insufficient_measured_backdoors_open"
    if open_unmeasured_backdoor_paths:
        if candidate.get("is_primary_recommendation"):
            return "allowed_pre_treatment_adjustment_with_unmeasured_limitation"
        return "allowed_pre_treatment_adjustment_with_unmeasured_limitation"
    return "allowed_pre_treatment_adjustment"


def evaluate_candidate_action(
    dag: dict[str, Any],
    candidate: dict[str, Any],
    treatment: str,
    outcome: str,
    dag_tools: Any,
    initial_total_paths: list[list[str]],
    initial_backdoor_paths: list[list[str]],
    directed_effect_paths: list[list[str]],
) -> dict[str, Any]:
    variables = conditioning_variables(candidate)
    classifications = [
        classify_variable(dag, variable, treatment, outcome) for variable in variables
    ]
    for classification in classifications:
        if classification["known"]:
            classification["mechanism_path_examples"] = mechanism_examples(
                dag,
                classification["variable"],
                treatment,
                outcome,
                dag_tools,
                directed_effect_paths,
            )
    unknown = [item["variable"] for item in classifications if not item["known"]]
    conditioning_set = set(variables)
    remaining_total_paths = (
        [] if unknown else dag_tools.active_paths(dag, treatment, outcome, conditioning_set)
    )
    remaining_backdoor_paths = (
        []
        if unknown
        else dag_tools.active_backdoor_paths(dag, treatment, outcome, conditioning_set)
    )
    open_measured_backdoor_paths = [
        path for path in remaining_backdoor_paths if not path_contains_unobserved(dag, path)
    ]
    open_unmeasured_backdoor_paths = [
        path for path in remaining_backdoor_paths if path_contains_unobserved(dag, path)
    ]

    remaining_total_keys = {path_key(path) for path in remaining_total_paths}
    initial_total_keys = {path_key(path) for path in initial_total_paths}
    newly_opened_paths = [
        path for path in remaining_total_paths if path_key(path) not in initial_total_keys
    ]
    closed_total_paths = [
        path for path in initial_total_paths if path_key(path) not in remaining_total_keys
    ]
    blocked_directed_effect_paths = [
        path
        for path in directed_effect_paths
        if path_key(path) in {path_key(item) for item in closed_total_paths}
    ]

    calculated_status = calculate_candidate_status(
        classifications,
        open_measured_backdoor_paths,
        open_unmeasured_backdoor_paths,
        candidate,
    )
    bad_variables = [
        item
        for item in classifications
        if item["core_status"] != "allowed_pre_treatment_adjustment"
    ]

    return {
        "action_id": candidate.get("action_id"),
        "action_type": candidate.get("action_type"),
        "declared_status": candidate.get("declared_status"),
        "calculated_status": calculated_status,
        "allowed_for_estimation": bool(candidate.get("allowed_for_estimation")),
        "is_primary_recommendation": bool(candidate.get("is_primary_recommendation")),
        "variables": list(candidate.get("variables", [])),
        "filter_variables": list(candidate.get("filter_variables", [])),
        "conditioning_variables": variables,
        "variable_classifications": classifications,
        "bad_control_variables": bad_variables,
        "active_total_paths_after_conditioning": len(remaining_total_paths),
        "active_backdoor_paths_after_conditioning": len(remaining_backdoor_paths),
        "open_measured_backdoor_paths": len(open_measured_backdoor_paths),
        "open_unmeasured_backdoor_paths": len(open_unmeasured_backdoor_paths),
        "newly_opened_paths": len(newly_opened_paths),
        "closed_total_paths": len(closed_total_paths),
        "blocked_directed_total_effect_paths": len(blocked_directed_effect_paths),
        "newly_opened_path_examples": path_report(dag, newly_opened_paths, limit=5),
        "blocked_directed_total_effect_path_examples": directed_path_report(
            blocked_directed_effect_paths,
            limit=5,
        ),
        "remaining_backdoor_path_examples": path_report(
            dag,
            remaining_backdoor_paths,
            limit=5,
        ),
        "changes_population": bool(candidate.get("filter_variables")),
        "population_change": candidate.get("population_change"),
    }


def validate_policy(
    dag: dict[str, Any],
    policy: dict[str, Any],
    data_contract: dict[str, Any],
    treatment: str,
    outcome: str,
) -> list[dict[str, Any]]:
    nodes = node_map(dag)
    fields = data_contract_fields(data_contract)
    required = [
        "policy_id",
        "graph_id",
        "question_id",
        "estimand_id",
        "treatment",
        "outcome",
        "effect",
        "bad_controls",
    ]
    missing = [field for field in required if field not in policy]
    checks = [
        make_check(
            "policy_required_fields",
            not missing,
            "Bad-control policy содержит обязательные поля.",
            sample=missing or None,
        )
    ]

    alignment_errors = []
    for field in ["graph_id", "question_id", "treatment", "outcome"]:
        if field == "graph_id":
            expected = dag.get("graph_id")
        else:
            expected = {
                "question_id": dag.get("question_id"),
                "treatment": treatment,
                "outcome": outcome,
            }[field]
        if policy.get(field) != expected:
            alignment_errors.append(
                {"field": field, "expected": expected, "actual": policy.get(field)}
            )
    checks.append(
        make_check(
            "policy_aligns_with_graph",
            not alignment_errors,
            "Policy относится к тому же DAG, question, treatment и outcome.",
            sample=alignment_errors or None,
        )
    )

    bad_controls = policy.get("bad_controls", [])
    policy_variables = [item.get("variable") for item in bad_controls]
    unknown = [variable for variable in policy_variables if variable not in nodes]
    checks.append(
        make_check(
            "bad_control_policy_variables_exist",
            not unknown,
            "Все bad controls из policy объявлены в DAG.",
            sample=unknown or None,
        )
    )

    expected = expected_graph_bad_controls(dag, treatment)
    missing_from_policy = sorted(expected - set(policy_variables))
    checks.append(
        make_check(
            "policy_covers_graph_bad_controls",
            not missing_from_policy,
            "Policy покрывает mediator, collider, selection, assignment mechanism "
            "и outcome leakage controls из DAG.",
            sample=missing_from_policy or None,
        )
    )

    classification_errors = []
    for item in bad_controls:
        variable = item.get("variable")
        if variable not in nodes:
            continue
        expected_status = core_status_for_variable(dag, variable, treatment, outcome)
        if item.get("expected_status") != expected_status:
            classification_errors.append(
                {
                    "variable": variable,
                    "expected_status": expected_status,
                    "declared_status": item.get("expected_status"),
                }
            )
        if expected_status == "allowed_pre_treatment_adjustment":
            classification_errors.append(
                {
                    "variable": variable,
                    "reason": "policy lists a baseline non-bad-control variable",
                }
            )
    checks.append(
        make_check(
            "bad_control_policy_classifications_match_graph",
            not classification_errors,
            "Типы bad controls в policy совпадают с DAG roles, timing и descendants.",
            sample=classification_errors or None,
        )
    )

    source_errors = []
    for variable in policy_variables:
        if variable not in nodes:
            continue
        for source_field in nodes[variable].get("source_fields", []):
            pair = (source_field.get("table"), source_field.get("field"))
            if pair not in fields:
                source_errors.append(
                    {
                        "variable": variable,
                        "source_field": source_field,
                        "reason": "source field is absent from data contract",
                    }
                )
    checks.append(
        make_check(
            "bad_control_source_fields_exist",
            not source_errors,
            "Observed bad controls ссылаются на поля из data contract.",
            sample=source_errors or None,
        )
    )
    return checks


def validate_candidate_actions(
    action_spec: dict[str, Any],
    candidate_audits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    required = [
        "control_action_spec_id",
        "graph_id",
        "policy_id",
        "question_id",
        "estimand_id",
        "treatment",
        "outcome",
        "candidate_control_actions",
    ]
    missing = [field for field in required if field not in action_spec]
    checks = [
        make_check(
            "candidate_action_spec_required_fields",
            not missing,
            "Control-action spec содержит обязательные поля.",
            sample=missing or None,
        )
    ]

    action_errors = []
    for candidate in action_spec.get("candidate_control_actions", []):
        missing_candidate_fields = [
            field
            for field in [
                "action_id",
                "action_type",
                "variables",
                "filter_variables",
                "declared_status",
                "allowed_for_estimation",
                "is_primary_recommendation",
            ]
            if field not in candidate
        ]
        if missing_candidate_fields:
            action_errors.append(
                {
                    "action_id": candidate.get("action_id"),
                    "missing": missing_candidate_fields,
                }
            )
    checks.append(
        make_check(
            "candidate_actions_required_fields",
            not action_errors,
            "Каждый candidate action описывает variables, filters, status и estimation policy.",
            sample=action_errors or None,
        )
    )

    status_errors = [
        {
            "action_id": audit["action_id"],
            "declared_status": audit["declared_status"],
            "calculated_status": audit["calculated_status"],
        }
        for audit in candidate_audits
        if audit["declared_status"] != audit["calculated_status"]
    ]
    checks.append(
        make_check(
            "candidate_statuses_match_audit",
            not status_errors,
            "Declared statuses совпадают с рассчитанными bad-control diagnostics.",
            sample=status_errors or None,
        )
    )

    unknown_errors = [
        {
            "action_id": audit["action_id"],
            "variables": [
                item["variable"] for item in audit["variable_classifications"] if not item["known"]
            ],
        }
        for audit in candidate_audits
        if any(not item["known"] for item in audit["variable_classifications"])
    ]
    checks.append(
        make_check(
            "candidate_variables_exist_in_graph",
            not unknown_errors,
            "Candidate actions не ссылаются на переменные вне DAG.",
            sample=unknown_errors or None,
        )
    )

    primary_ids = [
        audit["action_id"] for audit in candidate_audits if audit["is_primary_recommendation"]
    ]
    checks.append(
        make_check(
            "exactly_one_primary_recommendation",
            len(primary_ids) == 1,
            "Ровно один candidate action помечен как primary recommendation.",
            sample=primary_ids if len(primary_ids) != 1 else None,
        )
    )

    primary_errors = []
    for audit in candidate_audits:
        if not audit["is_primary_recommendation"]:
            continue
        if audit["bad_control_variables"]:
            primary_errors.append(
                {
                    "action_id": audit["action_id"],
                    "reason": "primary contains bad controls",
                    "variables": [item["variable"] for item in audit["bad_control_variables"]],
                }
            )
        if audit["open_measured_backdoor_paths"] != 0:
            primary_errors.append(
                {
                    "action_id": audit["action_id"],
                    "reason": "measured_backdoors_still_open",
                    "open_measured_backdoor_paths": audit["open_measured_backdoor_paths"],
                }
            )
        if audit["declared_status"] not in {
            "allowed_pre_treatment_adjustment",
            "allowed_pre_treatment_adjustment_with_unmeasured_limitation",
        }:
            primary_errors.append(
                {
                    "action_id": audit["action_id"],
                    "reason": "primary status is not allowed adjustment",
                    "declared_status": audit["declared_status"],
                }
            )
    checks.append(
        make_check(
            "primary_recommendation_has_no_bad_controls_and_blocks_measured_backdoors",
            not primary_errors,
            "Primary action использует только observed baseline controls "
            "и закрывает measured backdoors.",
            sample=primary_errors or None,
        )
    )

    estimation_policy_errors = []
    for audit in candidate_audits:
        is_allowed = audit["calculated_status"] in {
            "allowed_pre_treatment_adjustment",
            "allowed_pre_treatment_adjustment_with_unmeasured_limitation",
        }
        if audit["allowed_for_estimation"] != is_allowed:
            estimation_policy_errors.append(
                {
                    "action_id": audit["action_id"],
                    "calculated_status": audit["calculated_status"],
                    "allowed_for_estimation": audit["allowed_for_estimation"],
                }
            )
    checks.append(
        make_check(
            "estimation_policy_rejects_bad_controls",
            not estimation_policy_errors,
            "Only allowed pre-treatment actions may feed future estimators.",
            sample=estimation_policy_errors or None,
        )
    )

    filter_policy_errors = [
        {
            "action_id": audit["action_id"],
            "filter_variables": audit["filter_variables"],
            "reason": "filter changes population but population_change is empty",
        }
        for audit in candidate_audits
        if audit["filter_variables"] and not audit["population_change"]
    ]
    checks.append(
        make_check(
            "filter_actions_declare_population_change",
            not filter_policy_errors,
            "Filter actions явно описывают, как меняется target population.",
            sample=filter_policy_errors or None,
        )
    )
    return checks


def validate_specs(
    dag: dict[str, Any],
    policy: dict[str, Any],
    action_spec: dict[str, Any],
    data_contract: dict[str, Any],
    *,
    dag_tools: Any | None = None,
) -> dict[str, Any]:
    if dag_tools is None:
        dag_tools = load_dag_tools()
    treatment = action_spec.get("treatment") or policy.get("treatment")
    outcome = action_spec.get("outcome") or policy.get("outcome")

    initial_total_paths = dag_tools.active_paths(dag, treatment, outcome, set())
    initial_backdoor_paths = dag_tools.active_backdoor_paths(dag, treatment, outcome, set())
    directed_effect_paths = enumerate_directed_paths(dag, treatment, outcome)

    candidate_audits = [
        evaluate_candidate_action(
            dag,
            candidate,
            treatment,
            outcome,
            dag_tools,
            initial_total_paths,
            initial_backdoor_paths,
            directed_effect_paths,
        )
        for candidate in action_spec.get("candidate_control_actions", [])
    ]

    checks = []
    checks.extend(validate_policy(dag, policy, data_contract, treatment, outcome))
    checks.extend(validate_candidate_actions(action_spec, candidate_audits))

    blocking_checks = [
        check["id"] for check in checks if not check["valid"] and check.get("severity") == "error"
    ]
    valid = not blocking_checks
    primary = next(
        (audit for audit in candidate_audits if audit["is_primary_recommendation"]),
        None,
    )
    descendants = sorted(descendants_of(dag, treatment))
    bad_control_variables = sorted(item["variable"] for item in policy.get("bad_controls", []))

    return {
        "valid": valid,
        "summary": {
            "policy_id": policy.get("policy_id"),
            "control_action_spec_id": action_spec.get("control_action_spec_id"),
            "graph_id": dag.get("graph_id"),
            "treatment": treatment,
            "outcome": outcome,
            "effect": policy.get("effect"),
            "initial_active_total_paths": len(initial_total_paths),
            "initial_active_backdoor_paths": len(initial_backdoor_paths),
            "directed_total_effect_paths": len(directed_effect_paths),
            "descendants_of_treatment": descendants,
            "bad_control_variables": bad_control_variables,
            "audited_candidate_actions": len(candidate_audits),
            "allowed_candidate_actions": [
                audit["action_id"] for audit in candidate_audits if audit["allowed_for_estimation"]
            ],
            "rejected_candidate_actions": [
                audit["action_id"]
                for audit in candidate_audits
                if not audit["allowed_for_estimation"]
            ],
            "primary_recommendation": primary["action_id"] if primary else None,
            "primary_open_measured_backdoor_paths": primary["open_measured_backdoor_paths"]
            if primary
            else None,
            "primary_open_unmeasured_backdoor_paths": primary["open_unmeasured_backdoor_paths"]
            if primary
            else None,
            "blocking_checks": blocking_checks,
        },
        "candidate_action_audits": candidate_audits,
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit colliders, mediators, selection variables and other bad controls."
    )
    parser.add_argument("--dag", required=True, help="Path to causal_dag.json")
    parser.add_argument(
        "--policy",
        required=True,
        help="Path to bad_control_policy.json",
    )
    parser.add_argument(
        "--candidate-actions",
        required=True,
        help="Path to candidate_control_actions.json",
    )
    parser.add_argument(
        "--data-contract",
        required=True,
        help="Path to phase data/contract.json",
    )
    parser.add_argument(
        "--dag-validator",
        default=None,
        help="Optional path to causal_dag_validator.py",
    )
    parser.add_argument("--output", default=None, help="Optional report JSON path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dag_tools = load_dag_tools(args.dag_validator)
    report = validate_specs(
        read_json(args.dag),
        read_json(args.policy),
        read_json(args.candidate_actions),
        read_json(args.data_contract),
        dag_tools=dag_tools,
    )
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
