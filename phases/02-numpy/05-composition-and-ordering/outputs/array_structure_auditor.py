from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from numbers import Integral
from pathlib import Path
from typing import Any

import numpy as np


class StructureError(ValueError):
    """Raised when arrays cannot be combined or reordered safely."""


def _as_array(values: object, *, name: str) -> np.ndarray:
    try:
        array = np.asarray(values)
    except (TypeError, ValueError) as error:
        raise StructureError(f"{name} must form a rectangular array") from error
    if array.ndim == 0:
        raise StructureError(f"{name} must have at least one axis")
    if array.size == 0 or any(length == 0 for length in array.shape):
        raise StructureError(f"{name} must not contain empty axes")
    if array.dtype == object:
        raise StructureError(f"{name} must have a homogeneous non-object dtype")
    return array


def _axis_names(axis_names: Sequence[str], ndim: int) -> tuple[str, ...]:
    names = tuple(axis_names)
    if len(names) != ndim:
        raise StructureError(f"expected {ndim} axis names, got {len(names)}")
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise StructureError("axis names must be non-empty strings")
    if len(set(names)) != len(names):
        raise StructureError("axis names must be unique")
    return names


def _normalize_axis(axis: int, ndim: int, *, insertion: bool = False) -> int:
    if not isinstance(axis, Integral) or isinstance(axis, bool):
        raise StructureError("axis must be an integer")
    output_ndim = ndim + 1 if insertion else ndim
    normalized = int(axis) + output_ndim if axis < 0 else int(axis)
    if normalized < 0 or normalized >= output_ndim:
        action = "insertion" if insertion else "existing"
        raise StructureError(f"axis {axis} is not a valid {action} axis for ndim={ndim}")
    return normalized


def combine_report(
    arrays: Sequence[object],
    *,
    mode: str,
    axis: int,
    axis_names: Sequence[str],
    new_axis_name: str | None = None,
    allow_dtype_promotion: bool = False,
) -> dict[str, Any]:
    """Combine arrays and expose the structural contract of the result."""
    if len(arrays) < 2:
        raise StructureError("combine expects at least two arrays")
    converted = [_as_array(values, name=f"arrays[{index}]") for index, values in enumerate(arrays)]
    ndim = converted[0].ndim
    if any(array.ndim != ndim for array in converted[1:]):
        raise StructureError("all arrays must have the same number of axes")
    names = _axis_names(axis_names, ndim)

    dtypes = [array.dtype for array in converted]
    if not allow_dtype_promotion and any(dtype != dtypes[0] for dtype in dtypes[1:]):
        raise StructureError(
            "input dtypes differ; align them first or choose allow_dtype_promotion explicitly"
        )

    input_shapes = [array.shape for array in converted]
    if mode == "concatenate":
        normalized_axis = _normalize_axis(axis, ndim)
        reference = input_shapes[0]
        for shape in input_shapes[1:]:
            mismatches = [
                index
                for index, (left, right) in enumerate(zip(reference, shape, strict=True))
                if index != normalized_axis and left != right
            ]
            if mismatches:
                raise StructureError(
                    "concatenate requires equal lengths on every non-concatenated axis"
                )
        result = np.concatenate(converted, axis=normalized_axis)
        output_axis_names = names
        axis_role = "existing"
    elif mode == "stack":
        normalized_axis = _normalize_axis(axis, ndim, insertion=True)
        if any(shape != input_shapes[0] for shape in input_shapes[1:]):
            raise StructureError("stack requires exactly equal input shapes")
        if not isinstance(new_axis_name, str) or not new_axis_name.strip():
            raise StructureError("stack requires a non-empty new_axis_name")
        if new_axis_name in names:
            raise StructureError("new_axis_name must not duplicate an existing axis name")
        result = np.stack(converted, axis=normalized_axis)
        output_axis_names = names[:normalized_axis] + (new_axis_name,) + names[normalized_axis:]
        axis_role = "new"
    else:
        raise StructureError("mode must be 'concatenate' or 'stack'")

    if result.dtype == object:
        raise StructureError("combination produced object dtype")
    return {
        "operation": mode,
        "axis": normalized_axis,
        "axis_role": axis_role,
        "input": {
            "shapes": [list(shape) for shape in input_shapes],
            "dtypes": [str(dtype) for dtype in dtypes],
            "axis_names": list(names),
        },
        "output": {
            "shape": list(result.shape),
            "dtype": str(result.dtype),
            "axis_names": list(output_axis_names),
            "value": result.tolist(),
            "nbytes": int(result.nbytes),
            "shares_memory_with_input": [
                bool(np.shares_memory(result, array)) for array in converted
            ],
        },
        "dtype_promotion_allowed": allow_dtype_promotion,
    }


def manual_stable_permutation(keys: Sequence[float], *, direction: str = "ascending") -> list[int]:
    """Show that sorting related arrays starts with sorting positions."""
    if direction not in {"ascending", "descending"}:
        raise StructureError("direction must be 'ascending' or 'descending'")
    if len(keys) == 0:
        raise StructureError("keys must not be empty")
    try:
        return sorted(range(len(keys)), key=keys.__getitem__, reverse=direction == "descending")
    except TypeError as error:
        raise StructureError("keys must be mutually comparable") from error


def _descending_stable_permutation(keys: np.ndarray, ascending: np.ndarray) -> np.ndarray:
    """Reverse value groups while preserving the order inside every tie."""
    sorted_keys = keys[ascending]
    starts = np.r_[0, np.flatnonzero(sorted_keys[1:] != sorted_keys[:-1]) + 1]
    ends = np.r_[starts[1:], len(ascending)]
    groups = [ascending[start:end] for start, end in zip(starts, ends, strict=True)]
    return np.concatenate(groups[::-1])


def _numeric_keys(values: object) -> np.ndarray:
    keys = _as_array(values, name="keys")
    if keys.ndim != 1:
        raise StructureError("keys must be one-dimensional")
    if (
        not np.issubdtype(keys.dtype, np.number)
        or np.issubdtype(keys.dtype, np.bool_)
        or np.issubdtype(keys.dtype, np.complexfloating)
    ):
        raise StructureError("keys must contain real numbers")
    if np.isinf(keys).any():
        raise StructureError("infinite keys are not supported")
    return keys


def _arrays_equal(left: np.ndarray, right: np.ndarray) -> bool:
    if np.issubdtype(left.dtype, np.inexact):
        return bool(np.array_equal(left, right, equal_nan=True))
    return bool(np.array_equal(left, right))


def aligned_order_report(
    keys: object,
    payloads: Mapping[str, object],
    *,
    direction: str = "ascending",
    nan_policy: str = "error",
) -> dict[str, Any]:
    """Apply one stable ordering permutation to keys and all related values."""
    key_array = _numeric_keys(keys)
    if direction not in {"ascending", "descending"}:
        raise StructureError("direction must be 'ascending' or 'descending'")
    if nan_policy not in {"error", "last"}:
        raise StructureError("nan_policy must be 'error' or 'last'")
    if not isinstance(payloads, Mapping) or not payloads:
        raise StructureError("payloads must be a non-empty mapping")

    converted_payloads: dict[str, np.ndarray] = {}
    for name, values in payloads.items():
        if not isinstance(name, str) or not name:
            raise StructureError("payload names must be non-empty strings")
        array = _as_array(values, name=f"payloads[{name!r}]")
        if array.ndim != 1 or len(array) != len(key_array):
            raise StructureError("every payload must be 1D and have the same length as keys")
        converted_payloads[name] = array

    missing = np.isnan(key_array)
    if missing.any() and nan_policy == "error":
        raise StructureError("NaN keys found; choose nan_policy='last' explicitly")
    valid_positions = np.flatnonzero(~missing)
    if valid_positions.size == 0:
        raise StructureError("at least one finite key is required")

    local_ascending = np.argsort(key_array[valid_positions], kind="stable")
    ascending = valid_positions[local_ascending]
    if direction == "descending":
        ordered_valid = _descending_stable_permutation(key_array, ascending)
    else:
        ordered_valid = ascending
    permutation = np.concatenate((ordered_valid, np.flatnonzero(missing)))
    inverse = np.empty(len(permutation), dtype=np.intp)
    inverse[permutation] = np.arange(len(permutation))

    sorted_keys = key_array[permutation]
    sorted_payloads = {name: array[permutation] for name, array in converted_payloads.items()}
    restored_keys = sorted_keys[inverse]
    return {
        "direction": direction,
        "nan_policy": nan_policy,
        "tie_policy": "stable: equal keys keep their original relative order",
        "permutation": permutation.tolist(),
        "inverse_permutation": inverse.tolist(),
        "sorted_keys": sorted_keys.tolist(),
        "sorted_payloads": {name: array.tolist() for name, array in sorted_payloads.items()},
        "argmin_first": int(np.nanargmin(key_array)),
        "argmax_first": int(np.nanargmax(key_array)),
        "restoration_check": _arrays_equal(restored_keys, key_array),
    }


def unique_report(values: object) -> dict[str, Any]:
    """Explain unique values through counts, first positions, and reconstruction."""
    array = _as_array(values, name="values")
    if array.ndim != 1:
        raise StructureError("values must be one-dimensional")
    unique, first_indices, inverse, counts = np.unique(
        array,
        return_index=True,
        return_inverse=True,
        return_counts=True,
    )
    first_seen_order = np.argsort(first_indices, kind="stable")
    reconstructed = unique[inverse]
    return {
        "input_size": int(array.size),
        "unique_size": int(unique.size),
        "duplicate_count": int(array.size - unique.size),
        "sorted_unique_values": unique.tolist(),
        "counts": counts.tolist(),
        "inverse_indices": inverse.tolist(),
        "first_indices_in_sorted_unique_order": first_indices.tolist(),
        "values_in_first_seen_order": unique[first_seen_order].tolist(),
        "reconstruction_check": _arrays_equal(reconstructed, array),
    }


def _parse_json(raw: str, *, name: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise StructureError(f"{name} must be valid JSON") from error


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    rendered = json.dumps(_json_safe(report), ensure_ascii=False, indent=2, allow_nan=False)
    if output is None:
        print(rendered)
    else:
        output.write_text(rendered + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit composition, ordering, and uniqueness of related NumPy arrays"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    combine = subparsers.add_parser("combine", help="concatenate or stack arrays")
    combine.add_argument("--arrays", required=True, help="JSON list of arrays")
    combine.add_argument("--mode", choices=("concatenate", "stack"), required=True)
    combine.add_argument("--axis", type=int, required=True)
    combine.add_argument("--axis-names", nargs="+", required=True)
    combine.add_argument("--new-axis-name")
    combine.add_argument("--allow-dtype-promotion", action="store_true")
    combine.add_argument("--output", type=Path)

    order = subparsers.add_parser("order", help="sort related arrays by one key")
    order.add_argument("--keys", required=True, help="JSON list of numeric keys")
    order.add_argument("--payloads", required=True, help="JSON object of related arrays")
    order.add_argument("--direction", choices=("ascending", "descending"), default="ascending")
    order.add_argument("--nan-policy", choices=("error", "last"), default="error")
    order.add_argument("--output", type=Path)

    unique = subparsers.add_parser("unique", help="explain unique values and counts")
    unique.add_argument("--values", required=True, help="JSON list")
    unique.add_argument("--output", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "combine":
            report = combine_report(
                _parse_json(args.arrays, name="arrays"),
                mode=args.mode,
                axis=args.axis,
                axis_names=args.axis_names,
                new_axis_name=args.new_axis_name,
                allow_dtype_promotion=args.allow_dtype_promotion,
            )
        elif args.command == "order":
            payloads = _parse_json(args.payloads, name="payloads")
            if not isinstance(payloads, dict):
                raise StructureError("payloads JSON must be an object")
            report = aligned_order_report(
                _parse_json(args.keys, name="keys"),
                payloads,
                direction=args.direction,
                nan_policy=args.nan_policy,
            )
        else:
            report = unique_report(_parse_json(args.values, name="values"))
        _write_report(report, args.output)
    except (OSError, StructureError) as error:
        parser.exit(2, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
