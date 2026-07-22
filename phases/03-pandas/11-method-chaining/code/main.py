from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "order_pipeline.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("order_pipeline", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    pipeline = load_artifact()
    result = pipeline.prepare_orders(
        pd.read_csv(DATA),
        timezone="Europe/Moscow",
    )
    print(result[["order_id", "status", "local_order_date", "paid_amount"]].to_string(index=False))


if __name__ == "__main__":
    main()
