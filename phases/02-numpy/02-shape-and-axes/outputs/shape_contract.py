from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import numpy as np


class ShapeContractError(ValueError):
    """Raised when an operation cannot satisfy its shape contract."""


def validate_shape(shape: Iterable[int], *, name: str = "shape") -> tuple[int, ...]:
    result = tuple(shape)
    if any(isinstance(length, bool) or not isinstance(length, int) for length in result):
        raise ShapeContractError(f"{name} must contain integers")
    if any(length < 0 for length in result):
        raise ShapeContractError(f"{name} cannot contain negative lengths")
    return result


def normalize_axes(axis: int | Iterable[int] | None, ndim: int) -> tuple[int, ...]:
    if ndim < 0:
        raise ShapeContractError("ndim cannot be negative")
    if axis is None:
        return tuple(range(ndim))

    raw_axes = (axis,) if isinstance(axis, int) else tuple(axis)
    normalized: list[int] = []
    for raw_axis in raw_axes:
        if isinstance(raw_axis, bool) or not isinstance(raw_axis, int):
            raise ShapeContractError("axis must contain integers")
        current = raw_axis + ndim if raw_axis < 0 else raw_axis
        if current < 0 or current >= ndim:
            raise ShapeContractError(f"axis {raw_axis} is out of bounds for ndim={ndim}")
        if current in normalized:
            raise ShapeContractError(f"axis {raw_axis} is repeated")
        normalized.append(current)
    return tuple(sorted(normalized))


def reduction_shape(
    shape: Sequence[int],
    axis: int | Iterable[int] | None,
    *,
    keepdims: bool = False,
) -> tuple[int, ...]:
    source = validate_shape(shape)
    axes = set(normalize_axes(axis, len(source)))
    if keepdims:
        return tuple(1 if index in axes else length for index, length in enumerate(source))
    return tuple(length for index, length in enumerate(source) if index not in axes)


def reshape_shape(shape: Sequence[int], target: Sequence[int]) -> tuple[int, ...]:
    source = validate_shape(shape)
    requested = tuple(target)
    if any(isinstance(length, bool) or not isinstance(length, int) for length in requested):
        raise ShapeContractError("target shape must contain integers")
    if requested.count(-1) > 1 or any(length < -1 for length in requested):
        raise ShapeContractError("target shape allows at most one inferred -1")

    source_size = math.prod(source)
    known_product = math.prod(length for length in requested if length != -1)
    if -1 in requested:
        if known_product == 0 or source_size % known_product:
            raise ShapeContractError(f"cannot infer target {requested} from {source_size} elements")
        inferred = source_size // known_product
        requested = tuple(inferred if length == -1 else length for length in requested)

    if math.prod(requested) != source_size:
        raise ShapeContractError(
            f"reshape changes element count from {source_size} to {math.prod(requested)}"
        )
    return requested


def transpose_shape(shape: Sequence[int], axes: Sequence[int] | None = None) -> tuple[int, ...]:
    source = validate_shape(shape)
    permutation = tuple(reversed(range(len(source)))) if axes is None else tuple(axes)
    if sorted(permutation) != list(range(len(source))):
        raise ShapeContractError(f"axes {permutation} are not a permutation of dimensions")
    return tuple(source[index] for index in permutation)


def expand_dims_shape(shape: Sequence[int], axis: int) -> tuple[int, ...]:
    source = validate_shape(shape)
    ndim = len(source) + 1
    normalized = axis + ndim if axis < 0 else axis
    if normalized < 0 or normalized >= ndim:
        raise ShapeContractError(f"axis {axis} is out of bounds for expanded ndim={ndim}")
    return (*source[:normalized], 1, *source[normalized:])


def assert_shape(array: np.ndarray, expected: Sequence[int], *, name: str = "array") -> None:
    expected_shape = validate_shape(expected, name="expected shape")
    if array.shape != expected_shape:
        raise ShapeContractError(f"{name} has shape {array.shape}, expected {expected_shape}")


def parse_json_sequence(raw: str, *, name: str) -> list[int]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ShapeContractError(f"{name} must be valid JSON") from error
    if not isinstance(value, list):
        raise ShapeContractError(f"{name} must be a JSON array")
    return value


def build_report(
    shape: Sequence[int],
    *,
    axis: int | Iterable[int] | None = None,
    keepdims: bool = False,
    reshape: Sequence[int] | None = None,
    transpose: Sequence[int] | None = None,
    expand_axis: int | None = None,
) -> dict[str, Any]:
    source = validate_shape(shape)
    report: dict[str, Any] = {
        "source_shape": list(source),
        "ndim": len(source),
        "size": math.prod(source),
        "operations": {},
    }
    reduced = reduction_shape(source, axis, keepdims=keepdims)
    report["operations"]["reduction"] = {
        "axis": None if axis is None else list(normalize_axes(axis, len(source))),
        "keepdims": keepdims,
        "result_shape": list(reduced),
    }
    if reshape is not None:
        report["operations"]["reshape"] = {
            "requested": list(reshape),
            "result_shape": list(reshape_shape(source, reshape)),
        }
    if transpose is not None:
        report["operations"]["transpose"] = {
            "axes": list(transpose),
            "result_shape": list(transpose_shape(source, transpose)),
        }
    if expand_axis is not None:
        report["operations"]["expand_dims"] = {
            "axis": expand_axis,
            "result_shape": list(expand_dims_shape(source, expand_axis)),
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Predict NumPy operation shapes")
    parser.add_argument("--shape", default="[2, 3, 4]", help="JSON array of axis lengths")
    parser.add_argument("--axis", type=int, help="Reduction axis; default reduces all axes")
    parser.add_argument("--keepdims", action="store_true")
    parser.add_argument("--reshape", help="Optional target shape as JSON")
    parser.add_argument("--transpose", help="Optional axis permutation as JSON")
    parser.add_argument("--expand-axis", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = build_report(
            parse_json_sequence(args.shape, name="shape"),
            axis=args.axis,
            keepdims=args.keepdims,
            reshape=(parse_json_sequence(args.reshape, name="reshape") if args.reshape else None),
            transpose=(
                parse_json_sequence(args.transpose, name="transpose") if args.transpose else None
            ),
            expand_axis=args.expand_axis,
        )
    except ShapeContractError as error:
        parser.exit(2, f"shape-contract: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
