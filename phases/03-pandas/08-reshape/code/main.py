from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "reshape_contract.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("reshape_contract", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_wide_status_counts() -> pd.DataFrame:
    """Return an already typed table with one row per user and currency."""

    return pd.DataFrame(
        {
            "user_id": ["U1", "U2"],
            "currency": ["RUB", "RUB"],
            "paid": [2, 1],
            "refunded": [0, pd.NA],
            "pending": [1, 0],
        }
    ).astype(
        {
            "user_id": "string",
            "currency": "string",
            "paid": "Int64",
            "refunded": "Int64",
            "pending": "Int64",
        }
    )


def main() -> None:
    reshape = load_artifact()
    wide = build_wide_status_counts()
    long = reshape.to_long(
        wide,
        id_vars=["user_id", "currency"],
        value_vars=["paid", "refunded", "pending"],
        variable_name="status",
        value_name="order_count",
    )
    wide_again = reshape.pivot_unique(
        long,
        index=["user_id", "currency"],
        columns="status",
        values="order_count",
    ).loc[:, wide.columns]

    print("LONG: one row per (user_id, currency, status)")
    print(long.to_string(index=False))
    print("\nWIDE AGAIN: one row per (user_id, currency)")
    print(wide_again.to_string(index=False))


if __name__ == "__main__":
    main()
