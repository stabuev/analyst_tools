from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = ROOT / "outputs" / "macro_review_auditor.py"
PROJECT = ROOT / "outputs" / "macro_project"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"


def load_auditor():
    spec = importlib.util.spec_from_file_location("macro_review_auditor", AUDITOR_PATH)
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
        "macro_calls": summary.get("macro_calls"),
        "compiled_models": summary.get("compiled_file_count"),
        "compiled_mart_line_count": summary.get("compiled_mart_line_count"),
        "mart_output": summary.get("mart_output"),
        "checks": f"{sum(1 for item in report['checks'] if item['valid'])}/{len(report['checks'])}",
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
