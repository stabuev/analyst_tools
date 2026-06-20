from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "metric_tree_validator.py"
TREE = ROOT / "outputs" / "metric_tree.json"
SPECS = ROOT / "outputs" / "metric_specs.json"


def load_validator():
    spec = importlib.util.spec_from_file_location("metric_tree_validator", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manual_role_counts(tree: dict) -> dict[str, int]:
    counts = {"outcome": 0, "input": 0, "guardrail": 0}
    for node in tree["nodes"]:
        counts[node["role"]] += 1
    return counts


def main() -> None:
    tree = json.loads(TREE.read_text(encoding="utf-8"))
    validator = load_validator()
    report = validator.run(TREE, SPECS)
    result = {
        "product_question": tree["product_question"],
        "manual_role_counts": manual_role_counts(tree),
        "validator_summary": report["summary"],
        "valid": report["valid"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
