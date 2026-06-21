from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
PROTOCOL = ROOT / "outputs" / "experiment_protocol.json"
SPECS = ROOT / "outputs" / "metric_specs.json"
DATA_CONTRACT = PHASE_ROOT / "data" / "contract.json"
VALIDATOR_PATH = ROOT / "outputs" / "experiment_protocol_validator.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("experiment_protocol_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def manual_metric_role_map(specs: list[dict[str, Any]]) -> dict[str, list[str]]:
    roles = {"primary": [], "guardrail": [], "secondary": [], "exploratory": []}
    for spec in specs:
        role = spec["role"]
        if role in roles:
            roles[role].append(spec["metric_id"])
    return {role: sorted(metric_ids) for role, metric_ids in roles.items() if metric_ids}


def manual_missing_metric_windows(protocol: dict[str, Any], specs: list[dict[str, Any]]) -> list[str]:
    windows = protocol.get("metric_windows", {})
    return sorted(spec["metric_id"] for spec in specs if spec["metric_id"] not in windows)


def main() -> None:
    validator = load_validator()
    protocol = read_json(PROTOCOL)
    specs = validator.normalize_metric_specs(read_json(SPECS))
    role_map = manual_metric_role_map(specs)
    report = validator.run(PROTOCOL, SPECS, DATA_CONTRACT)
    payload = {
        "experiment_id": protocol["experiment_id"],
        "primary_metric": protocol["primary_metric"],
        "guardrail_metrics": protocol["guardrail_metrics"],
        "manual_metric_roles": role_map,
        "manual_missing_metric_windows": manual_missing_metric_windows(protocol, specs),
        "protocol_valid": report["valid"],
        "blocking_checks": [check["id"] for check in report["checks"] if not check["valid"]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
