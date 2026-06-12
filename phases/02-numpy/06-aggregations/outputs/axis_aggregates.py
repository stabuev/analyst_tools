from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


class AggregationError(ValueError):
    """Raised when an aggregation contract is invalid."""


def normalize_axis(axis: int | None, ndim: int) -> int | None:
    if axis is None:
        return None
    normalized = axis + ndim if axis < 0 else axis
    if normalized < 0 or normalized >= ndim:
        raise AggregationError(f"axis {axis} is out of bounds for ndim={ndim}")
    return normalized


def manual_sum_2d(values: list[list[float]], axis: int) -> list[float]:
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


def to_json_value(value: np.ndarray | np.generic) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value.item()


def result_shape(value: np.ndarray | np.generic) -> list[int]:
    return list(np.shape(value))


def aggregate(
    values: object,
    *,
    axis: int | None,
    keepdims: bool = False,
    ddof: int = 0,
) -> dict[str, Any]:
    array = np.asarray(values, dtype=float)
    if array.size == 0:
        raise AggregationError("values must not be empty")
    if not np.isfinite(array).all():
        raise AggregationError("values must contain only finite numbers")
    if ddof < 0:
        raise AggregationError("ddof cannot be negative")
    normalized_axis = normalize_axis(axis, array.ndim)
    reduced_count = array.size if normalized_axis is None else array.shape[normalized_axis]
    if ddof >= reduced_count:
        raise AggregationError("ddof must be smaller than the reduced observation count")

    count = np.sum(
        np.ones(array.shape, dtype=np.int64),
        axis=normalized_axis,
        keepdims=keepdims,
    )
    operations = {
        "count": count,
        "sum": np.sum(array, axis=normalized_axis, keepdims=keepdims),
        "mean": np.mean(array, axis=normalized_axis, keepdims=keepdims),
        "min": np.min(array, axis=normalized_axis, keepdims=keepdims),
        "max": np.max(array, axis=normalized_axis, keepdims=keepdims),
        "std": np.std(array, axis=normalized_axis, keepdims=keepdims, ddof=ddof),
    }
    return {
        "input_shape": list(array.shape),
        "axis": normalized_axis,
        "axis_meaning": "all axes" if normalized_axis is None else f"axis {normalized_axis}",
        "keepdims": keepdims,
        "ddof": ddof,
        "aggregates": {
            name: {
                "value": to_json_value(value),
                "shape": result_shape(value),
            }
            for name, value in operations.items()
        },
    }


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise AggregationError("values must be valid JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate axis-aware NumPy aggregates")
    parser.add_argument("--values", default="[[1, 2, 3], [4, 5, 6]]")
    parser.add_argument("--axis", type=int)
    parser.add_argument("--keepdims", action="store_true")
    parser.add_argument("--ddof", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = aggregate(
            parse_json(args.values),
            axis=args.axis,
            keepdims=args.keepdims,
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
