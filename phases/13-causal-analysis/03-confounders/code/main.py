from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
DAG = PHASE_ROOT / "02-causal-dags" / "outputs" / "causal_dag.json"
INVENTORY = ROOT / "outputs" / "confounder_inventory.json"
ADJUSTMENT_SPEC = ROOT / "outputs" / "adjustment_set_spec.json"
DATA_CONTRACT = PHASE_ROOT / "data" / "contract.json"
AUDITOR_PATH = ROOT / "outputs" / "backdoor_adjustment_auditor.py"


def load_auditor():
    spec = importlib.util.spec_from_file_location("backdoor_adjustment_auditor", AUDITOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {AUDITOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def main() -> None:
    auditor = load_auditor()
    report = auditor.run(DAG, INVENTORY, ADJUSTMENT_SPEC, DATA_CONTRACT)
    inventory = read_json(INVENTORY)
    recommended = next(
        candidate
        for candidate in report["candidate_set_audits"]
        if candidate["is_primary_recommendation"]
    )
    naive = next(
        candidate for candidate in report["candidate_set_audits"] if candidate["set_id"] == "none"
    )
    payload = {
        "audit_valid": report["valid"],
        "active_backdoor_paths_without_adjustment": report["summary"][
            "active_backdoor_paths_without_adjustment"
        ],
        "measured_confounders": [
            item["variable"]
            for item in inventory["confounders"]
            if item["measurement_status"] == "measured"
        ],
        "unmeasured_confounders": [
            item["variable"]
            for item in inventory["confounders"]
            if item["measurement_status"] == "unmeasured"
        ],
        "forbidden_controls": [item["variable"] for item in inventory["forbidden_controls"]],
        "naive_open_measured_paths": naive["open_measured_backdoor_paths"],
        "recommended_set_id": recommended["set_id"],
        "recommended_variable_count": recommended["variable_count"],
        "recommended_open_measured_paths": recommended["open_measured_backdoor_paths"],
        "recommended_open_unmeasured_paths": recommended["open_unmeasured_backdoor_paths"],
        "remaining_unmeasured_path": recommended["remaining_path_examples"][0]["path"],
        "identification_status": report["summary"]["identification_status"],
        "blocking_checks": [
            check["id"]
            for check in report["checks"]
            if not check["valid"] and check["severity"] == "error"
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
