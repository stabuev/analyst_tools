from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "materialization_reporter.py"
PROJECT = ROOT / "outputs" / "materialization_project"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"


def load_reporter():
    spec = importlib.util.spec_from_file_location("materialization_reporter", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    reporter = load_reporter()
    report = reporter.validate_project(PROJECT, DATA_CONTRACT, run_dbt=True)
    summary = report["summary"]
    compact = {
        "valid": report["valid"],
        "models": summary["models"],
        "materializations": summary["materialization_counts"],
        "physical_relations": summary.get("physical_relation_counts", {}),
        "mart_rows": summary.get("mart_row_count"),
        "checks": f"{sum(item['valid'] for item in report['checks'])}/{len(report['checks'])}",
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
