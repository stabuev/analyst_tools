from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


class MartContractError(ValueError):
    """Raised when the integrated mart cannot satisfy its data contract."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_unique(frame: pd.DataFrame, keys: list[str], label: str) -> None:
    missing = sorted(set(keys) - set(frame.columns))
    if missing:
        raise MartContractError(f"{label} misses keys: {missing}")
    if frame[keys].isna().any(axis=1).any():
        raise MartContractError(f"{label} keys contain nulls")
    if frame.duplicated(keys).any():
        raise MartContractError(f"{label} keys are not unique")


def prepare_users(users: pd.DataFrame) -> pd.DataFrame:
    assert_unique(users, ["user_id"], "users")
    required = {"country", "plan"}
    missing = sorted(required - set(users.columns))
    if missing:
        raise MartContractError(f"users misses columns: {missing}")
    return users.assign(
        country=users["country"].astype("string").str.strip().str.upper(),
        plan=users["plan"].astype("string").str.strip().str.lower(),
    )


def prepare_orders(orders: pd.DataFrame) -> pd.DataFrame:
    assert_unique(orders, ["order_id"], "orders")
    required = {"user_id", "ordered_at", "status", "currency", "amount"}
    missing = sorted(required - set(orders.columns))
    if missing:
        raise MartContractError(f"orders misses columns: {missing}")
    timestamp_source = orders["ordered_at"].astype("string")
    ordered_at_utc = pd.to_datetime(
        timestamp_source,
        errors="coerce",
        format="mixed",
        utc=True,
    )
    invalid = timestamp_source.notna() & timestamp_source.str.strip().ne("") & ordered_at_utc.isna()
    if invalid.any():
        raise MartContractError("orders contains invalid timestamps")
    return orders.assign(
        status=orders["status"].astype("string").str.strip().str.lower(),
        currency=orders["currency"].astype("string").str.strip().str.upper(),
        amount=pd.to_numeric(orders["amount"], errors="coerce").astype("Float64"),
        ordered_at_utc=ordered_at_utc,
    )


def prepare_item_totals(items: pd.DataFrame) -> pd.DataFrame:
    assert_unique(items, ["order_id", "product_id"], "order_items")
    required = {"quantity", "unit_price", "category"}
    missing = sorted(required - set(items.columns))
    if missing:
        raise MartContractError(f"order_items misses columns: {missing}")
    quantity = pd.to_numeric(items["quantity"], errors="raise")
    unit_price = pd.to_numeric(items["unit_price"], errors="raise")
    if quantity.le(0).any() or unit_price.lt(0).any():
        raise MartContractError("invalid item quantity or price")
    prepared = items.assign(
        category=items["category"]
        .astype("string")
        .str.strip()
        .str.lower()
        .str.replace(r"[\s-]+", "_", regex=True)
        .replace({"addon": "add_on"}),
        line_total=quantity * unit_price,
    )
    totals = prepared.groupby("order_id", as_index=False, observed=True).agg(
        item_rows=("product_id", "size"),
        item_total=("line_total", "sum"),
        categories=("category", lambda values: "|".join(sorted(set(values.dropna())))),
    )
    assert_unique(totals, ["order_id"], "item_totals")
    return totals


def build_order_mart(
    users: pd.DataFrame,
    orders: pd.DataFrame,
    items: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    prepared_users = prepare_users(users)
    prepared_orders = prepare_orders(orders)
    item_totals = prepare_item_totals(items)
    orphan_orders = sorted(set(item_totals["order_id"]) - set(prepared_orders["order_id"]))
    if orphan_orders:
        raise MartContractError(f"order_items reference unknown orders: {orphan_orders}")

    with_items = prepared_orders.merge(
        item_totals,
        on="order_id",
        how="left",
        validate="one_to_one",
    )
    mart = with_items.merge(
        prepared_users[["user_id", "country", "plan"]],
        on="user_id",
        how="left",
        validate="many_to_one",
        indicator="user_merge",
    )
    if len(mart) != len(prepared_orders):
        raise MartContractError("mart row count differs from orders")
    assert_unique(mart, ["order_id"], "mart")
    amount_matches_items = mart["amount"].sub(mart["item_total"]).abs().le(1e-9).astype("boolean")
    amount_matches_items = amount_matches_items.where(
        mart["amount"].notna() & mart["item_total"].notna(),
        pd.NA,
    )
    mart = mart.assign(
        user_found=mart["user_merge"].eq("both").astype("boolean"),
        is_paid=mart["status"].eq("paid").astype("boolean"),
        paid_amount=mart["amount"].where(mart["status"].eq("paid"), 0).astype("Float64"),
        amount_matches_items=amount_matches_items,
    ).drop(columns="user_merge")
    mart = mart.sort_values("order_id").reset_index(drop=True)
    checks = {
        "grain_unique": bool(mart["order_id"].is_unique),
        "rows_equal_orders": len(mart) == len(orders),
        "unknown_users": int((~mart["user_found"]).sum()),
        "amount_item_mismatches": int(mart["amount_matches_items"].eq(False).sum()),
        "amount_item_unchecked": int(mart["amount_matches_items"].isna().sum()),
        "missing_amount": int(mart["amount"].isna().sum()),
        "missing_ordered_at": int(mart["ordered_at_utc"].isna().sum()),
    }
    return mart, checks


def export_mart(
    mart: pd.DataFrame,
    checks: dict[str, Any],
    output_dir: Path,
    source_paths: dict[str, Path],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    mart_path = output_dir / "order_mart.csv"
    manifest_path = output_dir / "manifest.json"
    mart.to_csv(mart_path, index=False, lineterminator="\n", date_format="%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "name": "order_mart",
        "grain": ["order_id"],
        "rows": len(mart),
        "columns": mart.columns.tolist(),
        "dtypes": {column: str(dtype) for column, dtype in mart.dtypes.items()},
        "checks": checks,
        "artifact": {
            "path": mart_path.name,
            "sha256": sha256(mart_path),
        },
        "sources": {
            name: {"path": str(path), "sha256": sha256(path)} for name, path in source_paths.items()
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and export a checked order mart")
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        source_paths = {
            "users": args.users,
            "orders": args.orders,
            "order_items": args.items,
        }
        mart, checks = build_order_mart(
            pd.read_csv(args.users),
            pd.read_csv(args.orders),
            pd.read_csv(args.items),
        )
        manifest = export_mart(mart, checks, args.output_dir, source_paths)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    except (OSError, ValueError, MartContractError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
