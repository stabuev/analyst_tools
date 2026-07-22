from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "batch_concat.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("batch_concat", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def typed_orders(
    order_ids: list[str], statuses: list[str], amounts: list[object]
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": order_ids,
            "status": statuses,
            "amount": amounts,
        }
    ).astype({"order_id": "string", "status": "string", "amount": "Float64"})


def main() -> None:
    concat = load_artifact()
    batches = {
        "part-02": typed_orders(
            ["O1003", "O1004"], ["refunded", "paid"], [5500.0, pd.NA]
        ),
        "part-01": typed_orders(
            ["O1001", "O1002"], ["paid", "paid"], [1200.0, 800.0]
        ),
    }
    result, audit = concat.concat_batches(batches, key=["order_id"])

    print("AUDIT")
    print(audit)
    print("\nORDERS: one row per order_id")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
