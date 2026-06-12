from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "time_normalizer.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("time_normalizer", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    time = load_artifact()
    result = time.add_business_calendar(
        pd.read_csv(DATA),
        column="ordered_at",
        timezone="Europe/Moscow",
    )
    print(result[["order_id", "ordered_at_utc", "local_date"]].to_string(index=False))


if __name__ == "__main__":
    main()
