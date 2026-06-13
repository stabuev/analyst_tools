from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "sql_mart_builder.py"
DATA = ROOT.parent / "data" / "tiny"


def load_artifact():
    spec = importlib.util.spec_from_file_location("sql_mart_builder", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    result = load_artifact().build_marts(
        DATA / "users.csv",
        DATA / "orders.csv",
        DATA / "order_items.csv",
    )
    compact = {
        "checks": result["checks"],
        "boundary": result["boundary"],
        "order_sample": result["order_mart"]["records"][:2],
        "user_sample": result["user_summary"]["records"][:2],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
