from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "cte_pipeline.py"
DATA = ROOT.parent / "data" / "tiny"


def load_artifact():
    spec = importlib.util.spec_from_file_location("cte_pipeline", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manual_stages = {"raw": 12, "typed": 12, "paid": 9, "final": 9}
    report = load_artifact().run_pipeline(
        DATA / "orders.csv",
        DATA / "order_items.csv",
    )
    print(json.dumps({"manual": manual_stages, "duckdb": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
