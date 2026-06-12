from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


class NumericFilterError(ValueError):
    """Raised when a numeric selection contract is invalid."""


def as_numeric_array(values: object) -> np.ndarray:
    array = np.asarray(values)
    if array.dtype.kind not in "iuf":
        raise NumericFilterError(f"expected numeric values, got dtype {array.dtype}")
    return array


def range_mask(
    values: object,
    *,
    lower: float | None = None,
    upper: float | None = None,
    inclusive: str = "both",
) -> np.ndarray:
    if lower is not None and upper is not None and lower > upper:
        raise NumericFilterError("lower bound cannot exceed upper bound")
    if inclusive not in {"both", "left", "right", "neither"}:
        raise NumericFilterError("inclusive must be both, left, right, or neither")

    array = as_numeric_array(values)
    mask = np.isfinite(array)
    if lower is not None:
        mask &= array >= lower if inclusive in {"both", "left"} else array > lower
    if upper is not None:
        mask &= array <= upper if inclusive in {"both", "right"} else array < upper
    return mask


def filter_observations(
    values: object,
    *,
    lower: float | None = None,
    upper: float | None = None,
    inclusive: str = "both",
) -> np.ndarray:
    array = as_numeric_array(values)
    mask = range_mask(
        array,
        lower=lower,
        upper=upper,
        inclusive=inclusive,
    )
    selected = array[mask]
    if np.shares_memory(array, selected):
        raise NumericFilterError("filtered result unexpectedly shares memory")
    return selected


def replace_where(
    values: np.ndarray,
    mask: np.ndarray,
    replacement: float,
    *,
    in_place: bool = False,
) -> np.ndarray:
    array = as_numeric_array(values)
    boolean_mask = np.asarray(mask, dtype=bool)
    if boolean_mask.shape != array.shape:
        raise NumericFilterError(
            f"mask shape {boolean_mask.shape} does not match values {array.shape}"
        )
    result = array if in_place else array.copy()
    result[boolean_mask] = replacement
    return result


def memory_report(values: object) -> dict[str, Any]:
    array = as_numeric_array(values)
    if array.ndim != 1:
        raise NumericFilterError("memory report expects a one-dimensional array")
    basic_slice = array[1:-1]
    advanced_selection = array[np.arange(array.size) % 2 == 0]
    return {
        "source_shape": list(array.shape),
        "basic_slice_shape": list(basic_slice.shape),
        "basic_slice_shares_memory": bool(np.shares_memory(array, basic_slice)),
        "advanced_shape": list(advanced_selection.shape),
        "advanced_shares_memory": bool(np.shares_memory(array, advanced_selection)),
    }


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise NumericFilterError("values must be valid JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter numeric NumPy observations")
    parser.add_argument("--values", default="[5, 12, 18, 27]")
    parser.add_argument("--lower", type=float)
    parser.add_argument("--upper", type=float)
    parser.add_argument(
        "--inclusive",
        choices=("both", "left", "right", "neither"),
        default="both",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        values = parse_json(args.values)
        mask = range_mask(
            values,
            lower=args.lower,
            upper=args.upper,
            inclusive=args.inclusive,
        )
        selected = filter_observations(
            values,
            lower=args.lower,
            upper=args.upper,
            inclusive=args.inclusive,
        )
        report = {
            "mask": mask.tolist(),
            "selected": selected.tolist(),
            "selected_count": int(selected.size),
            "shares_memory": False,
            "memory_demo": memory_report(values),
        }
    except NumericFilterError as error:
        parser.exit(2, f"numeric-filters: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
