from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


class SelectionContractError(ValueError):
    """Raised when a filter cannot be applied predictably."""


def build_order_mask(
    frame: pd.DataFrame,
    *,
    statuses: set[str] | None = None,
    currencies: set[str] | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    missing: str = "exclude",
) -> pd.Series:
    required = {"status", "currency", "amount"}
    missing_columns = sorted(required - set(frame.columns))
    if missing_columns:
        raise SelectionContractError(f"missing columns: {missing_columns}")
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise SelectionContractError("min_amount cannot exceed max_amount")
    if missing not in {"exclude", "error"}:
        raise SelectionContractError("missing policy must be exclude or error")

    status = frame["status"].astype("string").str.strip().str.lower()
    currency = frame["currency"].astype("string").str.strip().str.upper()
    amount = pd.to_numeric(frame["amount"], errors="coerce")
    mask = pd.Series(True, index=frame.index, dtype="boolean")
    if statuses:
        mask &= status.isin({item.strip().lower() for item in statuses})
    if currencies:
        mask &= currency.isin({item.strip().upper() for item in currencies})
    if min_amount is not None:
        mask &= amount.ge(min_amount)
    if max_amount is not None:
        mask &= amount.le(max_amount)

    if missing == "error" and mask.isna().any():
        raise SelectionContractError("filter produced unknown truth values")
    return mask.fillna(False).astype(bool)


def select_orders(frame: pd.DataFrame, **criteria: Any) -> pd.DataFrame:
    mask = build_order_mask(frame, **criteria)
    return frame.loc[mask].copy()


def label_selected(
    frame: pd.DataFrame,
    mask: pd.Series,
    *,
    column: str = "review_status",
    value: str = "review",
) -> pd.DataFrame:
    if not mask.index.equals(frame.index):
        raise SelectionContractError("mask index must match frame index")
    result = frame.copy()
    result.loc[mask.fillna(False), column] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely filter order rows")
    parser.add_argument("input", type=Path)
    parser.add_argument("--status", action="append")
    parser.add_argument("--currency", action="append")
    parser.add_argument("--min-amount", type=float)
    parser.add_argument("--max-amount", type=float)
    args = parser.parse_args()
    try:
        frame = pd.read_csv(args.input)
        selected = select_orders(
            frame,
            statuses=set(args.status or []),
            currencies=set(args.currency or []),
            min_amount=args.min_amount,
            max_amount=args.max_amount,
        )
        report = {
            "input_rows": len(frame),
            "selected_rows": len(selected),
            "order_ids": selected.get("order_id", pd.Series(dtype="string")).tolist(),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, SelectionContractError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
