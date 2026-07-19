from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dataframe_inspector.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact() -> Any:
    spec = importlib.util.spec_from_file_location("dataframe_inspector", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_alignment_example() -> pd.Series:
    price = pd.Series(
        [100, 200],
        index=["order-a", "order-b"],
        name="price",
    )
    discount = pd.Series(
        [10, 20],
        index=["order-b", "order-c"],
        name="discount",
    )
    return price - discount


def dataframe_series_relationship(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    series = frame[column]
    return {
        "frame_type": type(frame).__name__,
        "series_type": type(series).__name__,
        "series_name": series.name,
        "same_row_index": bool(series.index.equals(frame.index)),
    }


def main() -> None:
    inspector = load_artifact()
    orders = inspector.load_table(DATA)

    print("DataFrame -> Series")
    print(dataframe_series_relationship(orders, "amount"))
    print()

    print("Label alignment")
    print(build_alignment_example().to_string())
    print()

    print("Declared grain preflight")
    report = inspector.inspect_dataframe(orders, ["order_id"])
    print(inspector.render_report(report), end="")


if __name__ == "__main__":
    main()
