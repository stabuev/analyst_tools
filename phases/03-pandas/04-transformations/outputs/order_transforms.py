from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


class TransformContractError(ValueError):
    """Raised when an input table does not support the declared transformation."""


def normalize_orders(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"order_id", "status", "currency", "amount"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise TransformContractError(f"missing order columns: {missing}")
    result = frame.copy()
    result["status"] = result["status"].astype("string").str.strip().str.lower()
    result["currency"] = result["currency"].astype("string").str.strip().str.upper()
    result["amount"] = pd.to_numeric(result["amount"], errors="coerce").astype("Float64")
    result["is_paid"] = result["status"].eq("paid").astype("boolean")
    result["paid_amount"] = result["amount"].where(result["is_paid"], 0).astype("Float64")
    result["amount_band"] = pd.cut(
        result["amount"],
        bins=[float("-inf"), 0, 100, 1000, float("inf")],
        labels=["zero", "small", "medium", "large"],
        right=True,
    )
    return result


def add_line_totals(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"quantity", "unit_price"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise TransformContractError(f"missing item columns: {missing}")
    result = frame.copy()
    quantity = pd.to_numeric(result["quantity"], errors="raise").astype("Int64")
    unit_price = pd.to_numeric(result["unit_price"], errors="raise").astype("Float64")
    if quantity.le(0).any() or unit_price.lt(0).any():
        raise TransformContractError("quantity must be positive and price non-negative")
    result["quantity"] = quantity
    result["unit_price"] = unit_price
    result["line_total"] = (quantity * unit_price).astype("Float64")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Vectorized order transformations")
    parser.add_argument("orders", type=Path)
    parser.add_argument("--items", type=Path)
    args = parser.parse_args()
    try:
        orders = normalize_orders(pd.read_csv(args.orders))
        report = {
            "orders": len(orders),
            "paid_orders": int(orders["is_paid"].sum()),
            "paid_amount_by_currency": {
                key: float(value)
                for key, value in orders.groupby("currency", dropna=False)["paid_amount"]
                .sum()
                .items()
            },
        }
        if args.items:
            items = add_line_totals(pd.read_csv(args.items))
            report["item_rows"] = len(items)
            report["line_total"] = float(items["line_total"].sum())
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, TransformContractError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
