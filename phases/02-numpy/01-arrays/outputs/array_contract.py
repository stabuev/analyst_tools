from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np


class ArrayContractError(ValueError):
    """Raised when values do not satisfy the requested array contract."""


def _axis_names(ndim: int, axes: Sequence[str] | None) -> tuple[str, ...]:
    if axes is None:
        return tuple(f"axis_{index}" for index in range(ndim))

    names = tuple(axes)
    if len(names) != ndim:
        raise ArrayContractError(
            f"expected {ndim} axis names for an array with ndim={ndim}, got {len(names)}"
        )
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ArrayContractError("axis names must be non-empty strings")
    if len(set(names)) != len(names):
        raise ArrayContractError("axis names must be unique")
    return names


def as_array(values: object) -> np.ndarray[Any, Any]:
    """Convert an array-like object to ndarray and explain a ragged input clearly."""
    try:
        return np.asarray(values)
    except (TypeError, ValueError) as error:
        raise ArrayContractError(
            "values must form a rectangular array; check lengths of nested sequences"
        ) from error


def describe_array(
    values: object,
    *,
    axes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return the observable ndarray contract with optional semantic axis names."""
    array = as_array(values)
    names = _axis_names(array.ndim, axes)

    return {
        "source_type": type(values).__name__,
        "input_is_ndarray": isinstance(values, np.ndarray),
        "ndim": int(array.ndim),
        "shape": tuple(int(length) for length in array.shape),
        "size": int(array.size),
        "dtype": str(array.dtype),
        "is_numeric": bool(np.issubdtype(array.dtype, np.number)),
        "axes": {
            name: int(length)
            for name, length in zip(names, array.shape, strict=True)
        },
    }


def require_numeric_array(
    values: object,
    *,
    axes: Sequence[str] | None = None,
) -> np.ndarray[Any, Any]:
    """Return an ndarray or reject values outside this lesson's numeric contract."""
    array = as_array(values)
    _axis_names(array.ndim, axes)

    if not np.issubdtype(array.dtype, np.number):
        raise ArrayContractError(
            f"expected numeric data, but NumPy selected dtype {array.dtype}"
        )
    return array


def format_contract(report: dict[str, Any]) -> str:
    """Render a compact human-readable array passport."""
    shape = report["shape"]
    shape_text = str(shape) if shape else "()"
    lines = [
        "Array contract",
        f"source: {report['source_type']}",
        f"ndim: {report['ndim']}",
        f"shape: {shape_text}",
        f"size: {report['size']}",
        f"dtype: {report['dtype']}",
        f"numeric: {report['is_numeric']}",
        "axes:",
    ]
    if report["axes"]:
        lines.extend(
            f"- {name}: {length}" for name, length in report["axes"].items()
        )
    else:
        lines.append("- none (0-dimensional array)")
    return "\n".join(lines) + "\n"


def main() -> None:
    order_counts = [[12, 15, 9], [10, 11, 14]]
    report = describe_array(order_counts, axes=("store", "day"))
    print(format_contract(report), end="")


if __name__ == "__main__":
    main()
