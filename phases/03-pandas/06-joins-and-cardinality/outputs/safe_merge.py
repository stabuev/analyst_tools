from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


class MergeContractError(ValueError):
    """Raised when merge keys or cardinality violate the declared contract."""


def assert_unique_key(frame: pd.DataFrame, keys: list[str], label: str) -> None:
    missing = sorted(set(keys) - set(frame.columns))
    if missing:
        raise MergeContractError(f"{label} misses key columns: {missing}")
    if frame[keys].isna().any(axis=1).any():
        raise MergeContractError(f"{label} key contains nulls")
    if frame.duplicated(keys).any():
        raise MergeContractError(f"{label} key is not unique")


def safe_merge(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    on: list[str],
    how: str,
    validate: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    try:
        merged = left.merge(
            right,
            on=on,
            how=how,
            validate=validate,
            indicator=True,
        )
    except pd.errors.MergeError as error:
        raise MergeContractError(str(error)) from error
    counts = merged["_merge"].value_counts().to_dict()
    report = {
        "on": on,
        "how": how,
        "validate": validate,
        "left_rows": len(left),
        "right_rows": len(right),
        "result_rows": len(merged),
        "matched": int(counts.get("both", 0)),
        "left_only": int(counts.get("left_only", 0)),
        "right_only": int(counts.get("right_only", 0)),
    }
    return merged.drop(columns="_merge"), report


def attach_item_totals(
    orders: pd.DataFrame,
    items: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    assert_unique_key(orders, ["order_id"], "orders")
    required = {"order_id", "quantity", "unit_price"}
    missing = sorted(required - set(items.columns))
    if missing:
        raise MergeContractError(f"items misses columns: {missing}")
    prepared = items.assign(
        quantity=pd.to_numeric(items["quantity"], errors="raise"),
        unit_price=pd.to_numeric(items["unit_price"], errors="raise"),
    )
    item_totals = (
        prepared.assign(line_total=prepared["quantity"] * prepared["unit_price"])
        .groupby("order_id", as_index=False, observed=True)
        .agg(item_rows=("order_id", "size"), item_total=("line_total", "sum"))
    )
    assert_unique_key(item_totals, ["order_id"], "item_totals")
    orphan_orders = sorted(set(item_totals["order_id"]) - set(orders["order_id"]))
    if orphan_orders:
        raise MergeContractError(f"items reference unknown orders: {orphan_orders}")
    merged, report = safe_merge(
        orders,
        item_totals,
        on=["order_id"],
        how="left",
        validate="one_to_one",
    )
    if len(merged) != len(orders):
        raise MergeContractError("order grain changed after merge")
    report["grain_preserved"] = True
    return merged, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Attach item totals with cardinality checks")
    parser.add_argument("orders", type=Path)
    parser.add_argument("items", type=Path)
    args = parser.parse_args()
    try:
        merged, report = attach_item_totals(
            pd.read_csv(args.orders),
            pd.read_csv(args.items),
        )
        report["orders_with_multiple_items"] = int(merged["item_rows"].gt(1).sum())
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, ValueError, MergeContractError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
