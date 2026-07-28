from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

READ_ONLY_START = re.compile(r"^\s*(SELECT|WITH|EXPLAIN)\b", re.IGNORECASE)


class QueryContractError(ValueError):
    """Raised when a query does not satisfy the runner contract."""


def execute_query(
    sql: str,
    params: Sequence[Any] = (),
    *,
    expected_columns: Sequence[str] | None = None,
    connection: duckdb.DuckDBPyConnection | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not READ_ONLY_START.match(sql):
        raise QueryContractError("runner accepts read-only SELECT, WITH, or EXPLAIN")

    owns_connection = connection is None
    active_connection = connection or duckdb.connect()
    try:
        frame = active_connection.execute(sql, list(params)).fetchdf()
    finally:
        if owns_connection:
            active_connection.close()

    columns = frame.columns.tolist()
    if expected_columns is not None and columns != list(expected_columns):
        raise QueryContractError(
            f"result columns {columns} differ from expected {list(expected_columns)}"
        )
    metadata = {
        "rows": len(frame),
        "columns": columns,
        "dtypes": {column: str(dtype) for column, dtype in frame.dtypes.items()},
        "connection_owned_by_runner": owns_connection,
    }
    return frame, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Run parameterized DuckDB SQL from Python")
    parser.add_argument("--sql-file", type=Path, required=True)
    parser.add_argument("--params-json", default="[]")
    parser.add_argument("--expected-columns", default="")
    args = parser.parse_args()
    try:
        params = json.loads(args.params_json)
        if not isinstance(params, list):
            raise QueryContractError("params-json must contain a JSON list")
        expected = [
            column.strip() for column in args.expected_columns.split(",") if column.strip()
        ] or None
        frame, metadata = execute_query(
            args.sql_file.read_text(encoding="utf-8"),
            params,
            expected_columns=expected,
        )
    except (duckdb.Error, OSError, json.JSONDecodeError, QueryContractError) as error:
        parser.error(str(error))
    payload = {"metadata": metadata, "records": frame.to_dict(orient="records")}
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
