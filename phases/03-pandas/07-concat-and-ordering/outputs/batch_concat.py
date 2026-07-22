"""Contract-first row-wise concatenation of already validated pandas batches.

The public function :func:`concat_batches` accepts a named mapping of same-grain,
same-schema DataFrames. It validates the contract before concatenation, records batch
provenance, rejects overlapping business keys and returns a deterministically ordered
result with an audit report. It does not read files, parse raw values or provide a CLI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

__all__ = ["ConcatContractError", "concat_batches"]


class ConcatContractError(ValueError):
    """Raised when row-wise concatenation would violate the declared contract."""


def _column_names(names: Sequence[str], *, argument: str) -> list[str]:
    if isinstance(names, (str, bytes)):
        raise ConcatContractError(f"{argument} must be a sequence of column names")
    result = list(names)
    if not result:
        raise ConcatContractError(f"{argument} must not be empty")
    if any(not isinstance(name, str) or not name.strip() for name in result):
        raise ConcatContractError(
            f"{argument} must contain non-blank string column names"
        )
    if len(result) != len(set(result)):
        raise ConcatContractError(f"{argument} must not contain duplicate names")
    return result


def _batch_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ConcatContractError("batch names must be non-blank strings")
    return name


def _frame(value: object, *, batch: str) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise ConcatContractError(f"batch {batch!r} must be a pandas DataFrame")
    if not value.columns.is_unique:
        raise ConcatContractError(f"batch {batch!r} column labels must be unique")
    return value


def _blank_mask(series: pd.Series) -> pd.Series:
    return series.map(
        lambda value: isinstance(value, str) and not value.strip()
    ).astype("boolean")


def _validate_key_values(
    frame: pd.DataFrame,
    *,
    batch: str,
    keys: Sequence[str],
) -> None:
    invalid = frame.loc[:, keys].isna().any(axis=1)
    for key in keys:
        invalid |= _blank_mask(frame[key]).fillna(False)
    if invalid.any():
        labels = frame.index[invalid].tolist()[:5]
        raise ConcatContractError(
            f"batch {batch!r} business key must be non-missing and non-blank; "
            f"row labels: {labels}"
        )


def _dtype_map(frame: pd.DataFrame) -> dict[str, Any]:
    """Return dtype objects so extension-type metadata participates in equality."""

    return {column: frame[column].dtype for column in frame.columns}


def _dtype_labels(dtypes: Mapping[str, Any]) -> dict[str, str]:
    """Make dtype objects readable and serializable in errors and audit output."""

    return {column: str(dtype) for column, dtype in dtypes.items()}


def concat_batches(
    batches: Mapping[str, pd.DataFrame],
    *,
    key: Sequence[str],
    sort_by: Sequence[str] | None = None,
    source_column: str = "source_batch",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Append same-grain batches and verify one reproducible result.

    Parameters
    ----------
    batches:
        Non-empty mapping ``batch name -> DataFrame``. Every frame must contain exactly
        the same columns with the same pandas dtypes. Column order may differ and is
        normalized to the first batch.
    key:
        Complete business key of the target row grain. Values must be non-missing,
        non-blank and unique across the combined result.
    sort_by:
        Optional leading business sort columns. Missing key columns are appended as
        deterministic tie-breakers. If omitted, the complete key defines the order.
    source_column:
        New string column that records the originating batch.

    Returns
    -------
    tuple[pandas.DataFrame, dict]
        A new DataFrame with a fresh ``RangeIndex`` and an audit report. Inputs are not
        modified.
    """

    if not isinstance(batches, Mapping) or not batches:
        raise ConcatContractError("batches must be a non-empty mapping")
    keys = _column_names(key, argument="key")
    if not isinstance(source_column, str) or not source_column.strip():
        raise ConcatContractError("source_column must be a non-blank string")

    named_frames: list[tuple[str, pd.DataFrame]] = []
    for raw_name, raw_frame in batches.items():
        name = _batch_name(raw_name)
        named_frames.append((name, _frame(raw_frame, batch=name)))

    reference_name, reference = named_frames[0]
    reference_columns = reference.columns.tolist()
    reference_set = set(reference_columns)
    if source_column in reference_set:
        raise ConcatContractError(
            f"source column already exists in input schema: {source_column}"
        )
    missing_key_columns = sorted(set(keys) - reference_set)
    if missing_key_columns:
        raise ConcatContractError(
            f"business key columns are missing from schema: {missing_key_columns}"
        )

    leading_order = keys if sort_by is None else _column_names(
        sort_by, argument="sort_by"
    )
    missing_sort_columns = sorted(set(leading_order) - reference_set)
    if missing_sort_columns:
        raise ConcatContractError(
            f"sort columns are missing from schema: {missing_sort_columns}"
        )
    effective_order = [*leading_order, *(name for name in keys if name not in leading_order)]

    reference_dtypes = _dtype_map(reference)
    normalized_order_batches: list[str] = []
    parts: list[pd.DataFrame] = []
    batch_rows: dict[str, int] = {}

    for name, frame in named_frames:
        columns = frame.columns.tolist()
        missing = sorted(reference_set - set(columns))
        extra = sorted(set(columns) - reference_set)
        if missing or extra:
            raise ConcatContractError(
                f"batch {name!r} schema differs from {reference_name!r}; "
                f"missing={missing}, extra={extra}"
            )
        if source_column in frame.columns:
            raise ConcatContractError(
                f"source column already exists in batch {name!r}: {source_column}"
            )

        actual_dtypes = _dtype_map(frame.loc[:, reference_columns])
        dtype_mismatches = {
            column: {
                "expected": str(reference_dtypes[column]),
                "actual": str(actual_dtypes[column]),
            }
            for column in reference_columns
            if actual_dtypes[column] != reference_dtypes[column]
        }
        if dtype_mismatches:
            raise ConcatContractError(
                f"batch {name!r} dtypes differ from {reference_name!r}: "
                f"{dtype_mismatches}"
            )

        _validate_key_values(frame, batch=name, keys=keys)
        if columns != reference_columns:
            normalized_order_batches.append(name)

        part = frame.loc[:, reference_columns].copy()
        part[source_column] = pd.array([name] * len(part), dtype="string")
        parts.append(part)
        batch_rows[name] = len(part)

    expected_rows = sum(batch_rows.values())
    combined = pd.concat(parts, axis=0, ignore_index=True, sort=False)
    if len(combined) != expected_rows:
        raise ConcatContractError(
            f"row reconciliation failed: expected {expected_rows}, got {len(combined)}"
        )

    combined_dtypes = _dtype_map(combined.loc[:, reference_columns])
    changed_dtypes = {
        column: {
            "expected": str(reference_dtypes[column]),
            "actual": str(combined_dtypes[column]),
        }
        for column in reference_columns
        if combined_dtypes[column] != reference_dtypes[column]
    }
    if changed_dtypes:
        raise ConcatContractError(
            f"concat changed declared dtypes: {changed_dtypes}"
        )

    duplicated = combined.duplicated(keys, keep=False)
    if duplicated.any():
        examples = (
            combined.loc[duplicated, [*keys, source_column]]
            .head(8)
            .to_dict(orient="records")
        )
        raise ConcatContractError(
            "business key overlaps within or across batches; "
            f"duplicate row examples: {examples}"
        )

    sort_kwargs: dict[str, Any] = {
        "by": effective_order,
        "na_position": "last",
        "ignore_index": True,
    }
    if len(effective_order) == 1:
        sort_kwargs["kind"] = "stable"
    result = combined.sort_values(**sort_kwargs)

    if not isinstance(result.index, pd.RangeIndex):
        raise ConcatContractError("result must have a fresh RangeIndex")
    if result.duplicated(keys).any():
        raise ConcatContractError("result does not satisfy the declared row grain")

    audit: dict[str, Any] = {
        "batch_order_received": [name for name, _ in named_frames],
        "batch_rows": batch_rows,
        "input_rows": expected_rows,
        "result_rows": len(result),
        "schema": reference_columns.copy(),
        "dtypes": _dtype_labels(reference_dtypes),
        "key": keys.copy(),
        "source_column": source_column,
        "column_order_normalized_batches": normalized_order_batches,
        "effective_sort_columns": effective_order,
        "row_reconciliation_passed": len(result) == expected_rows,
        "grain_valid": True,
        "index_policy": "fresh RangeIndex after concat and sort",
    }
    return result, audit
