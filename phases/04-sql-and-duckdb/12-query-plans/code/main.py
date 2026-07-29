from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "plan_report.py"
DATA = ROOT.parent / "data" / "tiny" / "events.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("plan_report", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    plan_report = load_artifact()
    connection = duckdb.connect()
    try:
        report = plan_report.build_plan_report(connection, DATA)
    finally:
        connection.close()

    baseline, candidate = report["variants"]
    compact = {
        "results": [baseline["result"], candidate["result"]],
        "estimated_rows": [
            baseline["explain"]["estimated_row_markers"],
            candidate["explain"]["estimated_row_markers"],
        ],
        "actual_rows": [
            baseline["explain_analyze"]["actual_row_markers"],
            candidate["explain_analyze"]["actual_row_markers"],
        ],
        "source_read_nodes": [
            baseline["explain"]["source_read_nodes"],
            candidate["explain"]["source_read_nodes"],
        ],
        "comparison": report["comparison"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
