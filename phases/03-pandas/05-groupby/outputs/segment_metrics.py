from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd


class AggregationContractError(ValueError):
    """Raised when source or result grain is ambiguous."""


def manual_group_sum(
    rows: Iterable[dict[str, Any]],
    *,
    key: str,
    value: str,
) -> dict[Any, float]:
    totals: dict[Any, float] = defaultdict(float)
    for row in rows:
        if row[value] is not None:
            totals[row[key]] += float(row[value])
    return dict(totals)


def aggregate_paid_orders(
    frame: pd.DataFrame,
    group_by: list[str],
) -> pd.DataFrame:
    required = {"order_id", "status", "amount", *group_by}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise AggregationContractError(f"missing columns: {missing}")
    if not group_by:
        raise AggregationContractError("group_by must contain at least one column")
    if frame["order_id"].isna().any() or not frame["order_id"].is_unique:
        raise AggregationContractError("source grain must be one row per order_id")

    normalized = frame.assign(
        status=frame["status"].astype("string").str.strip().str.lower(),
        amount=pd.to_numeric(frame["amount"], errors="coerce").astype("Float64"),
    )
    paid = normalized.loc[normalized["status"].eq("paid")].copy()
    named_aggregations: dict[str, pd.NamedAgg] = {
        "paid_orders": pd.NamedAgg(column="order_id", aggfunc="nunique"),
        "paid_amount": pd.NamedAgg(column="amount", aggfunc="sum"),
        "average_order_value": pd.NamedAgg(column="amount", aggfunc="mean"),
    }
    if "user_id" in paid.columns:
        named_aggregations["paying_users"] = pd.NamedAgg(
            column="user_id",
            aggfunc="nunique",
        )
    result = (
        paid.groupby(group_by, dropna=False, observed=True).agg(**named_aggregations).reset_index()
    )
    if result.duplicated(group_by).any():
        raise AggregationContractError("result grain is not unique")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate paid orders by declared grain")
    parser.add_argument("input", type=Path)
    parser.add_argument("--group-by", required=True)
    args = parser.parse_args()
    try:
        frame = pd.read_csv(args.input)
        group_by = [item.strip() for item in args.group_by.split(",") if item.strip()]
        result = aggregate_paid_orders(frame, group_by)
        payload = {
            "grain": group_by,
            "rows": len(result),
            "records": json.loads(result.to_json(orient="records")),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except (OSError, AggregationContractError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
