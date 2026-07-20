from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "safe_selection.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("safe_selection", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_example() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": pd.array(
                ["O1001", "O1002", "O1003", "O1004", "O1005"],
                dtype="string",
            ),
            "status": pd.array(
                ["paid", "paid", "refunded", pd.NA, "refunded"],
                dtype="string",
            ),
            "amount": pd.array(
                [120.0, pd.NA, 80.0, 100.0, pd.NA],
                dtype="Float64",
            ),
        },
        index=["row-a", "row-b", "row-c", "row-d", "row-e"],
    )


def main() -> None:
    selection = load_artifact()
    orders = build_example()
    mask = selection.build_order_mask(
        orders,
        statuses={"paid"},
        min_amount=70,
    )
    selected, report = selection.select_rows(
        orders,
        mask,
        columns=["order_id", "status", "amount"],
        missing="exclude",
    )
    labeled, _ = selection.label_rows(orders, mask, missing="exclude")

    print("Unresolved nullable mask:")
    print(mask.to_string())
    print("\nSelection report:")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\nSelected rows:")
    print(selected.to_string())
    print("\nLabeled copy:")
    print(labeled[["order_id", "review_status"]].to_string())


if __name__ == "__main__":
    main()
