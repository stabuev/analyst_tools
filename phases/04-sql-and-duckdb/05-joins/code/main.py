from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "safe_join.py"
DATA = ROOT.parent / "data" / "tiny"


def load_artifact():
    spec = importlib.util.spec_from_file_location("safe_join", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manual = {
        "safe_paid_revenue": 5005.0,
        "fanout_extra": 2700.0,
        "reason": "O1001 and O1005 each have two item rows",
    }
    report = load_artifact().audit_join(
        DATA / "users.csv",
        DATA / "orders.csv",
        DATA / "order_items.csv",
    )
    print(json.dumps({"manual": manual, "duckdb": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
