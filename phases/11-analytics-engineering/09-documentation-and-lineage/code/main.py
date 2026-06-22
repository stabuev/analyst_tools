from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "documentation_lineage_auditor.py"
PROJECT = ROOT / "outputs" / "documentation_project"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"


def load_auditor():
    spec = importlib.util.spec_from_file_location("documentation_lineage_auditor", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    auditor = load_auditor()
    report = auditor.validate_project(PROJECT, DATA_CONTRACT, run_dbt=False)
    total = len(report["checks"])
    passed = sum(1 for check in report["checks"] if check["valid"])
    payload = {
        "valid": report["valid"],
        "exposure": report["summary"]["exposure"],
        "key_models": sorted(report["summary"]["key_models"]),
        "checks": f"{passed}/{total}",
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
