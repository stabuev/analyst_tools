from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_LESSON = ROOT.parent / "01-causal-question-and-estimand"
DAG = ROOT / "outputs" / "causal_dag.json"
IDENTIFICATION_MAP = ROOT / "outputs" / "identification_map.json"
QUESTION = PREVIOUS_LESSON / "outputs" / "causal_question.json"
ESTIMAND = PREVIOUS_LESSON / "outputs" / "estimand.json"
VALIDATOR_PATH = ROOT / "outputs" / "causal_dag_validator.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("causal_dag_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def main() -> None:
    validator = load_validator()
    dag = read_json(DAG)
    identification = read_json(IDENTIFICATION_MAP)
    report = validator.run(DAG, IDENTIFICATION_MAP, QUESTION, ESTIMAND)

    treatment = identification["treatment"]
    outcome = identification["outcome"]
    measured_set = next(
        item
        for item in identification["adjustment_sets"]
        if item["set_id"] == "measured_baseline_core"
    )
    measured_variables = set(measured_set["variables"])
    collider_path = [
        "assisted_within_24h",
        "opened_support_chat_after_offer",
        "friction_score",
        "activation_14d",
    ]

    no_adjustment_paths = validator.active_backdoor_paths(dag, treatment, outcome, set())
    measured_paths = validator.active_backdoor_paths(
        dag,
        treatment,
        outcome,
        measured_variables,
    )

    payload = {
        "audit_valid": report["valid"],
        "graph_id": report["summary"]["graph_id"],
        "nodes": report["summary"]["nodes"],
        "edges": report["summary"]["edges"],
        "identification_status": report["summary"]["identification_status"],
        "active_backdoor_paths_without_adjustment": len(no_adjustment_paths),
        "active_backdoor_paths_after_measured_adjustment": len(measured_paths),
        "remaining_backdoor_example": measured_paths[0],
        "intervention_operation": report["summary"]["intervention_graph"]["operation"],
        "removed_incoming_edges_to_treatment": report["summary"]["intervention_graph"][
            "removed_incoming_edges"
        ],
        "collider_path_active_without_conditioning": validator.is_path_active(
            dag,
            collider_path,
            set(),
        ),
        "collider_path_active_after_conditioning": validator.is_path_active(
            dag,
            collider_path,
            {"opened_support_chat_after_offer"},
        ),
        "warnings": [
            check["id"]
            for check in report["checks"]
            if not check["valid"] and check["severity"] == "warning"
        ],
        "blocking_checks": [
            check["id"]
            for check in report["checks"]
            if not check["valid"] and check["severity"] == "error"
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
