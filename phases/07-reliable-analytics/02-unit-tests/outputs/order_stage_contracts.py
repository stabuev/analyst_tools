from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

ORDER_COLUMNS = {
    "order_id",
    "user_id",
    "ordered_at",
    "status",
    "currency",
    "amount_rub",
}
USER_COLUMNS = {"user_id", "registered_at", "country", "plan"}
ITEM_COLUMNS = {"order_id", "line_number", "product_id", "quantity", "unit_price_rub"}
STATUSES = {"paid", "refunded", "cancelled", "pending"}


class StageContractError(ValueError):
    def __init__(self, check_id: str, details: Any) -> None:
        self.check_id = check_id
        self.details = details
        super().__init__(f"{check_id}: {details}")


def require_columns(frame: pd.DataFrame, expected: set[str], stage: str) -> None:
    missing = sorted(expected - set(frame.columns))
    if missing:
        raise StageContractError(f"{stage}.required_columns", missing)


def money_to_kopecks(value: Any) -> int:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise StageContractError("orders.amount_domain", value) from error
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise StageContractError("orders.amount_domain", value)
    return int(amount * 100)


def normalize_orders(orders: pd.DataFrame) -> pd.DataFrame:
    require_columns(orders, ORDER_COLUMNS, "orders")
    frame = orders.copy()
    blank_keys = frame["order_id"].astype(str).str.strip().eq("") | frame["user_id"].astype(
        str
    ).str.strip().eq("")
    if blank_keys.any() or frame[["order_id", "user_id"]].isna().any(axis=None):
        raise StageContractError("orders.keys_not_blank", frame.index[blank_keys].tolist())
    duplicate_ids = sorted(
        frame.loc[frame["order_id"].duplicated(keep=False), "order_id"].astype(str).unique()
    )
    if duplicate_ids:
        raise StageContractError("orders.order_id_unique", duplicate_ids)

    frame["status"] = frame["status"].astype(str).str.strip().str.lower()
    invalid_statuses = sorted(set(frame.loc[~frame["status"].isin(STATUSES), "status"]))
    if invalid_statuses:
        raise StageContractError("orders.status_domain", invalid_statuses)
    if not frame["currency"].astype(str).str.upper().eq("RUB").all():
        raise StageContractError("orders.currency_domain", "only RUB is accepted")

    frame["ordered_at"] = pd.to_datetime(frame["ordered_at"], utc=True, errors="coerce")
    if frame["ordered_at"].isna().any():
        raise StageContractError("orders.timestamp_parseable", "invalid timestamp")
    frame["amount_kopecks"] = frame["amount_rub"].map(money_to_kopecks)
    return frame[
        ["order_id", "user_id", "ordered_at", "status", "currency", "amount_kopecks"]
    ].sort_values("order_id", ignore_index=True)


def build_order_mart(
    users: pd.DataFrame,
    orders: pd.DataFrame,
    items: pd.DataFrame,
) -> pd.DataFrame:
    require_columns(users, USER_COLUMNS, "users")
    require_columns(items, ITEM_COLUMNS, "order_items")
    normalized_orders = normalize_orders(orders)

    if users["user_id"].duplicated().any():
        raise StageContractError("users.user_id_unique", "duplicate user_id")
    item_keys = items[["order_id", "line_number"]].astype(str).agg("::".join, axis=1)
    if item_keys.duplicated().any():
        raise StageContractError("order_items.key_unique", "duplicate order_id,line_number")

    unknown_users = sorted(set(normalized_orders["user_id"]) - set(users["user_id"]))
    if unknown_users:
        raise StageContractError("orders.user_fk", unknown_users)
    unknown_orders = sorted(set(items["order_id"]) - set(normalized_orders["order_id"]))
    if unknown_orders:
        raise StageContractError("order_items.order_fk", unknown_orders)

    normalized_items = items.copy()
    normalized_items["quantity"] = pd.to_numeric(normalized_items["quantity"], errors="raise")
    normalized_items["unit_price_kopecks"] = normalized_items["unit_price_rub"].map(
        money_to_kopecks
    )
    normalized_items["line_total_kopecks"] = (
        normalized_items["quantity"].astype(int) * normalized_items["unit_price_kopecks"]
    )
    item_totals = (
        normalized_items.groupby("order_id", as_index=False)["line_total_kopecks"]
        .sum()
        .rename(columns={"line_total_kopecks": "item_total_kopecks"})
    )
    mart = normalized_orders.merge(item_totals, on="order_id", how="left", validate="one_to_one")
    mart["item_total_kopecks"] = mart["item_total_kopecks"].fillna(0).astype(int)
    mismatches = mart.loc[
        mart["amount_kopecks"].ne(mart["item_total_kopecks"]), "order_id"
    ].tolist()
    if mismatches:
        raise StageContractError("orders.items_reconcile", mismatches)
    mart["ordered_date"] = mart["ordered_at"].dt.date.astype(str)
    mart["paid_revenue_kopecks"] = mart["amount_kopecks"].where(mart["status"].eq("paid"), 0)
    return mart[
        [
            "order_id",
            "user_id",
            "ordered_at",
            "ordered_date",
            "status",
            "amount_kopecks",
            "item_total_kopecks",
            "paid_revenue_kopecks",
        ]
    ]


def build_daily_metrics(mart: pd.DataFrame) -> pd.DataFrame:
    required = {"ordered_date", "order_id", "status", "paid_revenue_kopecks"}
    require_columns(mart, required, "mart")
    metrics = (
        mart.assign(paid_order=mart["status"].eq("paid").astype(int))
        .groupby("ordered_date", as_index=False)
        .agg(
            order_count=("order_id", "count"),
            paid_order_count=("paid_order", "sum"),
            paid_revenue_kopecks=("paid_revenue_kopecks", "sum"),
        )
    )
    return metrics.sort_values("ordered_date", ignore_index=True)


def load_frames(data_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    root = Path(data_dir)
    return (
        pd.read_csv(root / "users.csv", dtype=str),
        pd.read_csv(root / "orders.csv", dtype=str),
        pd.read_csv(root / "order_items.csv", dtype=str),
    )


def run_contract_suite(data_dir: str | Path) -> dict[str, Any]:
    users, orders, items = load_frames(data_dir)
    mart = build_order_mart(users, orders, items)
    metrics = build_daily_metrics(mart)
    checks = [
        {"id": "mart.grain", "passed": mart["order_id"].is_unique, "observed": len(mart)},
        {
            "id": "mart.reconciliation",
            "passed": bool(mart["amount_kopecks"].eq(mart["item_total_kopecks"]).all()),
            "observed": int(mart["amount_kopecks"].sub(mart["item_total_kopecks"]).abs().sum()),
        },
        {
            "id": "metrics.partition",
            "passed": int(metrics["order_count"].sum()) == len(mart),
            "observed": int(metrics["order_count"].sum()),
        },
    ]
    return {
        "valid": all(check["passed"] for check in checks),
        "checks": checks,
        "summary": {
            "order_count": len(mart),
            "paid_revenue_kopecks": int(mart["paid_revenue_kopecks"].sum()),
            "metric_days": len(metrics),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run contracts at order pipeline boundaries")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run_contract_suite(args.data_dir)
    except (StageContractError, OSError, ValueError) as error:
        report = {
            "valid": False,
            "error": {
                "check_id": getattr(error, "check_id", "pipeline.input"),
                "details": getattr(error, "details", str(error)),
            },
        }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
