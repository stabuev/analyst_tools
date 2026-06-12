from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "safe_selection.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("safe_selection", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    selection = load_artifact()
    orders = pd.read_csv(DATA)
    paid = selection.select_orders(orders, statuses={"paid"}, min_amount=70)
    print(paid[["order_id", "currency", "amount"]].to_string(index=False))


if __name__ == "__main__":
    main()
