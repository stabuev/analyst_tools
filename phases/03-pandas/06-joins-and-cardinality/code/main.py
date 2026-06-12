from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "safe_merge.py"
DATA = ROOT.parent / "data" / "tiny"


def load_artifact():
    spec = importlib.util.spec_from_file_location("safe_merge", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    merge = load_artifact()
    result, report = merge.attach_item_totals(
        pd.read_csv(DATA / "orders.csv"),
        pd.read_csv(DATA / "order_items.csv"),
    )
    print(report)
    print(result[["order_id", "amount", "item_rows", "item_total"]].to_string(index=False))


if __name__ == "__main__":
    main()
