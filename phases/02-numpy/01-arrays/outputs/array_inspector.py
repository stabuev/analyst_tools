from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from numbers import Real
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_VALUES = "[[12, 15, 9], [10, 11, 14]]"
CREATION_RECIPES = (
    {
        "goal": "Convert a Python sequence",
        "code": "np.array([12, 15, 9])",
    },
    {
        "goal": "Fill a known shape with zeros",
        "code": "np.zeros((2, 3))",
    },
    {
        "goal": "Fill a known shape with ones",
        "code": "np.ones((2, 3))",
    },
    {
        "goal": "Create an integer progression",
        "code": "np.arange(0, 10, 2)",
    },
    {
        "goal": "Create a fixed number of interval points",
        "code": "np.linspace(0, 1, num=5)",
    },
)
LIST_COMPARISON = (
    {
        "property": "Element types",
        "python_list": "May be heterogeneous",
        "ndarray": "Represented by one dtype",
    },
    {
        "property": "Nested structure",
        "python_list": "May be ragged",
        "ndarray": "Uses one rectangular shape",
    },
    {
        "property": "Container size",
        "python_list": "Can grow in place",
        "ndarray": "Element count is fixed",
    },
    {
        "property": "Arithmetic",
        "python_list": "Operators often manage the container",
        "ndarray": "Operators act elementwise by default",
    },
)


class ArrayContractError(ValueError):
    """Raised when values cannot form the lesson's numeric array model."""


def is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def infer_shape(value: object, path: str = "values") -> tuple[int, ...]:
    """Infer a rectangular shape without using NumPy."""
    if is_sequence(value):
        items = list(value)
        if not items:
            return (0,)
        child_shapes = [infer_shape(item, f"{path}[{index}]") for index, item in enumerate(items)]
        expected = child_shapes[0]
        for index, shape in enumerate(child_shapes[1:], start=1):
            if shape != expected:
                raise ArrayContractError(
                    f"ragged nested sequence at {path}[{index}]: "
                    f"expected child shape {expected}, got {shape}"
                )
        return (len(items), *expected)

    if isinstance(value, Real) and not isinstance(value, bool):
        return ()

    raise ArrayContractError(f"{path} must be a real number or a nested sequence of real numbers")


def parse_json_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise ArrayContractError(
            f"invalid JSON at line {error.lineno}, column {error.colno}"
        ) from error


def inspect_values(values: object, dtype: str | None = None) -> dict[str, Any]:
    expected_shape = infer_shape(values)
    try:
        array = np.array(values, dtype=dtype)
    except (OverflowError, TypeError, ValueError) as error:
        raise ArrayContractError(f"NumPy could not create the requested array: {error}") from error

    actual_shape = tuple(int(length) for length in array.shape)
    if actual_shape != expected_shape:
        raise ArrayContractError(
            f"manual shape {expected_shape} disagrees with NumPy shape {actual_shape}"
        )

    return {
        "source_type": type(values).__name__,
        "array_type": type(array).__name__,
        "dtype_request": dtype,
        "ndim": int(array.ndim),
        "shape": list(actual_shape),
        "size": int(array.size),
        "dtype": str(array.dtype),
        "dtype_kind": array.dtype.kind,
        "values": array.tolist(),
        "invariants": {
            "rectangular": True,
            "homogeneous_dtype": True,
            "ndim_matches_shape": array.ndim == len(array.shape),
            "size_matches_shape": array.size == math.prod(array.shape),
        },
        "creation_recipes": list(CREATION_RECIPES),
        "list_comparison": list(LIST_COMPARISON),
    }


def format_shape(shape: Sequence[int]) -> str:
    if not shape:
        return "()"
    if len(shape) == 1:
        return f"({shape[0]},)"
    return f"({', '.join(str(length) for length in shape)})"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# NumPy array inspection",
        "",
        f"- Source type: `{report['source_type']}`",
        f"- Array type: `{report['array_type']}`",
        f"- `ndim`: `{report['ndim']}`",
        f"- `shape`: `{format_shape(report['shape'])}`",
        f"- `size`: `{report['size']}`",
        f"- `dtype`: `{report['dtype']}`",
        f"- Values: `{json.dumps(report['values'], ensure_ascii=False)}`",
        "",
        "## Verified invariants",
        "",
    ]
    for name, passed in report["invariants"].items():
        lines.append(f"- [{'x' if passed else ' '}] `{name}`")

    lines.extend(
        [
            "",
            "## Creation recipes",
            "",
            "| Goal | NumPy code |",
            "|---|---|",
        ]
    )
    for recipe in report["creation_recipes"]:
        lines.append(f"| {recipe['goal']} | `{recipe['code']}` |")

    lines.extend(
        [
            "",
            "## Python list and ndarray",
            "",
            "| Property | Python list | ndarray |",
            "|---|---|---|",
        ]
    )
    for row in report["list_comparison"]:
        lines.append(f"| {row['property']} | {row['python_list']} | {row['ndarray']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect numeric JSON values as a rectangular NumPy array"
    )
    parser.add_argument(
        "--values",
        default=DEFAULT_VALUES,
        help="JSON scalar or nested sequence of real numbers",
    )
    parser.add_argument("--dtype", help="Optional NumPy dtype, for example float32")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = inspect_values(parse_json_value(args.values), args.dtype)
    except ArrayContractError as error:
        parser.exit(2, f"array-inspector: {error}\n")

    text = (
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
