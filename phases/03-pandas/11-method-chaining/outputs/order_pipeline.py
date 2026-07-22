from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


class PipelineContractError(ValueError):
    """Raised when a pipeline stage breaks its declared invariant."""


def validate_order_grain(frame: pd.DataFrame) -> pd.DataFrame:
    if "order_id" not in frame:
        raise PipelineContractError("missing order_id")
    if frame["order_id"].isna().any() or not frame["order_id"].is_unique:
        raise PipelineContractError("expected one row per non-null order_id")
    return frame


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"status", "currency", "amount"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PipelineContractError(f"missing columns: {missing}")
    return frame.assign(
        status=lambda value: value["status"].astype("string").str.strip().str.lower(),
        currency=lambda value: value["currency"].astype("string").str.strip().str.upper(),
        amount=lambda value: pd.to_numeric(
            value["amount"],
            errors="coerce",
        ).astype("Float64"),
    )


def add_time_columns(
    frame: pd.DataFrame,
    *,
    timezone: str,
) -> pd.DataFrame:
    if "ordered_at" not in frame:
        raise PipelineContractError("missing ordered_at")
    source = frame["ordered_at"].astype("string")
    utc = pd.to_datetime(source, errors="coerce", format="mixed", utc=True)
    invalid = source.notna() & source.str.strip().ne("") & utc.isna()
    if invalid.any():
        raise PipelineContractError("ordered_at contains invalid timestamps")
    try:
        local = utc.dt.tz_convert(timezone)
    except (TypeError, ValueError, KeyError) as error:
        raise PipelineContractError(f"invalid timezone: {timezone}") from error
    return frame.assign(
        ordered_at_utc=utc,
        local_order_date=local.dt.date,
    )


def add_paid_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.assign(
        is_paid=lambda value: value["status"].eq("paid").astype("boolean"),
        paid_amount=lambda value: (
            value["amount"].where(value["status"].eq("paid"), 0).astype("Float64")
        ),
    )


def check_invariants(frame: pd.DataFrame) -> pd.DataFrame:
    validate_order_grain(frame)
    if frame.loc[frame["is_paid"], "paid_amount"].ne(frame.loc[frame["is_paid"], "amount"]).any():
        raise PipelineContractError("paid rows must preserve amount")
    if frame.loc[~frame["is_paid"], "paid_amount"].ne(0).any():
        raise PipelineContractError("non-paid rows must contribute zero")
    return frame


def prepare_orders(frame: pd.DataFrame, *, timezone: str) -> pd.DataFrame:
    return (
        frame.copy()
        .pipe(validate_order_grain)
        .pipe(normalize_columns)
        .pipe(add_time_columns, timezone=timezone)
        .pipe(add_paid_metrics)
        .pipe(check_invariants)
        .sort_values("order_id")
        .reset_index(drop=True)
    )


def pipeline_report(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": len(frame),
        "grain": ["order_id"],
        "paid_orders": int(frame["is_paid"].sum()),
        "missing_ordered_at": int(frame["ordered_at_utc"].isna().sum()),
        "columns": frame.columns.tolist(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a checked pandas order pipeline")
    parser.add_argument("orders", type=Path)
    parser.add_argument("--timezone", required=True)
    args = parser.parse_args()
    try:
        result = prepare_orders(
            pd.read_csv(args.orders),
            timezone=args.timezone,
        )
        print(json.dumps(pipeline_report(result), ensure_ascii=False, indent=2))
    except (OSError, PipelineContractError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
