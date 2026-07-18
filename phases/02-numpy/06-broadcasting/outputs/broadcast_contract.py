from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import numpy as np


class BroadcastingError(ValueError):
    """Raised when a broadcast contract cannot be constructed."""


OPERATIONS: dict[str, np.ufunc] = {
    "add": np.add,
    "subtract": np.subtract,
    "multiply": np.multiply,
    "true_divide": np.true_divide,
    "maximum": np.maximum,
    "equal": np.equal,
    "less": np.less,
}

COMPARISON_OPERATIONS = {"equal", "less"}
ARITHMETIC_OPERATIONS = {"add", "subtract", "multiply", "true_divide"}


def validate_shape(shape: Sequence[object]) -> tuple[int, ...]:
    normalized: list[int] = []
    for length in shape:
        if isinstance(length, bool) or not isinstance(length, Integral):
            raise BroadcastingError("shape lengths must be integers")
        number = int(length)
        if number < 0:
            raise BroadcastingError("shape lengths cannot be negative")
        normalized.append(number)
    return tuple(normalized)


def merge_lengths(left: int, right: int) -> int:
    """Merge two aligned lengths, including the zero-versus-one case."""
    if left == right:
        return left
    if left == 1:
        return right
    if right == 1:
        return left
    raise BroadcastingError(f"aligned lengths {left} and {right} are incompatible")


def broadcast_shape(*shapes: Sequence[object]) -> tuple[int, ...]:
    """Predict NumPy's common shape without allocating the output."""
    result: tuple[int, ...] = ()
    for raw_shape in shapes:
        shape = validate_shape(raw_shape)
        width = max(len(result), len(shape))
        left = (1,) * (width - len(result)) + result
        right = (1,) * (width - len(shape)) + shape
        try:
            result = tuple(
                merge_lengths(left_length, right_length)
                for left_length, right_length in zip(left, right, strict=True)
            )
        except BroadcastingError as error:
            raise BroadcastingError(
                f"shapes {result} and {shape} are incompatible: {error}"
            ) from error
    return result


def validate_axis_names(
    axis_names: object,
    *,
    ndim: int,
    operand_name: str,
) -> tuple[str, ...]:
    if axis_names is None:
        return tuple(f"axis_{index}" for index in range(ndim))
    if isinstance(axis_names, (str, bytes)) or not isinstance(axis_names, Sequence):
        raise BroadcastingError(f"{operand_name} axis_names must be a sequence")
    names = tuple(axis_names)
    if len(names) != ndim:
        raise BroadcastingError(
            f"{operand_name} has ndim={ndim}, but {len(names)} axis names were supplied"
        )
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise BroadcastingError(f"{operand_name} axis names must be non-empty strings")
    if len(set(names)) != len(names):
        raise BroadcastingError(f"{operand_name} axis names must be unique")
    return names


def normalize_operand(raw: object, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise BroadcastingError("each operand must be a JSON object")
    name = raw.get("name", f"operand_{index}")
    if not isinstance(name, str) or not name.strip():
        raise BroadcastingError("operand name must be a non-empty string")
    if "shape" not in raw:
        raise BroadcastingError(f"{name} must declare shape")
    shape_raw = raw["shape"]
    if isinstance(shape_raw, (str, bytes)) or not isinstance(shape_raw, Sequence):
        raise BroadcastingError(f"{name} shape must be a sequence")
    shape = validate_shape(shape_raw)
    axis_names = validate_axis_names(
        raw.get("axis_names"),
        ndim=len(shape),
        operand_name=name,
    )
    try:
        dtype = np.dtype(raw.get("dtype", "float64"))
    except TypeError as error:
        raise BroadcastingError(f"{name} has invalid dtype {raw.get('dtype')!r}") from error
    return {
        "name": name,
        "shape": shape,
        "axis_names": axis_names,
        "dtype": dtype,
    }


def semantic_axis_name(name: str) -> str:
    prefix = "summarized_"
    return name[len(prefix) :] if name.startswith(prefix) else name


def build_alignment(
    operands: Sequence[dict[str, Any]],
    output_shape: tuple[int, ...],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    width = len(output_shape)
    aligned_operands: list[dict[str, Any]] = []
    for operand in operands:
        padding = width - len(operand["shape"])
        aligned_operands.append(
            {
                **operand,
                "aligned_shape": (1,) * padding + operand["shape"],
                "aligned_axis_names": (None,) * padding + operand["axis_names"],
                "padding": padding,
            }
        )

    rows: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for output_axis, output_length in enumerate(output_shape):
        cells: list[dict[str, Any]] = []
        semantic_names: set[str] = set()
        preferred_names: list[str] = []
        for operand in aligned_operands:
            length = operand["aligned_shape"][output_axis]
            axis_name = operand["aligned_axis_names"][output_axis]
            implicit = output_axis < operand["padding"]
            input_axis = None if implicit else output_axis - operand["padding"]
            if axis_name is not None:
                semantic_names.add(semantic_axis_name(axis_name))
                if length == output_length and length != 1:
                    preferred_names.append(semantic_axis_name(axis_name))
            cells.append(
                {
                    "operand": operand["name"],
                    "input_axis": input_axis,
                    "axis_name": axis_name,
                    "length": length,
                    "implicit_leading_axis": implicit,
                    "expands": length == 1 and output_length != 1,
                }
            )

        if len(semantic_names) > 1:
            warnings.append(
                {
                    "code": "axis_name_conflict",
                    "output_axis": output_axis,
                    "message": (
                        f"aligned output axis {output_axis} combines semantic axes "
                        f"{sorted(semantic_names)}"
                    ),
                }
            )

        if preferred_names:
            output_name = preferred_names[0]
        elif len(semantic_names) == 1:
            output_name = next(iter(semantic_names))
        else:
            output_name = f"axis_{output_axis}"
        rows.append(
            {
                "output_axis": output_axis,
                "position_from_right": output_axis - width,
                "output_axis_name": output_name,
                "output_length": output_length,
                "operands": cells,
            }
        )
    return rows, warnings


def resolve_operation_dtype(
    left_dtype: np.dtype[Any],
    right_dtype: np.dtype[Any],
    operation: str,
) -> np.dtype[Any]:
    ufunc = OPERATIONS[operation]
    left = np.zeros((), dtype=left_dtype)
    right = np.zeros((), dtype=right_dtype)
    try:
        with np.errstate(all="ignore"):
            result = ufunc(left, right)
    except (TypeError, ValueError) as error:
        raise BroadcastingError(
            f"operation {operation!r} is not defined for {left_dtype} and {right_dtype}"
        ) from error
    return result.dtype


def expansion_factor(shape: tuple[int, ...], output_shape: tuple[int, ...]) -> int | None:
    source_size = math.prod(shape)
    output_size = math.prod(output_shape)
    if source_size == 0:
        return None
    return output_size // source_size


def analyze_broadcast(
    raw_operands: Sequence[object],
    *,
    operation: str = "subtract",
    memory_limit_mb: float = 256.0,
) -> dict[str, Any]:
    if len(raw_operands) != 2:
        raise BroadcastingError("operation contract expects exactly two operands")
    if operation not in OPERATIONS:
        raise BroadcastingError(f"unknown operation {operation!r}")
    if (
        isinstance(memory_limit_mb, bool)
        or not isinstance(memory_limit_mb, Real)
        or not math.isfinite(float(memory_limit_mb))
        or memory_limit_mb <= 0
    ):
        raise BroadcastingError("memory_limit_mb must be a positive finite number")

    operands = [normalize_operand(raw, index) for index, raw in enumerate(raw_operands)]
    output_shape = broadcast_shape(*(operand["shape"] for operand in operands))
    alignment, warnings = build_alignment(operands, output_shape)

    left_dtype = operands[0]["dtype"]
    right_dtype = operands[1]["dtype"]
    common_dtype = np.result_type(left_dtype, right_dtype)
    operation_error: str | None = None
    try:
        result_dtype = resolve_operation_dtype(left_dtype, right_dtype, operation)
    except BroadcastingError as error:
        result_dtype = None
        operation_error = str(error)
        warnings.append(
            {
                "code": "operation_not_defined",
                "message": operation_error,
            }
        )

    output_elements = math.prod(output_shape)
    output_nbytes = None if result_dtype is None else output_elements * result_dtype.itemsize
    memory_limit_bytes = int(float(memory_limit_mb) * 1024 * 1024)
    if output_nbytes is not None and output_nbytes > memory_limit_bytes:
        warnings.append(
            {
                "code": "output_exceeds_memory_limit",
                "message": (
                    f"logical result needs {output_nbytes} bytes, above limit "
                    f"{memory_limit_bytes} bytes"
                ),
            }
        )
    if (
        result_dtype is not None
        and operation in ARITHMETIC_OPERATIONS
        and np.issubdtype(result_dtype, np.integer)
    ):
        warnings.append(
            {
                "code": "integer_range_not_checked",
                "message": "integer result dtype does not guarantee that values cannot overflow",
            }
        )
    if operation in ARITHMETIC_OPERATIONS and all(
        np.issubdtype(operand["dtype"], np.bool_) for operand in operands
    ):
        warnings.append(
            {
                "code": "boolean_arithmetic",
                "message": (
                    "boolean arithmetic is defined, but logical operators express intent better"
                ),
            }
        )

    left_shape_can_store = operands[0]["shape"] == output_shape
    dtype_can_store = bool(
        result_dtype is not None and np.can_cast(result_dtype, left_dtype, casting="same_kind")
    )

    return {
        "operation": {
            "name": operation,
            "category": ("comparison" if operation in COMPARISON_OPERATIONS else "arithmetic"),
            "defined_for_dtypes": result_dtype is not None,
            "error": operation_error,
        },
        "operands": [
            {
                "name": operand["name"],
                "shape": list(operand["shape"]),
                "axis_names": list(operand["axis_names"]),
                "dtype": str(operand["dtype"]),
                "logical_expansion_factor": expansion_factor(operand["shape"], output_shape),
            }
            for operand in operands
        ],
        "alignment": alignment,
        "result": {
            "shape": list(output_shape),
            "axis_names": [row["output_axis_name"] for row in alignment],
            "element_count": output_elements,
            "common_input_dtype": str(common_dtype),
            "operation_dtype": None if result_dtype is None else str(result_dtype),
            "estimated_nbytes": output_nbytes,
        },
        "in_place_on_left": {
            "shape_can_store_result": left_shape_can_store,
            "dtype_can_store_result_with_same_kind": dtype_can_store,
            "allowed_by_shape_and_dtype": left_shape_can_store and dtype_can_store,
        },
        "memory_limit_mb": float(memory_limit_mb),
        "warnings": warnings,
    }


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise BroadcastingError("operands must be valid JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explain a NumPy broadcast operation before allocating its result"
    )
    parser.add_argument(
        "--operands",
        default=(
            '[{"name":"daily_metrics","shape":[2,3,2],'
            '"axis_names":["store","day","metric"],"dtype":"float64"},'
            '{"name":"metric_means","shape":[1,1,2],'
            '"axis_names":["summarized_store","summarized_day","metric"],'
            '"dtype":"float64"}]'
        ),
    )
    parser.add_argument("--operation", choices=tuple(OPERATIONS), default="subtract")
    parser.add_argument("--memory-limit-mb", type=float, default=256.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        operands = parse_json(args.operands)
        if not isinstance(operands, list):
            raise BroadcastingError("operands JSON must contain a list")
        report = analyze_broadcast(
            operands,
            operation=args.operation,
            memory_limit_mb=args.memory_limit_mb,
        )
    except BroadcastingError as error:
        parser.exit(2, f"broadcast-contract: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
