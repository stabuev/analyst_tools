from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

TIMING_ORDER = {
    "unobserved_baseline": 0,
    "baseline": 0,
    "instrument": 0,
    "time_zero": 1,
    "treatment": 2,
    "post_treatment": 3,
    "mediator": 3,
    "outcome": 4,
    "selection": 5,
}

FORBIDDEN_ADJUSTMENT_ROLES = {
    "treatment",
    "outcome",
    "mediator",
    "collider",
    "selection",
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


def node_map(dag: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {node["id"]: node for node in dag.get("nodes", [])}


def edge_tuples(dag: dict[str, Any]) -> list[tuple[str, str]]:
    return [(edge.get("source"), edge.get("target")) for edge in dag.get("edges", [])]


def directed_children(dag: dict[str, Any]) -> dict[str, set[str]]:
    children: dict[str, set[str]] = defaultdict(set)
    for source, target in edge_tuples(dag):
        children[source].add(target)
        children.setdefault(target, set())
    return children


def directed_parents(dag: dict[str, Any]) -> dict[str, set[str]]:
    parents: dict[str, set[str]] = defaultdict(set)
    for source, target in edge_tuples(dag):
        parents[target].add(source)
        parents.setdefault(source, set())
    return parents


def undirected_neighbors(dag: dict[str, Any]) -> dict[str, set[str]]:
    neighbors: dict[str, set[str]] = defaultdict(set)
    for source, target in edge_tuples(dag):
        neighbors[source].add(target)
        neighbors[target].add(source)
    return neighbors


def has_edge(dag: dict[str, Any], source: str, target: str) -> bool:
    return (source, target) in set(edge_tuples(dag))


def find_cycle(dag: dict[str, Any]) -> list[str]:
    children = directed_children(dag)
    temporary: set[str] = set()
    permanent: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        if node in permanent:
            return None
        if node in temporary:
            start = stack.index(node)
            return stack[start:] + [node]
        temporary.add(node)
        stack.append(node)
        for child in sorted(children[node]):
            cycle = visit(child)
            if cycle:
                return cycle
        stack.pop()
        temporary.remove(node)
        permanent.add(node)
        return None

    for node in sorted(children):
        cycle = visit(node)
        if cycle:
            return cycle
    return []


def ancestors_of(dag: dict[str, Any], nodes: set[str]) -> set[str]:
    parents = directed_parents(dag)
    ancestors: set[str] = set()
    stack = list(nodes)
    while stack:
        node = stack.pop()
        for parent in parents[node]:
            if parent not in ancestors:
                ancestors.add(parent)
                stack.append(parent)
    return ancestors


def enumerate_simple_paths(
    dag: dict[str, Any],
    source: str,
    target: str,
    *,
    max_paths: int = 500,
) -> list[list[str]]:
    neighbors = undirected_neighbors(dag)
    paths: list[list[str]] = []
    stack: list[tuple[str, list[str]]] = [(source, [source])]
    while stack:
        node, path = stack.pop()
        if node == target:
            paths.append(path)
            if len(paths) >= max_paths:
                break
            continue
        for neighbor in sorted(neighbors[node], reverse=True):
            if neighbor in path:
                continue
            stack.append((neighbor, path + [neighbor]))
    return paths


def is_collider_on_path(dag: dict[str, Any], previous: str, current: str, next_node: str) -> bool:
    return has_edge(dag, previous, current) and has_edge(dag, next_node, current)


def is_path_active(
    dag: dict[str, Any],
    path: list[str],
    conditioned_on: set[str],
) -> bool:
    conditioned_ancestors = ancestors_of(dag, conditioned_on)
    active_collider_nodes = conditioned_on | conditioned_ancestors
    for index in range(1, len(path) - 1):
        previous = path[index - 1]
        current = path[index]
        next_node = path[index + 1]
        if is_collider_on_path(dag, previous, current, next_node):
            if current not in active_collider_nodes:
                return False
        elif current in conditioned_on:
            return False
    return True


def active_paths(
    dag: dict[str, Any],
    source: str,
    target: str,
    conditioned_on: set[str],
) -> list[list[str]]:
    return [
        path
        for path in enumerate_simple_paths(dag, source, target)
        if is_path_active(dag, path, conditioned_on)
    ]


def is_d_separated(
    dag: dict[str, Any],
    source: str,
    target: str,
    conditioned_on: set[str],
) -> bool:
    return not active_paths(dag, source, target, conditioned_on)


def is_backdoor_path(dag: dict[str, Any], path: list[str]) -> bool:
    if len(path) < 2:
        return False
    treatment = path[0]
    first_neighbor = path[1]
    return has_edge(dag, first_neighbor, treatment)


def active_backdoor_paths(
    dag: dict[str, Any],
    treatment: str,
    outcome: str,
    conditioned_on: set[str],
) -> list[list[str]]:
    return [
        path
        for path in enumerate_simple_paths(dag, treatment, outcome)
        if is_backdoor_path(dag, path) and is_path_active(dag, path, conditioned_on)
    ]


def incoming_edges(dag: dict[str, Any], node_id: str) -> list[dict[str, str]]:
    return [
        {"source": source, "target": target}
        for source, target in edge_tuples(dag)
        if target == node_id
    ]


def intervention_graph_summary(dag: dict[str, Any], treatment: str) -> dict[str, Any]:
    removed = incoming_edges(dag, treatment)
    kept_outgoing = [
        {"source": source, "target": target}
        for source, target in edge_tuples(dag)
        if source == treatment
    ]
    return {
        "operation": f"do({treatment})",
        "removed_incoming_edges": removed,
        "kept_outgoing_edges": kept_outgoing,
    }


def check_graph_fields(dag: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in ["graph_id", "nodes", "edges"] if field not in dag]
    return make_check(
        "required_graph_fields",
        not missing,
        "DAG содержит graph_id, nodes и edges.",
        sample=missing or None,
    )


def check_node_ids_unique(dag: dict[str, Any]) -> dict[str, Any]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for node in dag.get("nodes", []):
        node_id = node.get("id")
        if node_id in seen:
            duplicates.append(node_id)
        seen.add(node_id)
    return make_check(
        "node_ids_unique",
        not duplicates,
        "Идентификаторы узлов уникальны.",
        sample=duplicates or None,
    )


def check_edges_known(dag: dict[str, Any]) -> dict[str, Any]:
    nodes = set(node_map(dag))
    unknown = [
        edge
        for edge in dag.get("edges", [])
        if edge.get("source") not in nodes or edge.get("target") not in nodes
    ]
    return make_check(
        "edge_endpoints_known",
        not unknown,
        "Все ребра ссылаются на объявленные узлы.",
        sample=unknown or None,
    )


def check_acyclic(dag: dict[str, Any]) -> dict[str, Any]:
    cycle = find_cycle(dag)
    return make_check(
        "graph_is_acyclic",
        not cycle,
        "Причинный граф не содержит направленных циклов.",
        sample=cycle or None,
    )


def check_temporal_order(dag: dict[str, Any]) -> dict[str, Any]:
    nodes = node_map(dag)
    violations: list[dict[str, Any]] = []
    for edge in dag.get("edges", []):
        source = edge.get("source")
        target = edge.get("target")
        if source not in nodes or target not in nodes:
            continue
        source_order = TIMING_ORDER.get(nodes[source].get("timing"))
        target_order = TIMING_ORDER.get(nodes[target].get("timing"))
        if source_order is None or target_order is None:
            violations.append(
                {
                    "edge": [source, target],
                    "reason": "unknown timing",
                    "source_timing": nodes[source].get("timing"),
                    "target_timing": nodes[target].get("timing"),
                }
            )
        elif source_order > target_order:
            violations.append(
                {
                    "edge": [source, target],
                    "reason": "effect cannot precede its cause",
                    "source_timing": nodes[source].get("timing"),
                    "target_timing": nodes[target].get("timing"),
                }
            )
    return make_check(
        "temporal_order_respected",
        not violations,
        "Ребра направлены из более ранних или одновременных причин к более поздним следствиям.",
        sample=violations or None,
    )


def check_required_roles(dag: dict[str, Any], treatment: str, outcome: str) -> dict[str, Any]:
    nodes = node_map(dag)
    role_counts: dict[str, int] = defaultdict(int)
    for node in nodes.values():
        role_counts[node.get("role", "")] += 1
    problems: list[str] = []
    if treatment not in nodes or nodes.get(treatment, {}).get("role") != "treatment":
        problems.append("declared treatment node is missing or has wrong role")
    if outcome not in nodes or nodes.get(outcome, {}).get("role") != "outcome":
        problems.append("declared outcome node is missing or has wrong role")
    for required in ["confounder", "mediator", "collider", "selection", "unmeasured_confounder"]:
        if role_counts[required] == 0:
            problems.append(f"missing {required} node")
    return make_check(
        "required_causal_roles_present",
        not problems,
        "Граф содержит treatment, outcome, confounder, mediator, collider, "
        "selection и unmeasured confounder.",
        sample=problems or None,
    )


def check_alignment(
    dag: dict[str, Any],
    identification_map: dict[str, Any],
    question: dict[str, Any] | None,
    estimand: dict[str, Any] | None,
) -> dict[str, Any]:
    mismatches: list[dict[str, str]] = []
    if identification_map.get("graph_id") != dag.get("graph_id"):
        mismatches.append(
            {
                "field": "graph_id",
                "dag": dag.get("graph_id", ""),
                "identification_map": identification_map.get("graph_id", ""),
            }
        )
    if question and identification_map.get("question_id") != question.get("question_id"):
        mismatches.append(
            {
                "field": "question_id",
                "question": question.get("question_id", ""),
                "identification_map": identification_map.get("question_id", ""),
            }
        )
    if estimand and identification_map.get("estimand_id") != estimand.get("estimand_id"):
        mismatches.append(
            {
                "field": "estimand_id",
                "estimand": estimand.get("estimand_id", ""),
                "identification_map": identification_map.get("estimand_id", ""),
            }
        )
    return make_check(
        "question_estimand_graph_ids_align",
        not mismatches,
        "Identification map ссылается на тот же question, estimand и graph.",
        sample=mismatches or None,
    )


def check_d_separation_claims(
    dag: dict[str, Any],
    identification_map: dict[str, Any],
    treatment: str,
    outcome: str,
) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    for claim in identification_map.get("d_separation_checks", []):
        conditioned_on = set(claim.get("conditioned_on", []))
        scope = claim.get("scope", "all_paths")
        if scope == "backdoor":
            calculated = not active_backdoor_paths(dag, treatment, outcome, conditioned_on)
            expected = claim.get("expected_d_separated")
            if calculated != expected:
                mismatches.append(
                    {
                        "check_id": claim.get("check_id"),
                        "scope": scope,
                        "expected_d_separated": expected,
                        "calculated_d_separated": calculated,
                        "active_backdoor_paths": active_backdoor_paths(
                            dag, treatment, outcome, conditioned_on
                        )[:3],
                    }
                )
        elif scope == "path":
            path = claim.get("path", [])
            calculated = is_path_active(dag, path, conditioned_on)
            expected = claim.get("expected_path_active")
            if calculated != expected:
                mismatches.append(
                    {
                        "check_id": claim.get("check_id"),
                        "scope": scope,
                        "path": path,
                        "expected_path_active": expected,
                        "calculated_path_active": calculated,
                    }
                )
        else:
            source = claim.get("x", treatment)
            target = claim.get("y", outcome)
            calculated = is_d_separated(dag, source, target, conditioned_on)
            expected = claim.get("expected_d_separated")
            if calculated != expected:
                mismatches.append(
                    {
                        "check_id": claim.get("check_id"),
                        "scope": scope,
                        "expected_d_separated": expected,
                        "calculated_d_separated": calculated,
                    }
                )
    return make_check(
        "d_separation_claims_match_graph",
        not mismatches,
        "Заявленные d-separation checks совпадают со структурой графа.",
        sample=mismatches or None,
    )


def check_adjustment_sets(
    dag: dict[str, Any],
    identification_map: dict[str, Any],
    treatment: str,
    outcome: str,
) -> dict[str, Any]:
    nodes = node_map(dag)
    problems: list[dict[str, Any]] = []
    for adjustment in identification_map.get("adjustment_sets", []):
        set_id = adjustment.get("set_id")
        variables = adjustment.get("variables", [])
        unknown = [variable for variable in variables if variable not in nodes]
        if unknown:
            problems.append({"set_id": set_id, "reason": "unknown variables", "variables": unknown})
            continue
        forbidden = [
            {
                "variable": variable,
                "role": nodes[variable].get("role"),
                "timing": nodes[variable].get("timing"),
            }
            for variable in variables
            if nodes[variable].get("role") in FORBIDDEN_ADJUSTMENT_ROLES
            or nodes[variable].get("timing")
            in {"post_treatment", "mediator", "selection", "outcome"}
        ]
        unobserved = [
            variable for variable in variables if nodes[variable].get("observed") is False
        ]
        remaining = active_backdoor_paths(dag, treatment, outcome, set(variables))
        status = adjustment.get("status")
        if forbidden and status not in {
            "invalid_for_total_effect",
            "invalid_opens_collider_path",
            "invalid_post_treatment_control",
        }:
            problems.append(
                {
                    "set_id": set_id,
                    "reason": "forbidden controls are not acknowledged",
                    "variables": forbidden,
                    "status": status,
                }
            )
        if unobserved and status != "invalid_contains_unobserved_variable":
            problems.append(
                {
                    "set_id": set_id,
                    "reason": "unobserved variables cannot be used as observed adjustment",
                    "variables": unobserved,
                    "status": status,
                }
            )
        if remaining and status == "sufficient_for_backdoor_identification":
            problems.append(
                {
                    "set_id": set_id,
                    "reason": "status claims sufficiency but backdoor paths remain open",
                    "active_backdoor_paths": remaining[:3],
                }
            )
        if not remaining and status in {
            "invalid_open_backdoor_paths",
            "insufficient_due_to_unmeasured_confounding",
        }:
            problems.append(
                {
                    "set_id": set_id,
                    "reason": "status claims open backdoors but graph shows none",
                    "status": status,
                }
            )
    return make_check(
        "adjustment_sets_are_graph_consistent",
        not problems,
        "Adjustment sets используют только допустимые observed pre-treatment controls "
        "и честно описывают оставшиеся backdoor paths.",
        sample=problems or None,
    )


def check_identification_status(
    dag: dict[str, Any],
    identification_map: dict[str, Any],
    treatment: str,
    outcome: str,
) -> list[dict[str, Any]]:
    observed_sets = [
        adjustment
        for adjustment in identification_map.get("adjustment_sets", [])
        if adjustment.get("status") == "sufficient_for_backdoor_identification"
    ]
    warnings: list[dict[str, Any]] = []
    if identification_map.get("identification_status") == "identified" and not observed_sets:
        warnings.append(
            make_check(
                "identification_status_not_supported",
                False,
                "Identification map заявляет identified без достаточного observed adjustment set.",
                sample={"identification_status": identification_map.get("identification_status")},
            )
        )
    measured = next(
        (
            adjustment
            for adjustment in identification_map.get("adjustment_sets", [])
            if adjustment.get("set_id") == "measured_baseline_core"
        ),
        None,
    )
    if measured:
        remaining = active_backdoor_paths(
            dag, treatment, outcome, set(measured.get("variables", []))
        )
        latent_remaining = [
            path
            for path in remaining
            if any(node_map(dag)[node].get("observed") is False for node in path)
        ]
        if latent_remaining:
            warnings.append(
                make_check(
                    "unmeasured_confounding_blocks_backdoor_identification",
                    False,
                    "Measured adjustment закрывает наблюдаемые backdoor paths, "
                    "но оставляет путь через unmeasured confounder; это ограничение "
                    "дизайна, а не ошибка кода.",
                    severity="warning",
                    sample=latent_remaining[:3],
                )
            )
    if identification_map.get("estimator") not in {None, "not_selected"}:
        warnings.append(
            make_check(
                "estimator_selected_before_identification",
                False,
                "В уроке 13/02 estimator еще не выбирается: сначала identification, затем оценка.",
                sample={"estimator": identification_map.get("estimator")},
            )
        )
    return warnings


def validate_specs(
    dag: dict[str, Any],
    identification_map: dict[str, Any],
    question: dict[str, Any] | None = None,
    estimand: dict[str, Any] | None = None,
) -> dict[str, Any]:
    treatment = identification_map.get("treatment")
    outcome = identification_map.get("outcome")
    checks = [
        check_graph_fields(dag),
        check_node_ids_unique(dag),
        check_edges_known(dag),
        check_acyclic(dag),
        check_temporal_order(dag),
        check_required_roles(dag, treatment, outcome),
        check_alignment(dag, identification_map, question, estimand),
        check_d_separation_claims(dag, identification_map, treatment, outcome),
        check_adjustment_sets(dag, identification_map, treatment, outcome),
    ]
    checks.extend(check_identification_status(dag, identification_map, treatment, outcome))
    measured = next(
        (
            adjustment
            for adjustment in identification_map.get("adjustment_sets", [])
            if adjustment.get("set_id") == "measured_baseline_core"
        ),
        {"variables": []},
    )
    no_adjustment_backdoors = active_backdoor_paths(dag, treatment, outcome, set())
    measured_backdoors = active_backdoor_paths(
        dag,
        treatment,
        outcome,
        set(measured.get("variables", [])),
    )
    report = {
        "valid": not any(not check["valid"] and check["severity"] == "error" for check in checks),
        "summary": {
            "graph_id": dag.get("graph_id"),
            "question_id": identification_map.get("question_id"),
            "estimand_id": identification_map.get("estimand_id"),
            "treatment": treatment,
            "outcome": outcome,
            "nodes": len(dag.get("nodes", [])),
            "edges": len(dag.get("edges", [])),
            "identification_status": identification_map.get("identification_status"),
            "active_backdoor_paths_without_adjustment": len(no_adjustment_backdoors),
            "active_backdoor_paths_after_measured_adjustment": len(measured_backdoors),
            "intervention_graph": intervention_graph_summary(dag, treatment),
        },
        "checks": checks,
    }
    return report


def run(
    dag_path: str | Path,
    identification_map_path: str | Path,
    question_path: str | Path | None = None,
    estimand_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    dag = read_json(dag_path)
    identification_map = read_json(identification_map_path)
    question = read_json(question_path) if question_path else None
    estimand = read_json(estimand_path) if estimand_path else None
    report = validate_specs(dag, identification_map, question, estimand)
    if output_path:
        write_json(output_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a causal DAG and identification map.")
    parser.add_argument("--dag", required=True, help="Path to causal_dag.json")
    parser.add_argument(
        "--identification-map", required=True, help="Path to identification_map.json"
    )
    parser.add_argument("--question", help="Optional path to causal_question.json")
    parser.add_argument("--estimand", help="Optional path to estimand.json")
    parser.add_argument("--output", help="Optional path for dag_audit.json")
    args = parser.parse_args()
    report = run(
        args.dag,
        args.identification_map,
        args.question,
        args.estimand,
        args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
