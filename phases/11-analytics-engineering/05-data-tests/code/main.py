from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dbt_test_reporter.py"
PROJECT = ROOT / "outputs" / "data_test_project"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"


def load_reporter():
    spec = importlib.util.spec_from_file_location("dbt_test_reporter", ARTIFACT)
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
        "generic_tests": summary["generic_counts"],
        "singular_tests": summary["singular_sql"],
        "test_statuses": summary.get("test_status_counts", {}),
        "contract_failures": summary.get("contract_failure_count"),
        "warning_diagnostics": summary.get("warning_diagnostic_count"),
        "freshness": summary.get("freshness_state_counts", {}),
        "checks": f"{sum(item['valid'] for item in report['checks'])}/{len(report['checks'])}",
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
