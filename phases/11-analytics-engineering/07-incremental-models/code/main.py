from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = ROOT / "outputs" / "incremental_model_auditor.py"
PROJECT = ROOT / "outputs" / "incremental_project"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"


def load_auditor():
    spec = importlib.util.spec_from_file_location("incremental_model_auditor", AUDITOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {AUDITOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    auditor = load_auditor()
    report = auditor.validate_project(PROJECT, DATA_CONTRACT, run_dbt=True)
    summary = report["summary"]
    compact = {
        "valid": report["valid"],
        "contract": summary.get("incremental_contract"),
        "initial_fct_output": summary.get("initial_fct_output"),
        "incremental_fct_output": summary.get("incremental_fct_output"),
        "final_full_refresh_output": summary.get("final_full_refresh_output"),
        "checks": f"{sum(1 for item in report['checks'] if item['valid'])}/{len(report['checks'])}",
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
