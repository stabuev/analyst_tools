from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from numbers import Integral
from pathlib import Path
from typing import Any

import numpy as np

Axis = int | Sequence[int] | None


class AggregationError(ValueError):
    """Raised when an aggregation contract is invalid."""


def normalize_axes(axis: Axis, ndim: int) -> tuple[int, ...]:
    """Return a validated tuple of non-negative axes."""
    if ndim < 1:
        raise AggregationError("values must have at least one axis")
    if axis is None:
        return tuple(range(ndim))
    if isinstance(axis, Integral) and not isinstance(axis, bool):
        raw_axes = (int(axis),)
    else:
        try:
            raw_axes = tuple(axis)
        except TypeError as error:
            raise AggregationError("axis must be an integer, a sequence, or None") from error
        if not raw_axes:
            raise AggregationError("axis sequence must not be empty")

    normalized: list[int] = []
    for item in raw_axes:
        if not isinstance(item, Integral) or isinstance(item, bool):
            raise AggregationError("every axis must be an integer")
        number = int(item)
        number = number + ndim if number < 0 else number
        if number < 0 or number >= ndim:
            raise AggregationError(f"axis {item} is out of bounds for ndim={ndim}")
        if number in normalized:
            raise AggregationError(f"axis {number} is repeated")
        normalized.append(number)
    return tuple(normalized)


def validate_axis_names(
    axis_names: Sequence[str] | None,
    ndim: int,
) -> tuple[str, ...]:
    if axis_names is None:
        return tuple(f"axis_{index}" for index in range(ndim))
    names = tuple(axis_names)
    if len(names) != ndim:
        raise AggregationError(
            f"expected {ndim} axis names for shape with {ndim} dimensions, got {len(names)}"
        )
    if any(not isinstance(name, str) or not name or not name.strip() for name in names):
        raise AggregationError("axis names must be non-empty strings")
    if len(set(names)) != len(names):
        raise AggregationError("axis names must be unique")
    return names


def aggregation_contract(
    shape: Sequence[int],
    *,
    axis: Axis,
    axis_names: Sequence[str] | None = None,
    keepdims: bool = False,
) -> dict[str, Any]:
    """Predict the semantic axes and shape after a reduction."""
    input_shape = tuple(int(length) for length in shape)
    axes = normalize_axes(axis, len(input_shape))
    names = validate_axis_names(axis_names, len(input_shape))
    reduced = set(axes)

    if keepdims:
        output_shape = tuple(
            1 if index in reduced else length for index, length in enumerate(input_shape)
        )
        output_axis_names = tuple(
            f"summarized_{name}" if index in reduced else name for index, name in enumerate(names)
        )
    else:
        output_shape = tuple(
            length for index, length in enumerate(input_shape) if index not in reduced
        )
        output_axis_names = tuple(name for index, name in enumerate(names) if index not in reduced)

    return {
        "input_shape": list(input_shape),
        "input_axis_names": list(names),
        "reduced_axes": list(axes),
        "reduced_axis_names": [names[index] for index in axes],
        "output_shape": list(output_shape),
        "output_axis_names": list(output_axis_names),
        "keepdims": keepdims,
    }


def manual_sum_2d(values: list[list[float]], axis: int) -> list[float]:
    """Expose the grouping hidden by np.sum for a small matrix."""
    if not values or not values[0]:
        raise AggregationError("manual sum expects a non-empty matrix")
    width = len(values[0])
    if any(len(row) != width for row in values):
        raise AggregationError("manual sum expects a rectangular matrix")
    if axis == 0:
        return [sum(row[column] for row in values) for column in range(width)]
    if axis == 1:
        return [sum(row) for row in values]
    raise AggregationError("manual 2D sum supports axis 0 or 1")


def as_numeric_array(values: object) -> np.ndarray:
    try:
        array = np.asarray(values)
    except ValueError as error:
        raise AggregationError("values must form a rectangular array") from error

    # JSON null creates an object array. Convert only that case so ordinary numeric
    # integer and floating dtypes remain observable in the report.
    if array.dtype == object:
        try:
            array = np.asarray(values, dtype=np.float64)
        except (TypeError, ValueError) as error:
            raise AggregationError("values must contain numbers or null") from error

    if array.ndim == 0:
        raise AggregationError("values must have at least one axis")
    if array.size == 0 or any(length == 0 for length in array.shape):
        raise AggregationError("values must not contain empty axes")
    if not np.issubdtype(array.dtype, np.number) or np.issubdtype(array.dtype, np.complexfloating):
        raise AggregationError("values must contain real numbers")
    if np.issubdtype(array.dtype, np.bool_):
        raise AggregationError("boolean values require an explicit counting contract")
    if np.isinf(array).any():
        raise AggregationError("infinite values are not treated as missing")
    return array


def to_json_value(value: np.ndarray | np.generic) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value.item()


def describe_result(value: np.ndarray | np.generic) -> dict[str, Any]:
    array = np.asarray(value)
    return {
        "value": to_json_value(value),
        "shape": list(array.shape),
        "dtype": str(array.dtype),
    }


def aggregate(
    values: object,
    *,
    axis: Axis,
    axis_names: Sequence[str] | None = None,
    keepdims: bool = False,
    missing_policy: str = "error",
    ddof: int = 0,
) -> dict[str, Any]:
    """Calculate aggregates and make their semantic shape contract observable."""
    array = as_numeric_array(values)
    if missing_policy not in {"error", "omit"}:
        raise AggregationError("missing_policy must be 'error' or 'omit'")
    if not isinstance(ddof, Integral) or isinstance(ddof, bool) or ddof < 0:
        raise AggregationError("ddof must be a non-negative integer")

    contract = aggregation_contract(
        array.shape,
        axis=axis,
        axis_names=axis_names,
        keepdims=keepdims,
    )
    axes = tuple(contract["reduced_axes"])
    missing = np.isnan(array)
    if missing_policy == "error" and missing.any():
        raise AggregationError(
            "missing values found; choose missing_policy='omit' explicitly to exclude them"
        )

    group_size = np.sum(
        np.ones(array.shape, dtype=np.int64),
        axis=axes,
        keepdims=keepdims,
    )
    valid_count = np.sum(~missing, axis=axes, keepdims=keepdims, dtype=np.int64)
    missing_count = group_size - valid_count

    if np.any(valid_count == 0):
        raise AggregationError("at least one reduction group has no valid observations")
    if np.any(valid_count <= ddof):
        raise AggregationError(
            "ddof must be smaller than the valid observation count in every group"
        )

    if missing_policy == "omit":
        operations = {
            "sum": np.nansum(array, axis=axes, keepdims=keepdims),
            "mean": np.nanmean(array, axis=axes, keepdims=keepdims),
            "min": np.nanmin(array, axis=axes, keepdims=keepdims),
            "max": np.nanmax(array, axis=axes, keepdims=keepdims),
            "std": np.nanstd(array, axis=axes, keepdims=keepdims, ddof=ddof),
        }
    else:
        operations = {
            "sum": np.sum(array, axis=axes, keepdims=keepdims),
            "mean": np.mean(array, axis=axes, keepdims=keepdims),
            "min": np.min(array, axis=axes, keepdims=keepdims),
            "max": np.max(array, axis=axes, keepdims=keepdims),
            "std": np.std(array, axis=axes, keepdims=keepdims, ddof=ddof),
        }

    all_results = {
        "group_size": group_size,
        "valid_count": valid_count,
        "missing_count": missing_count,
        **operations,
    }
    expected_shape = contract["output_shape"]
    if any(list(np.shape(value)) != expected_shape for value in all_results.values()):
        raise AggregationError("calculated result does not match the predicted shape")

    return {
        "input": {
            "shape": list(array.shape),
            "dtype": str(array.dtype),
            "axis_names": contract["input_axis_names"],
        },
        "reduction": {
            "axes": contract["reduced_axes"],
            "axis_names": contract["reduced_axis_names"],
            "keepdims": keepdims,
            "output_shape": expected_shape,
            "output_axis_names": contract["output_axis_names"],
            "missing_policy": missing_policy,
            "ddof": int(ddof),
        },
        "aggregates": {name: describe_result(value) for name, value in all_results.items()},
    }


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise AggregationError("values must be valid JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit NumPy aggregates by named semantic axes")
    parser.add_argument("--values", default="[[1, 2, 3], [4, 5, 6]]")
    parser.add_argument(
        "--axis",
        type=int,
        nargs="+",
        help="one or more axes; omit to reduce all axes",
    )
    parser.add_argument("--axis-names", nargs="+")
    parser.add_argument("--keepdims", action="store_true")
    parser.add_argument(
        "--missing-policy",
        choices=("error", "omit"),
        default="error",
    )
    parser.add_argument("--ddof", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    axis: Axis
    if args.axis is None:
        axis = None
    elif len(args.axis) == 1:
        axis = args.axis[0]
    else:
        axis = tuple(args.axis)

    try:
        report = aggregate(
            parse_json(args.values),
            axis=axis,
            axis_names=args.axis_names,
            keepdims=args.keepdims,
            missing_policy=args.missing_policy,
            ddof=args.ddof,
        )
    except AggregationError as error:
        parser.exit(2, f"axis-aggregates: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
