"""Strict row selection for an already validated pandas DataFrame.

Public workflow: build an unresolved mask with ``build_order_mask``; inspect it with
``mask_report``; then call ``select_rows`` or ``label_rows`` with an explicit missing
policy. Run ``uv run --locked python code/main.py`` from the lesson directory for a
complete example.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from numbers import Integral, Real
from typing import Any

import pandas as pd
from pandas.api.types import is_bool_dtype, is_numeric_dtype

__all__ = [
    "SelectionContractError",
    "build_order_mask",
    "label_rows",
    "mask_report",
    "resolve_mask",
    "select_rows",
    "validate_mask",
]


class SelectionContractError(ValueError):
    """Raised when a selection cannot be applied predictably."""


MISSING_POLICIES = {"exclude", "error"}


def _require_dataframe(frame: object) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise SelectionContractError("expected a pandas DataFrame")
    if not frame.columns.is_unique:
        raise SelectionContractError("frame column names must be unique")
    if not frame.index.is_unique:
        raise SelectionContractError("frame index must be unique for strict selection")
    return frame


def _validate_values(values: Collection[str], *, name: str) -> set[str]:
    if isinstance(values, str):
        raise SelectionContractError(
            f"{name} must be a collection of strings, not one string"
        )
    if not values:
        raise SelectionContractError(f"{name} must not be empty")

    validated: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise SelectionContractError(f"{name} must contain non-empty strings")
        if value != value.strip():
            raise SelectionContractError(
                f"{name} must contain already normalized values without outer spaces"
            )
        validated.add(value)
    return validated


def _normalize_bound(value: object | None, *, name: str) -> Real | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise SelectionContractError(f"{name} must be a finite number, not bool")
    if not isinstance(value, Real):
        raise SelectionContractError(f"{name} must be an already parsed finite number")
    if not isinstance(value, Integral) and not math.isfinite(value):
        raise SelectionContractError(f"{name} must be a finite number")
    return value


def _require_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise SelectionContractError(f"missing column: {column}")
    return frame[column]


def _string_membership(
    frame: pd.DataFrame,
    *,
    column: str,
    allowed: Collection[str],
) -> pd.Series:
    source = _require_column(frame, column)
    if not isinstance(source.dtype, pd.StringDtype):
        raise SelectionContractError(
            f"{column} must already have a string dtype; got {source.dtype}"
        )
    nullable = source.astype("string")
    condition = nullable.isin(allowed).astype("boolean")
    return condition.mask(nullable.isna(), pd.NA)


def _amount_condition(
    frame: pd.DataFrame,
    *,
    minimum: Real | None,
    maximum: Real | None,
) -> pd.Series:
    source = _require_column(frame, "amount")
    if not is_numeric_dtype(source.dtype) or is_bool_dtype(source.dtype):
        raise SelectionContractError(
            "amount must already have a numeric dtype; run the dtype audit first"
        )
    if source.isin([float("inf"), float("-inf")]).any():
        raise SelectionContractError(
            "amount must contain only finite numbers or missing values"
        )

    condition = pd.Series(True, index=frame.index, dtype="boolean")
    if minimum is not None:
        condition &= source.ge(minimum).astype("boolean")
    if maximum is not None:
        condition &= source.le(maximum).astype("boolean")
    return condition


def build_order_mask(
    frame: pd.DataFrame,
    *,
    statuses: Collection[str] | None = None,
    currencies: Collection[str] | None = None,
    min_amount: object | None = None,
    max_amount: object | None = None,
) -> pd.Series:
    """Build an unresolved nullable mask from already validated order columns."""

    checked = _require_dataframe(frame)
    lower = _normalize_bound(min_amount, name="min_amount")
    upper = _normalize_bound(max_amount, name="max_amount")
    if lower is not None and upper is not None and lower > upper:
        raise SelectionContractError("min_amount cannot exceed max_amount")
    if statuses is None and currencies is None and lower is None and upper is None:
        raise SelectionContractError("at least one selection criterion is required")

    mask = pd.Series(True, index=checked.index, dtype="boolean", name="order_filter")
    if statuses is not None:
        allowed_statuses = _validate_values(statuses, name="statuses")
        mask &= _string_membership(
            checked,
            column="status",
            allowed=allowed_statuses,
        )
    if currencies is not None:
        allowed_currencies = _validate_values(currencies, name="currencies")
        mask &= _string_membership(
            checked,
            column="currency",
            allowed=allowed_currencies,
        )
    if lower is not None or upper is not None:
        mask &= _amount_condition(checked, minimum=lower, maximum=upper)
    return mask


def validate_mask(frame: pd.DataFrame, mask: pd.Series) -> pd.Series:
    """Require one nullable Boolean decision for every row in exact index order."""

    checked = _require_dataframe(frame)
    if not isinstance(mask, pd.Series):
        raise SelectionContractError("mask must be a pandas Series with row labels")
    if not is_bool_dtype(mask.dtype):
        raise SelectionContractError(
            "mask must have a recognized boolean dtype "
            f"(bool, boolean, or bool[pyarrow]); got {mask.dtype}"
        )
    if not mask.index.is_unique:
        raise SelectionContractError("mask index must be unique")
    if not mask.index.equals(checked.index):
        raise SelectionContractError(
            "mask index and order must exactly match the DataFrame index"
        )
    return mask.astype("boolean")


def mask_report(frame: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    """Describe True, False, and unknown rows before resolving the mask."""

    nullable = validate_mask(frame, mask)
    selected = nullable.eq(True).fillna(False)
    excluded = nullable.eq(False).fillna(False)
    unknown = nullable.isna()
    selected_labels = nullable.index[selected].tolist()
    unknown_labels = nullable.index[unknown].tolist()
    return {
        "rows": len(nullable),
        "mask_dtype": str(nullable.dtype),
        "selected_rows": int(selected.sum()),
        "excluded_rows": int(excluded.sum()),
        "unknown_rows": int(unknown.sum()),
        "selected_index_examples": [str(label) for label in selected_labels[:5]],
        "unknown_index_examples": [str(label) for label in unknown_labels[:5]],
    }


def resolve_mask(
    frame: pd.DataFrame,
    mask: pd.Series,
    *,
    missing: str = "exclude",
) -> tuple[pd.Series, dict[str, Any]]:
    """Resolve NA according to an explicit policy and retain an audit report."""

    if missing not in MISSING_POLICIES:
        raise SelectionContractError(
            f"missing policy must be one of {sorted(MISSING_POLICIES)}"
        )
    nullable = validate_mask(frame, mask)
    report = mask_report(frame, nullable)
    if missing == "error" and report["unknown_rows"]:
        examples = report["unknown_index_examples"]
        raise SelectionContractError(
            f"filter has unknown truth values at index labels: {examples}"
        )

    resolved = nullable.fillna(False).astype(bool)
    resolved.name = nullable.name
    report["missing_policy"] = missing
    report["resolved_selected_rows"] = int(resolved.sum())
    return resolved, report


def _normalize_columns(
    frame: pd.DataFrame,
    columns: Sequence[str] | None,
) -> list[str]:
    if columns is None:
        return frame.columns.tolist()
    if isinstance(columns, str) or not columns:
        raise SelectionContractError("columns must be a non-empty sequence of names")
    selected = list(columns)
    if any(not isinstance(column, str) or not column for column in selected):
        raise SelectionContractError("column names must be non-empty strings")
    if len(set(selected)) != len(selected):
        raise SelectionContractError("columns must not contain duplicates")
    missing = [column for column in selected if column not in frame.columns]
    if missing:
        raise SelectionContractError(f"missing selected columns: {missing}")
    return selected


def select_rows(
    frame: pd.DataFrame,
    mask: pd.Series,
    *,
    columns: Sequence[str] | None = None,
    missing: str = "exclude",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Select rows and named columns, returning an independent DataFrame and report."""

    checked = _require_dataframe(frame)
    selected_columns = _normalize_columns(checked, columns)
    resolved, report = resolve_mask(checked, mask, missing=missing)
    result = checked.loc[resolved, selected_columns].copy()
    report["columns"] = selected_columns
    report["output_shape"] = list(result.shape)
    return result, report


def label_rows(
    frame: pd.DataFrame,
    mask: pd.Series,
    *,
    column: str = "review_status",
    value: object = "review",
    missing: str = "exclude",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Label selected rows on an independent frame with one loc assignment."""

    checked = _require_dataframe(frame)
    if not isinstance(column, str) or not column:
        raise SelectionContractError("target column must be a non-empty string")
    resolved, report = resolve_mask(checked, mask, missing=missing)
    result = checked.copy()
    try:
        result.loc[resolved, column] = value
    except (TypeError, ValueError) as error:
        raise SelectionContractError(
            f"value {value!r} is incompatible with target column {column!r}"
        ) from error
    report["target_column"] = column
    report["labeled_rows"] = int(resolved.sum())
    return result, report
