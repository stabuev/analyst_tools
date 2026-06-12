from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


class TableContractError(ValueError):
    """Raised when the declared table contract cannot be checked."""


def load_table(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.is_file():
        raise TableContractError(f"input file does not exist: {source}")
    return pd.read_csv(source)


def alignment_example() -> dict[str, Any]:
    price = pd.Series([100, 200], index=["order-a", "order-b"], name="price")
    discount = pd.Series([10, 20], index=["order-b", "order-c"], name="discount")
    result = price - discount
    return {
        "index": result.index.tolist(),
        "values": [None if pd.isna(value) else float(value) for value in result],
    }


def inspect_dataframe(
    frame: pd.DataFrame,
    keys: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame):
        raise TableContractError("expected a pandas DataFrame")
    declared_keys = keys or []
    missing_keys = [key for key in declared_keys if key not in frame.columns]
    if missing_keys:
        raise TableContractError(f"missing key columns: {missing_keys}")

    duplicate_key_rows = (
        int(frame.duplicated(declared_keys, keep=False).sum()) if declared_keys else None
    )
    null_key_rows = int(frame[declared_keys].isna().any(axis=1).sum()) if declared_keys else None
    return {
        "object_type": type(frame).__name__,
        "shape": list(frame.shape),
        "axes": {
            "rows": frame.index.tolist(),
            "columns": frame.columns.tolist(),
        },
        "index": {
            "type": type(frame.index).__name__,
            "name": frame.index.name,
            "is_unique": bool(frame.index.is_unique),
            "is_monotonic_increasing": bool(frame.index.is_monotonic_increasing),
        },
        "dtypes": {column: str(dtype) for column, dtype in frame.dtypes.items()},
        "null_counts": {column: int(value) for column, value in frame.isna().sum().items()},
        "memory_bytes": int(frame.memory_usage(index=True, deep=True).sum()),
        "grain": {
            "keys": declared_keys,
            "duplicate_key_rows": duplicate_key_rows,
            "null_key_rows": null_key_rows,
            "valid": (duplicate_key_rows == 0 and null_key_rows == 0 if declared_keys else None),
        },
        "alignment_example": alignment_example(),
        "copy_on_write": True,
    }


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect a DataFrame and its declared grain")
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--keys",
        default="",
        help="Comma-separated columns that define one observation",
    )
    args = parser.parse_args()
    try:
        frame = load_table(args.input)
        keys = [item.strip() for item in args.keys.split(",") if item.strip()]
        print(render_report(inspect_dataframe(frame, keys)), end="")
    except (OSError, TableContractError, pd.errors.ParserError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
