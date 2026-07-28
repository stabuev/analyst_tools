from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "cohort_mart.py"
DATA = ROOT.parent / "data" / "tiny"


def load_artifact():
    spec = importlib.util.spec_from_file_location("cohort_mart", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manual_december = {
        "cohort_size": 2,
        "period_1_active": 2,
        "period_1_retention": 1.0,
    }
    report = load_artifact().build_cohort_mart(
        DATA / "users.csv",
        DATA / "events.csv",
    )
    print(json.dumps({"manual": manual_december, "duckdb": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
