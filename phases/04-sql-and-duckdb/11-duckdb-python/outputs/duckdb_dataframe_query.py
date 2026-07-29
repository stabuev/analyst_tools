from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import duckdb
import pandas as pd

QueryParameters = Sequence[Any] | Mapping[str, Any]


class QueryContractError(ValueError):
    """Raised when a DataFrame does not satisfy a declared query contract."""


def _normalized_contract(
    expected_columns: Sequence[str],
    expected_dtypes: Mapping[str, str],
) -> tuple[list[str], dict[str, str]]:
    columns = list(expected_columns)
    dtypes = dict(expected_dtypes)

    if not columns:
        raise QueryContractError("expected_columns must not be empty")
    if len(columns) != len(set(columns)):
        raise QueryContractError("expected_columns must not contain duplicates")

    missing_dtypes = [column for column in columns if column not in dtypes]
    extra_dtypes = [column for column in dtypes if column not in columns]
    if missing_dtypes or extra_dtypes:
        raise QueryContractError(
            "dtype contract must describe exactly expected_columns; "
            f"missing={missing_dtypes}, extra={extra_dtypes}"
        )

    return columns, dtypes


def validate_dataframe_contract(
    frame: object,
    *,
    expected_columns: Sequence[str],
    expected_dtypes: Mapping[str, str],
    role: str,
) -> None:
    """Validate exact column order and pandas dtypes at an engine boundary."""

    columns, dtypes = _normalized_contract(expected_columns, expected_dtypes)
    if not isinstance(frame, pd.DataFrame):
        raise QueryContractError(f"{role} must be a pandas DataFrame")

    actual_columns = frame.columns.tolist()
    if actual_columns != columns:
        raise QueryContractError(
            f"{role} columns {actual_columns} differ from expected {columns}"
        )

    actual_dtypes = {column: str(frame[column].dtype) for column in columns}
    wrong_dtypes = {
        column: {"expected": dtypes[column], "actual": actual_dtypes[column]}
        for column in columns
        if actual_dtypes[column] != dtypes[column]
    }
    if wrong_dtypes:
        raise QueryContractError(f"{role} dtype contract violation: {wrong_dtypes}")


def execute_trusted_query(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    parameters: QueryParameters = (),
    *,
    expected_columns: Sequence[str],
    expected_dtypes: Mapping[str, str],
) -> pd.DataFrame:
    """Execute reviewed SQL with bound values and validate its pandas result."""

    columns, dtypes = _normalized_contract(expected_columns, expected_dtypes)
    bound_parameters: list[Any] | dict[str, Any] = (
        dict(parameters) if isinstance(parameters, Mapping) else list(parameters)
    )

    frame = connection.execute(sql, bound_parameters).fetchdf()
    validate_dataframe_contract(
        frame,
        expected_columns=columns,
        expected_dtypes=dtypes,
        role="query result",
    )
    return frame


def query_dataframe(
    connection: duckdb.DuckDBPyConnection,
    *,
    sql: str,
    relation_name: str,
    frame: pd.DataFrame,
    parameters: QueryParameters = (),
    expected_input_columns: Sequence[str],
    expected_input_dtypes: Mapping[str, str],
    expected_output_columns: Sequence[str],
    expected_output_dtypes: Mapping[str, str],
) -> pd.DataFrame:
    """Expose one typed DataFrame to reviewed SQL and return a checked DataFrame."""

    validate_dataframe_contract(
        frame,
        expected_columns=expected_input_columns,
        expected_dtypes=expected_input_dtypes,
        role=f"input relation {relation_name!r}",
    )

    connection.register(relation_name, frame)
    try:
        return execute_trusted_query(
            connection,
            sql,
            parameters,
            expected_columns=expected_output_columns,
            expected_dtypes=expected_output_dtypes,
        )
    finally:
        connection.unregister(relation_name)
