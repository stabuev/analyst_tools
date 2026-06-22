from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "source_ref_lineage_auditor.py"
PROJECT = ROOT / "outputs" / "source_ref_project"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"


def load_auditor():
    spec = importlib.util.spec_from_file_location("source_ref_lineage_auditor", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    auditor = load_auditor()
    report = auditor.validate_project(PROJECT, DATA_CONTRACT, run_dbt=False)
    summary = {
        "valid": report["valid"],
        "declared_sources": len(report["summary"].get("declared_sources", [])),
        "models": report["summary"].get("models", []),
        "checks_passed": sum(1 for check in report["checks"] if check["valid"]),
        "checks_total": len(report["checks"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
