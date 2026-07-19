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


def inspect_dataframe(frame: pd.DataFrame, keys: list[str]) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame):
        raise TableContractError("expected a pandas DataFrame")
    if not keys:
        raise TableContractError("at least one grain key is required")

    missing_keys = [key for key in keys if key not in frame.columns]
    if missing_keys:
        raise TableContractError(f"missing key columns: {missing_keys}")

    key_values = frame[keys]
    null_key_mask = key_values.isna().any(axis=1)
    blank_key_cells = pd.DataFrame(False, index=frame.index, columns=keys)
    for key in keys:
        text = key_values[key].astype("string")
        blank_key_cells[key] = text.str.strip().eq("").fillna(False)

    blank_key_mask = blank_key_cells.any(axis=1)
    missing_key_mask = null_key_mask | blank_key_mask
    duplicate_key_rows = int(frame.duplicated(keys, keep=False).sum())
    null_key_rows = int(null_key_mask.sum())
    blank_key_rows = int(blank_key_mask.sum())
    missing_key_rows = int(missing_key_mask.sum())
    return {
        "table": {
            "object_type": type(frame).__name__,
            "shape": list(frame.shape),
            "columns": frame.columns.tolist(),
            "index": {
                "type": type(frame.index).__name__,
                "name": frame.index.name,
                "is_unique": bool(frame.index.is_unique),
                "preview": frame.index[:5].tolist(),
            },
        },
        "declared_grain": {
            "keys": keys,
            "null_key_rows": null_key_rows,
            "blank_key_rows": blank_key_rows,
            "missing_key_rows": missing_key_rows,
            "duplicate_key_rows": duplicate_key_rows,
            "valid": duplicate_key_rows == 0 and missing_key_rows == 0,
        },
    }


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect a DataFrame and its declared grain",
    )
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--keys",
        required=True,
        help="Comma-separated columns that identify one observation",
    )
    args = parser.parse_args(argv)

    try:
        frame = load_table(args.input)
        keys = [item.strip() for item in args.keys.split(",") if item.strip()]
        report = inspect_dataframe(frame, keys)
    except (OSError, TableContractError, pd.errors.ParserError) as error:
        parser.error(str(error))

    print(render_report(report), end="")
    return 0 if report["declared_grain"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
