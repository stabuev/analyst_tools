from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd


class ReshapeContractError(ValueError):
    """Raised when reshape would lose identity or hide an aggregation."""


def _validate_frame(frame: object) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise ReshapeContractError("frame must be a pandas DataFrame")
    if not frame.columns.is_unique:
        raise ReshapeContractError("column labels must be unique")
    return frame


def _column_list(names: Sequence[str], *, argument: str) -> list[str]:
    if isinstance(names, (str, bytes)):
        raise ReshapeContractError(f"{argument} must be a sequence of column names")

    result = list(names)
    if not result:
        raise ReshapeContractError(f"{argument} must not be empty")
    if any(not isinstance(name, str) or not name.strip() for name in result):
        raise ReshapeContractError(
            f"{argument} must contain non-blank string column names"
        )
    if len(result) != len(set(result)):
        raise ReshapeContractError(f"{argument} must not contain duplicate names")
    return result


def _validate_output_name(name: object, *, argument: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ReshapeContractError(f"{argument} must be a non-blank string")
    return name


def _missing_columns(frame: pd.DataFrame, required: Sequence[str]) -> list[str]:
    return sorted(set(required) - set(frame.columns))


def _blank_mask(series: pd.Series) -> pd.Series:
    return series.map(lambda value: isinstance(value, str) and not value.strip()).astype(
        "boolean"
    )


def _validate_key_values(frame: pd.DataFrame, keys: Sequence[str], *, role: str) -> None:
    for key in keys:
        invalid = frame[key].isna() | _blank_mask(frame[key])
        if invalid.any():
            labels = frame.index[invalid].tolist()
            raise ReshapeContractError(
                f"{role} column {key!r} must be non-missing and non-blank "
                f"at rows: {labels}"
            )


def to_long(
    frame: pd.DataFrame,
    *,
    id_vars: Sequence[str],
    value_vars: Sequence[str],
    variable_name: str = "metric",
    value_name: str = "value",
) -> pd.DataFrame:
    """Move one variable's levels from column labels into rows.

    ``id_vars`` must uniquely identify the source wide rows. All ``value_vars`` must
    already have the same dtype because the result stores them in one value column.
    Missing measured values are preserved, and the technical index is intentionally
    replaced with a fresh RangeIndex. The input object is never modified.
    """

    source = _validate_frame(frame)
    ids = _column_list(id_vars, argument="id_vars")
    measured = _column_list(value_vars, argument="value_vars")
    variable = _validate_output_name(variable_name, argument="variable_name")
    value = _validate_output_name(value_name, argument="value_name")

    overlap = sorted(set(ids) & set(measured))
    if overlap:
        raise ReshapeContractError(
            f"id_vars and value_vars must not overlap: {overlap}"
        )
    if variable == value:
        raise ReshapeContractError("variable_name and value_name must be different")

    missing = _missing_columns(source, [*ids, *measured])
    if missing:
        raise ReshapeContractError(f"missing columns: {missing}")

    collisions = sorted({variable, value} & set(source.columns))
    if collisions:
        raise ReshapeContractError(
            f"output column names collide with input columns: {collisions}"
        )

    _validate_key_values(source, ids, role="identifier")
    duplicated_ids = source.duplicated(ids, keep=False)
    if duplicated_ids.any():
        labels = source.index[duplicated_ids].tolist()
        raise ReshapeContractError(
            "id_vars must identify one source wide row; "
            f"duplicate identifier rows: {labels}"
        )

    measured_dtypes = {column: str(source[column].dtype) for column in measured}
    if len(set(measured_dtypes.values())) != 1:
        raise ReshapeContractError(
            "value_vars must have one declared dtype before sharing a value column: "
            f"{measured_dtypes}"
        )

    result = source.melt(
        id_vars=ids,
        value_vars=measured,
        var_name=variable,
        value_name=value,
        ignore_index=True,
    )

    expected_rows = len(source) * len(measured)
    if len(result) != expected_rows:
        raise ReshapeContractError(
            f"row reconciliation failed: expected {expected_rows}, got {len(result)}"
        )
    expected_missing = int(source[measured].isna().to_numpy().sum())
    if int(result[value].isna().sum()) != expected_missing:
        raise ReshapeContractError("missing-value reconciliation failed")

    return result


def pivot_unique(
    frame: pd.DataFrame,
    *,
    index: Sequence[str],
    columns: str,
    values: str,
) -> pd.DataFrame:
    """Move one variable's levels from rows into columns without aggregation.

    The combination ``[*index, columns]`` must identify at most one source row. Missing
    measured values and missing combinations remain missing; the function never fills
    them with zero. The input object is never modified.
    """

    source = _validate_frame(frame)
    index_columns = _column_list(index, argument="index")
    column_axis = _validate_output_name(columns, argument="columns")
    value_column = _validate_output_name(values, argument="values")

    roles = [*index_columns, column_axis, value_column]
    if len(roles) != len(set(roles)):
        raise ReshapeContractError(
            "index, columns and values must refer to different input columns"
        )

    missing = _missing_columns(source, roles)
    if missing:
        raise ReshapeContractError(f"missing columns: {missing}")

    cell_keys = [*index_columns, column_axis]
    _validate_key_values(source, cell_keys, role="pivot key")

    duplicated_cells = source.duplicated(cell_keys, keep=False)
    if duplicated_cells.any():
        conflicts: list[dict[str, Any]] = (
            source.loc[duplicated_cells, cell_keys]
            .drop_duplicates()
            .head(3)
            .to_dict(orient="records")
        )
        raise ReshapeContractError(
            "pivot cell key must be unique; conflicting keys: "
            f"{conflicts}. Aggregate explicitly before pivot only when multiple "
            "observations are expected by the business definition."
        )

    future_labels = source[column_axis].drop_duplicates().tolist()
    collisions = [label for label in future_labels if label in set(index_columns)]
    if collisions:
        raise ReshapeContractError(
            "future wide column labels collide with index columns: "
            f"{collisions}"
        )

    try:
        result = (
            source.pivot(
                index=index_columns,
                columns=column_axis,
                values=value_column,
            )
            .reset_index()
        )
    except (TypeError, ValueError) as error:
        raise ReshapeContractError(f"cannot build wide table: {error}") from error

    result.columns.name = None
    expected_rows = int(source[index_columns].drop_duplicates().shape[0])
    if len(result) != expected_rows:
        raise ReshapeContractError(
            f"wide row reconciliation failed: expected {expected_rows}, got {len(result)}"
        )
    if result.duplicated(index_columns).any():
        raise ReshapeContractError("wide result does not satisfy the declared grain")
    return result
