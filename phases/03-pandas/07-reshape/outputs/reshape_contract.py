from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


class ReshapeContractError(ValueError):
    """Raised when reshape would lose identity or require hidden aggregation."""


def to_long(
    frame: pd.DataFrame,
    *,
    id_vars: list[str],
    value_vars: list[str],
    variable_name: str = "metric",
    value_name: str = "value",
) -> pd.DataFrame:
    missing = sorted((set(id_vars) | set(value_vars)) - set(frame.columns))
    if missing:
        raise ReshapeContractError(f"missing columns: {missing}")
    if frame[id_vars].isna().any(axis=1).any():
        raise ReshapeContractError("identifier columns contain nulls")
    return frame.melt(
        id_vars=id_vars,
        value_vars=value_vars,
        var_name=variable_name,
        value_name=value_name,
    )


def pivot_unique(
    frame: pd.DataFrame,
    *,
    index: list[str],
    columns: str,
    values: str,
) -> pd.DataFrame:
    required = set(index) | {columns, values}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ReshapeContractError(f"missing columns: {missing}")
    cell_keys = [*index, columns]
    duplicates = frame.duplicated(cell_keys, keep=False)
    if duplicates.any():
        raise ReshapeContractError(
            f"pivot cells are not unique: {int(duplicates.sum())} conflicting rows"
        )
    return frame.pivot(index=index, columns=columns, values=values).reset_index()


def build_status_matrix(orders: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"user_id", "status", "order_id"}
    missing = sorted(required - set(orders.columns))
    if missing:
        raise ReshapeContractError(f"missing order columns: {missing}")
    normalized = orders.assign(status=orders["status"].astype("string").str.strip().str.lower())
    long = normalized.groupby(["user_id", "status"], as_index=False, observed=True).agg(
        orders=("order_id", "nunique")
    )
    wide = pivot_unique(
        long,
        index=["user_id"],
        columns="status",
        values="orders",
    ).fillna(0)
    return long, wide


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a checked long and wide status table")
    parser.add_argument("orders", type=Path)
    args = parser.parse_args()
    try:
        long, wide = build_status_matrix(pd.read_csv(args.orders))
        report = {
            "long_rows": len(long),
            "wide_rows": len(wide),
            "wide_columns": wide.columns.tolist(),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, ReshapeContractError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
