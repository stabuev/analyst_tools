from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "order_transforms.py"
DATA = ROOT.parent / "data" / "tiny"


def load_artifact():
    spec = importlib.util.spec_from_file_location("order_transforms", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    transforms = load_artifact()
    orders = transforms.normalize_orders(pd.read_csv(DATA / "orders.csv"))
    print(orders[["order_id", "status", "is_paid", "paid_amount"]].to_string(index=False))


if __name__ == "__main__":
    main()
