from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd


class AggregationContractError(ValueError):
    """Raised when line items cannot be rolled up without changing their meaning."""


REQUIRED_DTYPES = {
    "order_id": "string",
    "product_id": "string",
    "line_total": "Float64",
}

OUTPUT_COLUMNS = [
    "order_id",
    "line_count",
    "known_amount_lines",
    "missing_amount_lines",
    "known_amount_total",
    "order_amount",
]


def _is_missing_scalar(value: object) -> bool:
    missing = pd.isna(value)
    if not isinstance(missing, bool):
        raise AggregationContractError("line_total must contain scalar values")
    return missing


def manual_order_rollup(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build a transparent order-level control result without ``groupby``."""

    groups: dict[Any, dict[str, Any]] = {}
    for row in rows:
        order_id = row["order_id"]
        group = groups.setdefault(
            order_id,
            {
                "order_id": order_id,
                "line_count": 0,
                "known_amount_lines": 0,
                "missing_amount_lines": 0,
                "known_amount_total": 0.0,
            },
        )
        group["line_count"] += 1

        value = row["line_total"]
        if _is_missing_scalar(value):
            group["missing_amount_lines"] += 1
        else:
            group["known_amount_lines"] += 1
            group["known_amount_total"] += float(value)

    result: list[dict[str, Any]] = []
    for group in groups.values():
        known_amount = (
            group["known_amount_total"] if group["known_amount_lines"] > 0 else None
        )
        order_amount = known_amount if group["missing_amount_lines"] == 0 else None
        result.append(
            {
                "order_id": group["order_id"],
                "line_count": group["line_count"],
                "known_amount_lines": group["known_amount_lines"],
                "missing_amount_lines": group["missing_amount_lines"],
                "known_amount_total": known_amount,
                "order_amount": order_amount,
            }
        )
    return result


def _validate_input(frame: object) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise AggregationContractError("frame must be a pandas DataFrame")
    if not frame.columns.is_unique:
        raise AggregationContractError("column labels must be unique")

    missing_columns = sorted(set(REQUIRED_DTYPES) - set(frame.columns))
    if missing_columns:
        raise AggregationContractError(f"missing columns: {missing_columns}")

    wrong_dtypes = {
        column: {"expected": expected, "actual": str(frame[column].dtype)}
        for column, expected in REQUIRED_DTYPES.items()
        if str(frame[column].dtype) != expected
    }
    if wrong_dtypes:
        raise AggregationContractError(
            f"input must already satisfy the dtype contract: {wrong_dtypes}"
        )

    for column in ("order_id", "product_id"):
        blank = frame[column].str.strip().eq("").fillna(False)
        invalid = frame[column].isna() | blank
        if invalid.any():
            labels = frame.index[invalid].tolist()
            raise AggregationContractError(
                f"{column} must be non-missing and non-blank at rows: {labels}"
            )

    duplicated_items = frame.duplicated(["order_id", "product_id"], keep=False)
    if duplicated_items.any():
        labels = frame.index[duplicated_items].tolist()
        raise AggregationContractError(
            "source grain must be one row per (order_id, product_id); "
            f"duplicate rows: {labels}"
        )
    return frame


def aggregate_order_items(frame: pd.DataFrame) -> pd.DataFrame:
    """Roll typed line items up to one row per order.

    ``known_amount_total`` contains the sum of observed ``line_total`` values and remains
    missing when none are known. ``order_amount`` is stricter: it remains missing when at
    least one line amount is unknown. The input object is never modified.
    """

    source = _validate_input(frame)
    result = (
        source.groupby("order_id", as_index=False, sort=False)
        .agg(
            line_count=("product_id", "size"),
            known_amount_lines=("line_total", "count"),
            known_amount_total=("line_total", "sum"),
        )
        .astype(
            {
                "order_id": "string",
                "line_count": "Int64",
                "known_amount_lines": "Int64",
                "known_amount_total": "Float64",
            }
        )
    )

    result["missing_amount_lines"] = (
        result["line_count"] - result["known_amount_lines"]
    ).astype("Int64")
    result["known_amount_total"] = result["known_amount_total"].mask(
        result["known_amount_lines"].eq(0),
        pd.NA,
    )
    result["order_amount"] = result["known_amount_total"].mask(
        result["missing_amount_lines"].gt(0),
        pd.NA,
    ).astype("Float64")
    result = result.loc[:, OUTPUT_COLUMNS]

    if result["order_id"].duplicated().any():
        raise AggregationContractError("result grain must be one row per order_id")
    if int(result["line_count"].sum()) != len(source):
        raise AggregationContractError("line-count reconciliation failed")
    if int(result["known_amount_lines"].sum()) != int(source["line_total"].notna().sum()):
        raise AggregationContractError("known-amount reconciliation failed")
    return result
