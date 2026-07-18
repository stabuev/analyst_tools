from __future__ import annotations

import argparse
import json
import operator
from pathlib import Path
from typing import Any

import numpy as np


class SelectionContractError(ValueError):
    """Raised when an array selection contract is invalid."""


def _as_numeric_array(
    values: object,
    *,
    name: str,
    ndim: int | None = None,
) -> np.ndarray:
    try:
        array = np.asarray(values)
    except ValueError as error:
        raise SelectionContractError(f"{name} must be rectangular") from error

    if ndim is not None and array.ndim != ndim:
        raise SelectionContractError(
            f"{name} must be {ndim}-dimensional, got shape {array.shape}"
        )
    if array.ndim == 0:
        raise SelectionContractError(f"{name} must contain an array, not a scalar")
    if 0 in array.shape:
        raise SelectionContractError(f"{name} must not have an empty axis")

    if array.dtype.kind == "O":
        try:
            array = np.asarray(values, dtype=np.float64)
        except (TypeError, ValueError) as error:
            raise SelectionContractError(f"{name} must contain numeric values") from error

    if array.dtype.kind not in "iuf":
        raise SelectionContractError(
            f"{name} must contain numeric values, got dtype {array.dtype}"
        )
    return array


def as_numeric_matrix(values: object) -> np.ndarray:
    """Return a non-empty two-dimensional numeric array.

    JSON ``null`` values are converted to ``NaN`` and therefore require a floating dtype.
    """

    return _as_numeric_array(values, name="matrix", ndim=2)


def _validate_bounds(
    lower: float | None,
    upper: float | None,
) -> tuple[float | None, float | None]:
    normalized_lower = None if lower is None else float(lower)
    normalized_upper = None if upper is None else float(upper)

    for name, value in (("lower", normalized_lower), ("upper", normalized_upper)):
        if value is not None and not np.isfinite(value):
            raise SelectionContractError(f"{name} bound must be finite")
    if (
        normalized_lower is not None
        and normalized_upper is not None
        and normalized_lower > normalized_upper
    ):
        raise SelectionContractError("lower bound cannot exceed upper bound")
    return normalized_lower, normalized_upper


def build_range_mask(
    values: object,
    *,
    lower: float | None = None,
    upper: float | None = None,
    inclusive: str = "both",
) -> np.ndarray:
    """Build a one-dimensional mask and always reject non-finite values."""

    if inclusive not in {"both", "left", "right", "neither"}:
        raise SelectionContractError(
            "inclusive must be both, left, right, or neither"
        )
    normalized_lower, normalized_upper = _validate_bounds(lower, upper)
    array = _as_numeric_array(values, name="filter values", ndim=1)

    mask = np.isfinite(array)
    if normalized_lower is not None:
        lower_mask = (
            array >= normalized_lower
            if inclusive in {"both", "left"}
            else array > normalized_lower
        )
        mask &= lower_mask
    if normalized_upper is not None:
        upper_mask = (
            array <= normalized_upper
            if inclusive in {"both", "right"}
            else array < normalized_upper
        )
        mask &= upper_mask
    return mask


def _normalize_index(index: object, length: int, *, name: str) -> int:
    if isinstance(index, (bool, np.bool_)):
        raise SelectionContractError(f"{name} must be an integer, not bool")
    try:
        normalized = operator.index(index)
    except TypeError as error:
        raise SelectionContractError(f"{name} must be an integer") from error
    if normalized < -length or normalized >= length:
        raise SelectionContractError(
            f"{name} {normalized} is out of bounds for axis of length {length}"
        )
    return normalized % length


def _normalize_columns(
    columns: object | None,
    feature_count: int,
) -> tuple[int, ...]:
    if columns is None:
        return tuple(range(feature_count))

    raw = np.asarray(columns)
    if raw.ndim != 1 or raw.size == 0:
        raise SelectionContractError("columns must be a non-empty one-dimensional list")
    normalized = tuple(
        _normalize_index(value, feature_count, name="column index") for value in raw
    )
    if len(set(normalized)) != len(normalized):
        raise SelectionContractError("columns must not contain duplicates")
    return normalized


def _validate_row_mask(row_mask: object, row_count: int) -> np.ndarray:
    mask = np.asarray(row_mask)
    if mask.dtype.kind != "b":
        raise SelectionContractError(
            f"row mask must have bool dtype, got {mask.dtype}"
        )
    if mask.shape != (row_count,):
        raise SelectionContractError(
            f"row mask shape {mask.shape} does not match row axis ({row_count},)"
        )
    return mask


def select_rows(
    matrix: object,
    row_mask: object,
    *,
    columns: object | None = None,
) -> np.ndarray:
    """Select rows and columns, preserving their order and returning an independent array."""

    array = as_numeric_matrix(matrix)
    mask = _validate_row_mask(row_mask, array.shape[0])
    normalized_columns = _normalize_columns(columns, array.shape[1])

    selected_rows = array[mask]
    selected = selected_rows[:, normalized_columns]
    result = selected.copy()
    if np.shares_memory(array, result):
        raise SelectionContractError("selected result unexpectedly shares memory")
    return result


def replace_where(
    values: np.ndarray,
    mask: object,
    replacement: object,
    *,
    in_place: bool = False,
) -> np.ndarray:
    """Replace positions selected by a same-shape boolean mask.

    The replacement must survive conversion to the array dtype without changing value.
    """

    array = _as_numeric_array(values, name="values")
    if in_place and array is not values:
        raise SelectionContractError("in_place=True requires a NumPy ndarray")

    boolean_mask = np.asarray(mask)
    if boolean_mask.dtype.kind != "b":
        raise SelectionContractError(
            f"replacement mask must have bool dtype, got {boolean_mask.dtype}"
        )
    if boolean_mask.shape != array.shape:
        raise SelectionContractError(
            f"replacement mask shape {boolean_mask.shape} does not match values {array.shape}"
        )

    replacement_array = np.asarray(replacement)
    if replacement_array.ndim != 0:
        raise SelectionContractError("replacement must be a scalar")
    try:
        converted = replacement_array.astype(
            array.dtype,
            casting="same_value",
            copy=False,
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise SelectionContractError(
            f"replacement {replacement!r} cannot be stored unchanged in dtype {array.dtype}"
        ) from error

    result = array if in_place else array.copy()
    result[boolean_mask] = converted.item()
    return result


def memory_report(matrix: object) -> dict[str, Any]:
    """Demonstrate shape and memory differences for common indexing forms."""

    array = as_numeric_matrix(matrix)
    take_count = min(2, array.shape[0])
    basic_slice = array[:take_count]
    advanced_selection = array[np.arange(take_count)]
    column_vector = array[:, 0]
    column_matrix = array[:, 0:1]
    return {
        "source_shape": list(array.shape),
        "basic_slice_shape": list(basic_slice.shape),
        "basic_slice_shares_memory": bool(np.shares_memory(array, basic_slice)),
        "advanced_selection_shape": list(advanced_selection.shape),
        "advanced_selection_shares_memory": bool(
            np.shares_memory(array, advanced_selection)
        ),
        "column_vector_shape": list(column_vector.shape),
        "column_matrix_shape": list(column_matrix.shape),
    }


def build_selection_report(
    matrix: object,
    *,
    filter_column: object,
    lower: float | None = None,
    upper: float | None = None,
    inclusive: str = "both",
    columns: object | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable audit of one row-selection contract."""

    array = as_numeric_matrix(matrix)
    normalized_filter_column = _normalize_index(
        filter_column,
        array.shape[1],
        name="filter column",
    )
    normalized_columns = _normalize_columns(columns, array.shape[1])
    filter_values = array[:, normalized_filter_column]
    mask = build_range_mask(
        filter_values,
        lower=lower,
        upper=upper,
        inclusive=inclusive,
    )
    selected = select_rows(array, mask, columns=normalized_columns)
    return {
        "axis_contract": ["observation", "feature"],
        "source_shape": list(array.shape),
        "source_dtype": str(array.dtype),
        "filter_column": normalized_filter_column,
        "columns": list(normalized_columns),
        "mask_shape": list(mask.shape),
        "mask": mask.tolist(),
        "selected_count": int(mask.sum()),
        "excluded_non_finite": int((~np.isfinite(filter_values)).sum()),
        "selected_shape": list(selected.shape),
        "selected_dtype": str(selected.dtype),
        "selected": selected.tolist(),
        "shares_memory": bool(np.shares_memory(array, selected)),
        "memory_demo": memory_report(array),
    }


def parse_json(raw: str, *, name: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise SelectionContractError(f"{name} must be valid JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit NumPy row, column, mask, shape, and memory selection"
    )
    parser.add_argument(
        "--matrix",
        default=(
            "[[101, 1, 1200, 2], [102, 3, 4500, 7], "
            "[103, 2, null, 4], [104, 2, 3200, 3], [105, 5, 8000, 1]]"
        ),
    )
    parser.add_argument("--filter-column", type=int, default=2)
    parser.add_argument("--lower", type=float)
    parser.add_argument("--upper", type=float)
    parser.add_argument(
        "--inclusive",
        choices=("both", "left", "right", "neither"),
        default="both",
    )
    parser.add_argument("--columns", default="[0, 2, 3]")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        matrix = parse_json(args.matrix, name="matrix")
        columns = parse_json(args.columns, name="columns")
        report = build_selection_report(
            matrix,
            filter_column=args.filter_column,
            lower=args.lower,
            upper=args.upper,
            inclusive=args.inclusive,
            columns=columns,
        )
    except SelectionContractError as error:
        parser.exit(2, f"selection-contract: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
