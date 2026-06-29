from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

ALLOWED_BASELINE_TIMINGS = {"baseline"}
FORBIDDEN_ADJUSTMENT_ROLES = {
    "assignment_mechanism",
    "treatment",
    "mediator",
    "collider",
    "selection",
    "outcome",
}


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


def data_contract_fields(data_contract: dict[str, Any]) -> set[tuple[str, str]]:
    fields: set[tuple[str, str]] = set()
    for table, table_spec in data_contract.get("tables", {}).items():
        for field in table_spec.get("columns", {}):
            fields.add((table, field))
    return fields


def path_contains_unobserved(dag: dict[str, Any], path: list[str]) -> bool:
    nodes = node_map(dag)
    return any(nodes[node].get("observed") is False for node in path)


def path_signature(path: list[str]) -> str:
    return " -- ".join(path)


def active_path_report(
    dag: dict[str, Any],
    paths: list[list[str]],
    *,
    limit: int = 25,
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


def backdoor_participation(
    dag: dict[str, Any],
    paths: list[list[str]],
) -> dict[str, dict[str, Any]]:
    nodes = node_map(dag)
    counts = Counter(node for path in paths for node in path[1:-1])
    return {
        node: {
            "path_count": count,
            "observed": nodes[node].get("observed"),
            "timing": nodes[node].get("timing"),
            "role": nodes[node].get("role"),
        }
        for node, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    }


def candidate_by_id(adjustment_spec: dict[str, Any], set_id: str) -> dict[str, Any] | None:
    return next(
        (
            candidate
            for candidate in adjustment_spec.get("candidate_adjustment_sets", [])
            if candidate.get("set_id") == set_id
        ),
        None,
    )


def evaluate_candidate_set(
    dag: dict[str, Any],
    candidate: dict[str, Any],
    treatment: str,
    outcome: str,
    dag_tools: Any,
    initial_paths: list[list[str]],
) -> dict[str, Any]:
    nodes = node_map(dag)
    variables = list(candidate.get("variables", []))
    unknown = [variable for variable in variables if variable not in nodes]
    forbidden = [
        {
            "variable": variable,
            "role": nodes[variable].get("role"),
            "timing": nodes[variable].get("timing"),
        }
        for variable in variables
        if variable in nodes
        and (
            nodes[variable].get("role") in FORBIDDEN_ADJUSTMENT_ROLES
            or nodes[variable].get("timing") not in ALLOWED_BASELINE_TIMINGS
        )
    ]
    unobserved = [
        variable
        for variable in variables
        if variable in nodes and nodes[variable].get("observed") is False
    ]
    remaining_paths = (
        [] if unknown else dag_tools.active_backdoor_paths(dag, treatment, outcome, set(variables))
    )
    open_measured_paths = [
        path for path in remaining_paths if not path_contains_unobserved(dag, path)
    ]
    open_unmeasured_paths = [
        path for path in remaining_paths if path_contains_unobserved(dag, path)
    ]
    calculated_status = calculate_status(
        candidate,
        unknown,
        forbidden,
        unobserved,
        open_measured_paths,
        open_unmeasured_paths,
    )
    return {
        "set_id": candidate.get("set_id"),
        "declared_status": candidate.get("declared_status"),
        "calculated_status": calculated_status,
        "is_primary_recommendation": bool(candidate.get("is_primary_recommendation")),
        "variables": variables,
        "variable_count": len(variables),
        "unknown_variables": unknown,
        "forbidden_variables": forbidden,
        "unobserved_variables": unobserved,
        "active_backdoor_paths": len(remaining_paths),
        "open_measured_backdoor_paths": len(open_measured_paths),
        "open_unmeasured_backdoor_paths": len(open_unmeasured_paths),
        "closed_backdoor_paths": max(0, len(initial_paths) - len(remaining_paths))
        if not unknown
        else None,
        "newly_opened_or_reopened_paths": max(0, len(remaining_paths) - len(initial_paths))
        if not unknown
        else None,
        "remaining_path_examples": active_path_report(dag, remaining_paths, limit=5),
    }


def calculate_status(
    candidate: dict[str, Any],
    unknown: list[str],
    forbidden: list[dict[str, Any]],
    unobserved: list[str],
    open_measured_paths: list[list[str]],
    open_unmeasured_paths: list[list[str]],
) -> str:
    if unknown:
        return "invalid_unknown_variable"
    if unobserved:
        return "invalid_contains_unmeasured_variable"
    if forbidden:
        return "invalid_forbidden_control"
    if open_measured_paths:
        return "insufficient_measured_backdoors_open"
    if open_unmeasured_paths:
        if candidate.get("is_primary_recommendation"):
            return "recommended_measured_adjustment_with_unmeasured_limitation"
        return "insufficient_unmeasured_confounding"
    return "sufficient_observed_backdoor_adjustment"


def validate_inventory(
    dag: dict[str, Any],
    inventory: dict[str, Any],
    data_contract: dict[str, Any],
    active_paths: list[list[str]],
) -> list[dict[str, Any]]:
    nodes = node_map(dag)
    contract_fields = data_contract_fields(data_contract)
    confounders = inventory.get("confounders", [])
    forbidden_controls = inventory.get("forbidden_controls", [])
    path_variables = {node for path in active_paths for node in path[1:-1]}

    required = [
        "inventory_id",
        "graph_id",
        "question_id",
        "estimand_id",
        "treatment",
        "outcome",
        "confounders",
        "forbidden_controls",
    ]
    missing = [field for field in required if field not in inventory]
    checks = [
        make_check(
            "inventory_required_fields",
            not missing,
            "Confounder inventory содержит обязательные поля.",
            sample=missing or None,
        )
    ]

    alignment_errors = []
    for field in ["graph_id", "question_id"]:
        if inventory.get(field) != dag.get(field):
            alignment_errors.append(
                {"field": field, "inventory": inventory.get(field), "dag": dag.get(field)}
            )
    checks.append(
        make_check(
            "inventory_aligns_with_graph",
            not alignment_errors,
            "Inventory относится к тому же graph/question.",
            sample=alignment_errors or None,
        )
    )

    unknown_confounders = [
        item.get("variable") for item in confounders if item.get("variable") not in nodes
    ]
    checks.append(
        make_check(
            "confounder_variables_exist_in_dag",
            not unknown_confounders,
            "Все confounders из inventory существуют в DAG.",
            sample=unknown_confounders or None,
        )
    )

    measurement_errors: list[dict[str, Any]] = []
    for item in confounders:
        variable = item.get("variable")
        if variable not in nodes:
            continue
        node = nodes[variable]
        category = item.get("measurement_status")
        if category == "measured":
            if node.get("observed") is not True:
                measurement_errors.append(
                    {"variable": variable, "reason": "measured variable is not observed"}
                )
            if node.get("timing") != "baseline":
                measurement_errors.append(
                    {
                        "variable": variable,
                        "reason": "measured confounder must be baseline",
                        "timing": node.get("timing"),
                    }
                )
            source_fields = node.get("source_fields", [])
            if not source_fields:
                measurement_errors.append({"variable": variable, "reason": "missing source_fields"})
            for source in source_fields:
                table_field = (source.get("table"), source.get("field"))
                if table_field not in contract_fields:
                    measurement_errors.append(
                        {
                            "variable": variable,
                            "reason": "source field is absent from data contract",
                            "source": source,
                        }
                    )
        elif category == "unmeasured":
            if node.get("observed") is not False:
                measurement_errors.append(
                    {"variable": variable, "reason": "unmeasured variable is observed"}
                )
        else:
            measurement_errors.append(
                {
                    "variable": variable,
                    "reason": "measurement_status must be measured or unmeasured",
                    "measurement_status": category,
                }
            )
    checks.append(
        make_check(
            "confounder_measurement_status_is_consistent",
            not measurement_errors,
            "Measured confounders имеют observed baseline source fields, "
            "unmeasured — явно ненаблюдаемы.",
            sample=measurement_errors or None,
        )
    )

    missing_active_confounders = [
        variable
        for variable in sorted(path_variables)
        if variable in nodes
        and nodes[variable].get("role") in {"confounder", "unmeasured_confounder"}
        and variable not in {item.get("variable") for item in confounders}
    ]
    checks.append(
        make_check(
            "active_backdoor_confounders_are_in_inventory",
            not missing_active_confounders,
            "Все confounder/unmeasured nodes на active backdoor paths включены в inventory.",
            sample=missing_active_confounders or None,
        )
    )

    unknown_forbidden = [
        item.get("variable") for item in forbidden_controls if item.get("variable") not in nodes
    ]
    forbidden_role_errors = [
        {
            "variable": item.get("variable"),
            "role": nodes[item.get("variable")].get("role"),
            "timing": nodes[item.get("variable")].get("timing"),
        }
        for item in forbidden_controls
        if item.get("variable") in nodes
        and nodes[item.get("variable")].get("role") not in FORBIDDEN_ADJUSTMENT_ROLES
        and nodes[item.get("variable")].get("timing") in ALLOWED_BASELINE_TIMINGS
    ]
    checks.append(
        make_check(
            "forbidden_controls_are_real_bad_controls",
            not unknown_forbidden and not forbidden_role_errors,
            "Forbidden controls существуют и не являются допустимыми baseline controls.",
            sample=(unknown_forbidden + forbidden_role_errors) or None,
        )
    )
    return checks


def validate_adjustment_spec(
    dag: dict[str, Any],
    adjustment_spec: dict[str, Any],
    evaluated_sets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    required = [
        "adjustment_spec_id",
        "graph_id",
        "inventory_id",
        "question_id",
        "estimand_id",
        "treatment",
        "outcome",
        "claim_policy",
        "candidate_adjustment_sets",
    ]
    missing = [field for field in required if field not in adjustment_spec]
    checks = [
        make_check(
            "adjustment_spec_required_fields",
            not missing,
            "Adjustment spec содержит обязательные поля.",
            sample=missing or None,
        )
    ]

    alignment_errors = []
    for field in ["graph_id", "question_id"]:
        if adjustment_spec.get(field) != dag.get(field):
            alignment_errors.append(
                {
                    "field": field,
                    "adjustment_spec": adjustment_spec.get(field),
                    "dag": dag.get(field),
                }
            )
    checks.append(
        make_check(
            "adjustment_spec_aligns_with_graph",
            not alignment_errors,
            "Adjustment spec относится к тому же graph/question.",
            sample=alignment_errors or None,
        )
    )

    status_mismatches = [
        {
            "set_id": item["set_id"],
            "declared_status": item["declared_status"],
            "calculated_status": item["calculated_status"],
        }
        for item in evaluated_sets
        if item["declared_status"] != item["calculated_status"]
    ]
    checks.append(
        make_check(
            "candidate_statuses_match_graph",
            not status_mismatches,
            "Declared statuses candidate adjustment sets совпадают с DAG-аудитом.",
            sample=status_mismatches or None,
        )
    )

    primary_sets = [item for item in evaluated_sets if item["is_primary_recommendation"]]
    checks.append(
        make_check(
            "exactly_one_primary_recommendation",
            len(primary_sets) == 1,
            "Ровно один candidate set объявлен primary recommendation.",
            sample=[item["set_id"] for item in primary_sets] if len(primary_sets) != 1 else None,
        )
    )

    primary = primary_sets[0] if len(primary_sets) == 1 else None
    primary_errors: list[dict[str, Any]] = []
    if primary:
        if primary["unknown_variables"]:
            primary_errors.append(
                {"reason": "unknown_variables", "items": primary["unknown_variables"]}
            )
        if primary["forbidden_variables"]:
            primary_errors.append(
                {"reason": "forbidden_variables", "items": primary["forbidden_variables"]}
            )
        if primary["unobserved_variables"]:
            primary_errors.append(
                {"reason": "unobserved_variables", "items": primary["unobserved_variables"]}
            )
        if primary["open_measured_backdoor_paths"] != 0:
            primary_errors.append(
                {
                    "reason": "measured_backdoors_still_open",
                    "count": primary["open_measured_backdoor_paths"],
                }
            )
    checks.append(
        make_check(
            "primary_recommendation_is_observed_baseline_and_blocks_measured_paths",
            not primary_errors and primary is not None,
            "Primary recommendation использует observed baseline variables "
            "и закрывает measured backdoor paths.",
            sample=primary_errors or None,
        )
    )

    claim_policy = adjustment_spec.get("claim_policy", {})
    unsupported_claim = []
    if primary and primary["open_unmeasured_backdoor_paths"] > 0:
        if (
            claim_policy.get("identification_status")
            != "not_identified_due_to_unmeasured_confounding"
        ):
            unsupported_claim.append(
                {
                    "field": "identification_status",
                    "value": claim_policy.get("identification_status"),
                    "expected": "not_identified_due_to_unmeasured_confounding",
                }
            )
        if claim_policy.get("allowed_effect_claim") is not False:
            unsupported_claim.append(
                {
                    "field": "allowed_effect_claim",
                    "value": claim_policy.get("allowed_effect_claim"),
                    "expected": False,
                }
            )
    checks.append(
        make_check(
            "claim_policy_matches_remaining_unmeasured_confounding",
            not unsupported_claim,
            "Claim policy не разрешает causal effect claim при remaining unmeasured confounding.",
            sample=unsupported_claim or None,
        )
    )
    return checks


def validate_specs(
    dag: dict[str, Any],
    inventory: dict[str, Any],
    adjustment_spec: dict[str, Any],
    data_contract: dict[str, Any],
    dag_tools: Any | None = None,
) -> dict[str, Any]:
    dag_tools = dag_tools or load_dag_tools()
    treatment = adjustment_spec.get("treatment")
    outcome = adjustment_spec.get("outcome")
    initial_paths = dag_tools.active_backdoor_paths(dag, treatment, outcome, set())
    evaluated_sets = [
        evaluate_candidate_set(dag, candidate, treatment, outcome, dag_tools, initial_paths)
        for candidate in adjustment_spec.get("candidate_adjustment_sets", [])
    ]
    checks = []
    checks.extend(validate_inventory(dag, inventory, data_contract, initial_paths))
    checks.extend(validate_adjustment_spec(dag, adjustment_spec, evaluated_sets))
    recommended = next((item for item in evaluated_sets if item["is_primary_recommendation"]), None)
    measured_confounders = [
        item
        for item in inventory.get("confounders", [])
        if item.get("measurement_status") == "measured"
    ]
    unmeasured_confounders = [
        item
        for item in inventory.get("confounders", [])
        if item.get("measurement_status") == "unmeasured"
    ]
    report = {
        "valid": not any(not check["valid"] and check["severity"] == "error" for check in checks),
        "summary": {
            "graph_id": dag.get("graph_id"),
            "question_id": adjustment_spec.get("question_id"),
            "estimand_id": adjustment_spec.get("estimand_id"),
            "treatment": treatment,
            "outcome": outcome,
            "active_backdoor_paths_without_adjustment": len(initial_paths),
            "backdoor_participation": backdoor_participation(dag, initial_paths),
            "measured_confounders": len(measured_confounders),
            "unmeasured_confounders": len(unmeasured_confounders),
            "forbidden_controls": len(inventory.get("forbidden_controls", [])),
            "candidate_sets": len(evaluated_sets),
            "primary_recommendation": recommended["set_id"] if recommended else None,
            "primary_variable_count": recommended["variable_count"] if recommended else None,
            "primary_open_measured_paths": recommended["open_measured_backdoor_paths"]
            if recommended
            else None,
            "primary_open_unmeasured_paths": recommended["open_unmeasured_backdoor_paths"]
            if recommended
            else None,
            "identification_status": adjustment_spec.get("claim_policy", {}).get(
                "identification_status"
            ),
        },
        "candidate_set_audits": evaluated_sets,
        "active_backdoor_path_examples": active_path_report(dag, initial_paths, limit=10),
        "checks": checks,
    }
    return report


def run(
    dag_path: str | Path,
    inventory_path: str | Path,
    adjustment_spec_path: str | Path,
    data_contract_path: str | Path,
    *,
    dag_validator_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    dag = read_json(dag_path)
    inventory = read_json(inventory_path)
    adjustment_spec = read_json(adjustment_spec_path)
    data_contract = read_json(data_contract_path)
    dag_tools = load_dag_tools(dag_validator_path)
    report = validate_specs(dag, inventory, adjustment_spec, data_contract, dag_tools)
    if output_path:
        write_json(output_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit confounders and candidate backdoor adjustment sets."
    )
    parser.add_argument("--dag", required=True, help="Path to causal_dag.json")
    parser.add_argument("--inventory", required=True, help="Path to confounder_inventory.json")
    parser.add_argument(
        "--adjustment-spec",
        required=True,
        help="Path to adjustment_set_spec.json",
    )
    parser.add_argument("--data-contract", required=True, help="Path to phase data contract")
    parser.add_argument(
        "--dag-validator",
        help="Optional path to causal_dag_validator.py from lesson 13/02",
    )
    parser.add_argument("--output", help="Optional path for backdoor_adjustment_audit.json")
    args = parser.parse_args()
    report = run(
        args.dag,
        args.inventory,
        args.adjustment_spec,
        args.data_contract,
        dag_validator_path=args.dag_validator,
        output_path=args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
