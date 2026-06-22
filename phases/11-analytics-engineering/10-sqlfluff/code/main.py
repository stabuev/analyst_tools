from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "sqlfluff_quality_gate.py"
PROJECT = ROOT / "outputs" / "sqlfluff_project"
BAD_EXAMPLE = ROOT / "outputs" / "bad_style_example.sql"


def load_gate():
    spec = importlib.util.spec_from_file_location("sqlfluff_quality_gate", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    gate = load_gate()
    report = gate.validate_project(PROJECT, BAD_EXAMPLE, run_lint=False)
    payload = {
        "valid": report["valid"],
        "sql_files": report["summary"]["sql_files"],
        "checks": f"{sum(1 for item in report['checks'] if item['valid'])}/{len(report['checks'])}",
        "style_gate": "sqlfluff lint models tests snapshots",
        "semantic_gate": "dbt test --select test_type:data",
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
