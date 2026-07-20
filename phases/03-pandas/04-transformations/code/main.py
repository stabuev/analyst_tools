from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "order_transforms.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("order_transforms", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    transforms = load_artifact()
    items = pd.DataFrame(
        {
            "order_id": ["O1001", "O1001", "O1002", "O1003", "O1004"],
            "product_id": ["P01", "P02", "P03", "P04", "P05"],
            "quantity": [2, 1, 3, 1, 1],
            "unit_price": [400.0, 800.0, pd.NA, 75.5, 0.0],
        },
        index=pd.Index(
            ["item-a", "item-b", "item-c", "item-d", "item-e"],
            name="row_label",
        ),
    ).astype(
        {
            "order_id": "string",
            "product_id": "string",
            "quantity": "Int64",
            "unit_price": "Float64",
        }
    )

    result = transforms.add_line_item_features(items, review_threshold=800.0)
    print(
        result[
            [
                "order_id",
                "product_id",
                "line_total",
                "requires_review",
                "review_amount",
            ]
        ].to_string()
    )


if __name__ == "__main__":
    main()
