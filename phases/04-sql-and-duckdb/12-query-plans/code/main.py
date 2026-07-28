from __future__ import annotations

import importlib.util
import json
from pathlib import Path

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
    report = load_artifact().compare_plans(DATA)
    compact = {
        "results": [query["result"] for query in report["queries"]],
        "scan_nodes": [query["scan_nodes"] for query in report["queries"]],
        "times": [query["total_time_seconds"] for query in report["queries"]],
        "checks": report["checks"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
