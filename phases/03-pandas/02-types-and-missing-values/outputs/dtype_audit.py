from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd


class DtypeContractError(ValueError):
    """Raised when a value cannot be converted without silent loss."""


BOOLEAN_VALUES = {
    "true": True,
    "false": False,
    "1": True,
    "0": False,
    "yes": True,
    "no": False,
}


def _non_empty(series: pd.Series) -> pd.Series:
    return series.notna() & series.astype("string").str.strip().ne("")


def convert_series(series: pd.Series, target: str) -> pd.Series:
    source = series.copy()
    if target == "string":
        return source.astype("string")
    if target in {"Int64", "Float64"}:
        converted = pd.to_numeric(source, errors="coerce")
        invalid = _non_empty(source) & converted.isna()
        if invalid.any():
            raise DtypeContractError(f"cannot parse {int(invalid.sum())} values as {target}")
        if target == "Int64":
            fractional = converted.dropna().mod(1).ne(0)
            if fractional.any():
                raise DtypeContractError("integer conversion would truncate values")
        return converted.astype(target)
    if target == "boolean":
        normalized = source.astype("string").str.strip().str.lower()
        converted = normalized.map(BOOLEAN_VALUES).astype("boolean")
        invalid = _non_empty(source) & converted.isna()
        if invalid.any():
            raise DtypeContractError(f"cannot parse {int(invalid.sum())} values as boolean")
        return converted
    if target == "datetime_utc":
        converted = pd.to_datetime(source, errors="coerce", format="mixed", utc=True)
        invalid = _non_empty(source) & converted.isna()
        if invalid.any():
            raise DtypeContractError(f"cannot parse {int(invalid.sum())} values as datetime")
        return converted
    raise DtypeContractError(f"unsupported target dtype: {target}")


def audit_and_convert(
    frame: pd.DataFrame,
    schema: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    missing = sorted(set(schema) - set(frame.columns))
    if missing:
        raise DtypeContractError(f"missing schema columns: {missing}")
    result = frame.copy()
    before_memory = int(result.memory_usage(index=True, deep=True).sum())
    columns: dict[str, Any] = {}
    for column, target in schema.items():
        before = result[column]
        converted = convert_series(before, target)
        result[column] = converted
        columns[column] = {
            "source_dtype": str(before.dtype),
            "target_dtype": str(converted.dtype),
            "nulls_before": int(before.isna().sum()),
            "nulls_after": int(converted.isna().sum()),
        }
    return result, {
        "rows": len(result),
        "columns": columns,
        "memory_bytes_before": before_memory,
        "memory_bytes_after": int(result.memory_usage(index=True, deep=True).sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and convert pandas dtypes")
    parser.add_argument("input", type=Path)
    parser.add_argument("--schema", required=True, help="JSON object: column -> dtype")
    args = parser.parse_args()
    try:
        schema = json.loads(args.schema)
        if not isinstance(schema, dict):
            raise DtypeContractError("schema must be a JSON object")
        frame = pd.read_csv(args.input, dtype="string")
        _, report = audit_and_convert(frame, schema)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, DtypeContractError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
