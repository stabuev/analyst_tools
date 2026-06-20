from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_SPEC_FIELDS = {
    "metric_id",
    "question",
    "owner",
    "role",
    "grain",
    "eligible_population",
    "numerator",
    "denominator",
    "window",
    "filters",
    "dimensions",
    "expected_direction",
    "guardrails",
    "known_failure_modes",
    "source_tables",
    "validation_checks",
}
ROLES = {"outcome", "input", "guardrail"}
STANDARD_DIRECTIONS = {"up", "down", "neutral"}
GUARDRAIL_DIRECTIONS = {"up_is_bad", "down_is_bad"}


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"id": check_id, "valid": True, "observed": observed, "expected": expected, "sample": []}


def failed(
    check_id: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def normalize_specs(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("metrics"), list):
        value = value["metrics"]
    if not isinstance(value, list):
        raise ValueError("metric specs must be a list or an object with a metrics list")
    specs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("each metric spec must be an object")
        specs.append(item)
    return specs


def non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def metric_ids_from_nodes(nodes: list[dict[str, Any]]) -> list[str]:
    return [node.get("metric_id", "") for node in nodes if isinstance(node.get("metric_id"), str)]


def validate_tree(tree: dict[str, Any], specs: list[dict[str, Any]]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    nodes = tree.get("nodes")
    edges = tree.get("edges", [])
    if not isinstance(nodes, list) or not nodes:
        checks.append(failed("metric_nodes_present", 0, "at least one metric node"))
        nodes = []
    else:
        checks.append(passed("metric_nodes_present", len(nodes), "at least one metric node"))
    if not isinstance(edges, list):
        checks.append(failed("metric_edges_list", type(edges).__name__, "list"))
        edges = []
    else:
        checks.append(passed("metric_edges_list", len(edges), "list"))

    ids = metric_ids_from_nodes(nodes)
    duplicate_ids = sorted({metric_id for metric_id in ids if ids.count(metric_id) > 1})
    if duplicate_ids:
        checks.append(failed("metric_ids_unique", len(ids) - len(set(ids)), "0 duplicates", duplicate_ids))
    else:
        checks.append(passed("metric_ids_unique", len(ids), "unique metric_id values"))

    node_by_id = {
        node["metric_id"]: node
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("metric_id"), str)
    }
    roles = {role: 0 for role in ROLES}
    invalid_roles: list[dict[str, Any]] = []
    for node in nodes:
        role = node.get("role") if isinstance(node, dict) else None
        metric_id = node.get("metric_id") if isinstance(node, dict) else None
        if role in ROLES:
            roles[role] += 1
        else:
            invalid_roles.append({"metric_id": metric_id, "role": role})
    missing_roles = sorted(role for role, count in roles.items() if count == 0)
    if missing_roles or invalid_roles:
        checks.append(failed("metric_roles_present", roles, "outcome, input and guardrail", missing_roles + invalid_roles))
    else:
        checks.append(passed("metric_roles_present", roles, "outcome, input and guardrail"))

    edge_errors: list[dict[str, Any]] = []
    for edge in edges:
        if not isinstance(edge, dict):
            edge_errors.append({"edge": edge, "reason": "not an object"})
            continue
        source = edge.get("from")
        target = edge.get("to")
        if source not in node_by_id or target not in node_by_id or source == target:
            edge_errors.append({"from": source, "to": target})
    if edge_errors:
        checks.append(failed("metric_edges_resolve", len(edge_errors), "all edges reference existing different nodes", edge_errors))
    else:
        checks.append(passed("metric_edges_resolve", len(edges), "all edges reference existing different nodes"))

    spec_by_id = {
        spec.get("metric_id"): spec
        for spec in specs
        if isinstance(spec.get("metric_id"), str)
    }
    missing_specs = sorted(set(node_by_id) - set(spec_by_id))
    extra_specs = sorted(set(spec_by_id) - set(node_by_id))
    if missing_specs or extra_specs:
        checks.append(failed("metric_specs_match_tree", {"missing": missing_specs, "extra": extra_specs}, "one spec per tree node", missing_specs + extra_specs))
    else:
        checks.append(passed("metric_specs_match_tree", len(spec_by_id), "one spec per tree node"))

    missing_fields: list[dict[str, Any]] = []
    denominator_errors: list[str] = []
    source_errors: list[str] = []
    validation_errors: list[str] = []
    direction_errors: list[dict[str, Any]] = []
    spec_role_errors: list[dict[str, Any]] = []
    guardrail_reference_errors: list[dict[str, Any]] = []
    guardrail_ids = {
        metric_id for metric_id, node in node_by_id.items() if node.get("role") == "guardrail"
    }

    for spec in specs:
        metric_id = spec.get("metric_id", "<missing>")
        missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
        if missing:
            missing_fields.append({"metric_id": metric_id, "missing": missing})
        if not non_empty_text(spec.get("denominator")):
            denominator_errors.append(str(metric_id))
        if not non_empty_list(spec.get("source_tables")):
            source_errors.append(str(metric_id))
        if not non_empty_list(spec.get("validation_checks")):
            validation_errors.append(str(metric_id))
        node_role = node_by_id.get(metric_id, {}).get("role")
        if node_role is not None and spec.get("role") != node_role:
            spec_role_errors.append({"metric_id": metric_id, "node_role": node_role, "spec_role": spec.get("role")})
        direction = spec.get("expected_direction")
        if spec.get("role") == "guardrail":
            if direction not in GUARDRAIL_DIRECTIONS:
                direction_errors.append({"metric_id": metric_id, "expected_direction": direction})
        elif direction not in STANDARD_DIRECTIONS:
            direction_errors.append({"metric_id": metric_id, "expected_direction": direction})
        for guardrail in spec.get("guardrails", []):
            if guardrail not in guardrail_ids:
                guardrail_reference_errors.append({"metric_id": metric_id, "guardrail": guardrail})

    if missing_fields:
        checks.append(failed("metric_spec_required_fields", len(missing_fields), "all required fields present", missing_fields))
    else:
        checks.append(passed("metric_spec_required_fields", len(specs), "all required fields present"))
    if denominator_errors:
        checks.append(failed("metric_denominator_defined", len(denominator_errors), "each metric has explicit denominator", denominator_errors))
    else:
        checks.append(passed("metric_denominator_defined", len(specs), "each metric has explicit denominator"))
    if source_errors:
        checks.append(failed("metric_sources_declared", len(source_errors), "each metric declares source tables", source_errors))
    else:
        checks.append(passed("metric_sources_declared", len(specs), "each metric declares source tables"))
    if validation_errors:
        checks.append(failed("metric_validation_checks", len(validation_errors), "each metric declares validation checks", validation_errors))
    else:
        checks.append(passed("metric_validation_checks", len(specs), "each metric declares validation checks"))
    if spec_role_errors:
        checks.append(failed("metric_spec_role_matches_tree", len(spec_role_errors), "spec role equals tree node role", spec_role_errors))
    else:
        checks.append(passed("metric_spec_role_matches_tree", len(specs), "spec role equals tree node role"))
    if direction_errors:
        checks.append(failed("metric_direction_declared", len(direction_errors), "standard directions and explicit guardrail risk direction", direction_errors))
    else:
        checks.append(passed("metric_direction_declared", len(specs), "standard directions and explicit guardrail risk direction"))
    if guardrail_reference_errors:
        checks.append(failed("metric_guardrails_resolve", len(guardrail_reference_errors), "guardrails reference guardrail metric nodes", guardrail_reference_errors))
    else:
        checks.append(passed("metric_guardrails_resolve", len(specs), "guardrails reference guardrail metric nodes"))

    valid = all(check["valid"] for check in checks)
    return {
        "valid": valid,
        "checks": checks,
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "metrics": len(specs),
            "roles": roles,
        },
    }


def run(tree_path: Path, specs_path: Path) -> dict[str, Any]:
    tree = read_json(tree_path)
    specs = normalize_specs(read_json(specs_path))
    if not isinstance(tree, dict):
        raise ValueError("metric tree must be an object")
    return validate_tree(tree, specs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a product metric tree and metric specs")
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--specs", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run(args.tree, args.specs)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
