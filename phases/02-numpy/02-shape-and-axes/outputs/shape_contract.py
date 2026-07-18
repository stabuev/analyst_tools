from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable, Sequence
from numbers import Integral
from pathlib import Path
from typing import Any

import numpy as np


class ShapeContractError(ValueError):
    """Raised when an operation cannot satisfy its shape contract."""


def validate_shape(shape: Iterable[int], *, name: str = "shape") -> tuple[int, ...]:
    raw_shape = tuple(shape)
    if any(isinstance(length, bool) or not isinstance(length, Integral) for length in raw_shape):
        raise ShapeContractError(f"{name} must contain integers")
    result = tuple(int(length) for length in raw_shape)
    if any(length < 0 for length in result):
        raise ShapeContractError(f"{name} cannot contain negative lengths")
    return result


def validate_axis_names(
    axis_names: Sequence[str],
    ndim: int,
    *,
    name: str = "axis names",
) -> tuple[str, ...]:
    if isinstance(axis_names, (str, bytes)):
        raise ShapeContractError(f"{name} must be a sequence of names")
    result = tuple(axis_names)
    if len(result) != ndim:
        raise ShapeContractError(f"{name} has {len(result)} names, expected {ndim}")
    if any(not isinstance(axis_name, str) or not axis_name.strip() for axis_name in result):
        raise ShapeContractError(f"{name} must contain non-empty strings")
    if len(set(result)) != len(result):
        raise ShapeContractError(f"{name} must be unique")
    return result


def normalize_axes(axis: int | Iterable[int] | None, ndim: int) -> tuple[int, ...]:
    if ndim < 0:
        raise ShapeContractError("ndim cannot be negative")
    if axis is None:
        return tuple(range(ndim))

    raw_axes = (axis,) if isinstance(axis, (Integral, bool)) else tuple(axis)
    normalized: list[int] = []
    for raw_axis in raw_axes:
        if isinstance(raw_axis, bool) or not isinstance(raw_axis, Integral):
            raise ShapeContractError("axis must contain integers")
        axis_number = int(raw_axis)
        current = axis_number + ndim if axis_number < 0 else axis_number
        if current < 0 or current >= ndim:
            raise ShapeContractError(f"axis {axis_number} is out of bounds for ndim={ndim}")
        if current in normalized:
            raise ShapeContractError(f"axis {axis_number} is repeated")
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
    raw_target = tuple(target)
    if any(isinstance(length, bool) or not isinstance(length, Integral) for length in raw_target):
        raise ShapeContractError("target shape must contain integers")
    requested = tuple(int(length) for length in raw_target)
    if requested.count(-1) > 1 or any(length < -1 for length in requested):
        raise ShapeContractError("target shape allows at most one inferred -1")

    source_size = math.prod(source)
    known_product = math.prod(length for length in requested if length != -1)
    if -1 in requested:
        if known_product == 0 or source_size % known_product:
            raise ShapeContractError(f"cannot infer target {requested} from {source_size} elements")
        inferred = source_size // known_product
        requested = tuple(inferred if length == -1 else length for length in requested)

    target_size = math.prod(requested)
    if target_size != source_size:
        raise ShapeContractError(
            f"reshape changes element count from {source_size} to {target_size}"
        )
    return requested


def transpose_shape(shape: Sequence[int], axes: Sequence[int] | None = None) -> tuple[int, ...]:
    source = validate_shape(shape)
    raw_axes = tuple(reversed(range(len(source)))) if axes is None else tuple(axes)
    if any(isinstance(axis, bool) or not isinstance(axis, Integral) for axis in raw_axes):
        raise ShapeContractError("transpose axes must contain integers")
    permutation = tuple(int(axis) for axis in raw_axes)
    if sorted(permutation) != list(range(len(source))):
        raise ShapeContractError(f"axes {permutation} are not a permutation of dimensions")
    return tuple(source[index] for index in permutation)


def expand_dims_shape(shape: Sequence[int], axis: int) -> tuple[int, ...]:
    source = validate_shape(shape)
    if isinstance(axis, bool) or not isinstance(axis, Integral):
        raise ShapeContractError("expand axis must be an integer")
    result_ndim = len(source) + 1
    axis_number = int(axis)
    normalized = axis_number + result_ndim if axis_number < 0 else axis_number
    if normalized < 0 or normalized >= result_ndim:
        raise ShapeContractError(
            f"axis {axis_number} is out of bounds for expanded ndim={result_ndim}"
        )
    return (*source[:normalized], 1, *source[normalized:])


def axis_descriptors(
    shape: Sequence[int],
    axis_names: Sequence[str] | None = None,
) -> list[dict[str, int | str]]:
    valid_shape = validate_shape(shape)
    names = None if axis_names is None else validate_axis_names(axis_names, len(valid_shape))
    return [
        {
            "axis": index,
            **({"name": names[index]} if names is not None else {}),
            "length": length,
        }
        for index, length in enumerate(valid_shape)
    ]


def assert_shape(
    array: np.ndarray,
    expected: Sequence[int],
    *,
    name: str = "array",
    axis_names: Sequence[str] | None = None,
) -> None:
    expected_shape = validate_shape(expected, name="expected shape")
    names = None if axis_names is None else validate_axis_names(axis_names, len(expected_shape))
    if array.shape == expected_shape:
        return

    named_expected = (
        ", ".join(
            f"{axis_name}={length}"
            for axis_name, length in zip(names, expected_shape, strict=True)
        )
        if names is not None
        else str(expected_shape)
    )
    raise ShapeContractError(
        f"{name} has shape {array.shape}, expected {expected_shape} ({named_expected})"
    )


def parse_json_sequence(raw: str, *, name: str) -> list[Any]:
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
    axis_names: Sequence[str] | None = None,
    axis: int | Iterable[int] | None = None,
    keepdims: bool = False,
    reshape: Sequence[int] | None = None,
    reshape_axis_names: Sequence[str] | None = None,
    transpose: Sequence[int] | None = None,
    expand_axis: int | None = None,
    expand_axis_name: str | None = None,
) -> dict[str, Any]:
    source = validate_shape(shape)
    names = None if axis_names is None else validate_axis_names(axis_names, len(source))
    normalized_reduction_axes = normalize_axes(axis, len(source))
    reduced_shape = reduction_shape(source, axis, keepdims=keepdims)
    reduced_names = None
    if names is not None:
        reduced_names = (
            names
            if keepdims
            else tuple(
                axis_name
                for index, axis_name in enumerate(names)
                if index not in normalized_reduction_axes
            )
        )

    report: dict[str, Any] = {
        "source_shape": list(source),
        "ndim": len(source),
        "size": math.prod(source),
        "axis_names": None if names is None else list(names),
        "axes": axis_descriptors(source, names),
        "operations": {
            "reduction": {
                "normalized_axes": list(normalized_reduction_axes),
                "operated_axis_names": (
                    None
                    if names is None
                    else [names[index] for index in normalized_reduction_axes]
                ),
                "keepdims": keepdims,
                "result_shape": list(reduced_shape),
                "result_axis_names": None if reduced_names is None else list(reduced_names),
            }
        },
    }

    if reshape is not None:
        reshaped = reshape_shape(source, reshape)
        target_names = (
            None
            if reshape_axis_names is None
            else validate_axis_names(reshape_axis_names, len(reshaped), name="reshape axis names")
        )
        reshape_report: dict[str, Any] = {
            "requested": list(reshape),
            "result_shape": list(reshaped),
            "result_axis_names": None if target_names is None else list(target_names),
        }
        if names is not None and target_names is None:
            reshape_report["semantic_warning"] = (
                "reshape preserves element count, not axis meaning; name target axes explicitly"
            )
        report["operations"]["reshape"] = reshape_report
    elif reshape_axis_names is not None:
        raise ShapeContractError("reshape axis names require a reshape target")

    if transpose is not None:
        transposed = transpose_shape(source, transpose)
        transposed_names = None if names is None else tuple(names[index] for index in transpose)
        report["operations"]["transpose"] = {
            "axes": list(transpose),
            "result_shape": list(transposed),
            "result_axis_names": (
                None if transposed_names is None else list(transposed_names)
            ),
        }

    if expand_axis is not None:
        expanded = expand_dims_shape(source, expand_axis)
        expanded_names = None
        if names is not None and expand_axis_name is not None:
            result_ndim = len(source) + 1
            normalized = expand_axis + result_ndim if expand_axis < 0 else expand_axis
            expanded_names = (*names[:normalized], expand_axis_name, *names[normalized:])
            expanded_names = validate_axis_names(expanded_names, result_ndim)
        expand_report: dict[str, Any] = {
            "axis": expand_axis,
            "result_shape": list(expanded),
            "result_axis_names": None if expanded_names is None else list(expanded_names),
        }
        if names is not None and expand_axis_name is None:
            expand_report["semantic_warning"] = "name the new length-one axis explicitly"
        report["operations"]["expand_dims"] = expand_report
    elif expand_axis_name is not None:
        raise ShapeContractError("expand axis name requires expand_axis")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Predict NumPy shapes and preserve the semantic names of their axes"
    )
    parser.add_argument("--shape", default="[2, 3, 2]", help="JSON array of axis lengths")
    parser.add_argument("--axis-names", help="Optional JSON array of semantic axis names")
    parser.add_argument("--axis", type=int, help="Reduction axis; default reduces all axes")
    parser.add_argument("--keepdims", action="store_true")
    parser.add_argument("--reshape", help="Optional target shape as JSON")
    parser.add_argument("--reshape-axis-names", help="Semantic names for reshape result axes")
    parser.add_argument("--transpose", help="Optional axis permutation as JSON")
    parser.add_argument("--expand-axis", type=int)
    parser.add_argument("--expand-axis-name", help="Semantic name for a newly inserted axis")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = build_report(
            parse_json_sequence(args.shape, name="shape"),
            axis_names=(
                parse_json_sequence(args.axis_names, name="axis names")
                if args.axis_names
                else None
            ),
            axis=args.axis,
            keepdims=args.keepdims,
            reshape=(parse_json_sequence(args.reshape, name="reshape") if args.reshape else None),
            reshape_axis_names=(
                parse_json_sequence(args.reshape_axis_names, name="reshape axis names")
                if args.reshape_axis_names
                else None
            ),
            transpose=(
                parse_json_sequence(args.transpose, name="transpose") if args.transpose else None
            ),
            expand_axis=args.expand_axis,
            expand_axis_name=args.expand_axis_name,
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
