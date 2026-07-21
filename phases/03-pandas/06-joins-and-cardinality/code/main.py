from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "safe_merge.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("safe_merge", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_orders() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["O1001", "O1002", "O1003", "O1004", "O1005"],
            "amount": [1200.0, 800.0, 5500.0, pd.NA, 49.99],
        }
    ).astype({"order_id": "string", "amount": "Float64"})


def build_order_rollup() -> pd.DataFrame:
    """Return a typed table with the exact output contract of lesson 03/05."""

    return pd.DataFrame(
        {
            "order_id": ["O1001", "O1002", "O1003", "O1004"],
            "line_count": [2, 1, 1, 1],
            "known_amount_lines": [2, 0, 1, 1],
            "missing_amount_lines": [0, 1, 0, 0],
            "known_amount_total": [1600.0, pd.NA, 75.5, 0.0],
            "order_amount": [1600.0, pd.NA, 75.5, 0.0],
        }
    ).astype(
        {
            "order_id": "string",
            "line_count": "Int64",
            "known_amount_lines": "Int64",
            "missing_amount_lines": "Int64",
            "known_amount_total": "Float64",
            "order_amount": "Float64",
        }
    )


def main() -> None:
    merge = load_artifact()
    result, report = merge.attach_order_rollup(build_orders(), build_order_rollup())
    print(report)
    print(
        result[
            [
                "order_id",
                "amount",
                "line_count",
                "order_amount",
                "items_match",
            ]
        ].to_string(index=False)
    )


if __name__ == "__main__":
    main()
