from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "order_item_rollup.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("order_item_rollup", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_transformed_items() -> pd.DataFrame:
    """Return an already typed line-item table like the output of lesson 03/04."""

    return pd.DataFrame(
        {
            "order_id": ["O1001", "O1001", "O1002", "O1003", "O1004"],
            "product_id": ["P01", "P02", "P03", "P04", "P05"],
            "line_total": [800.0, 800.0, pd.NA, 75.5, 0.0],
        },
        index=["item-a", "item-b", "item-c", "item-d", "item-e"],
    ).astype(
        {
            "order_id": "string",
            "product_id": "string",
            "line_total": "Float64",
        }
    )


def main() -> None:
    rollup = load_artifact()
    result = rollup.aggregate_order_items(build_transformed_items())
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
