from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

INTEGER_DTYPES = (
    np.dtype("uint8"),
    np.dtype("int8"),
    np.dtype("uint16"),
    np.dtype("int16"),
    np.dtype("uint32"),
    np.dtype("int32"),
    np.dtype("uint64"),
    np.dtype("int64"),
)


class DtypeAuditError(ValueError):
    """Raised when values violate the requested dtype contract."""


def manual_integer_bounds(bits: int, *, signed: bool) -> tuple[int, int]:
    if bits <= 0:
        raise DtypeAuditError("integer bit width must be positive")
    if signed:
        return (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1)
    return (0, 2**bits - 1)


def smallest_integer_dtype(minimum: int, maximum: int) -> str | None:
    if minimum > maximum:
        raise DtypeAuditError("minimum cannot exceed maximum")
    candidates = sorted(INTEGER_DTYPES, key=lambda dtype: (dtype.itemsize, dtype.kind))
    for dtype in candidates:
        info = np.iinfo(dtype)
        if minimum >= info.min and maximum <= info.max:
            return dtype.name
    return None


def replace_missing(value: object) -> object:
    if value is None:
        return np.nan
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [replace_missing(item) for item in value]
    return value


def parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise DtypeAuditError(
            f"invalid JSON at line {error.lineno}, column {error.colno}"
        ) from error


def dtype_limits(dtype: np.dtype[Any]) -> dict[str, Any]:
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        manual_min, manual_max = manual_integer_bounds(
            info.bits, signed=np.issubdtype(dtype, np.signedinteger)
        )
        return {
            "kind": "integer",
            "bits": info.bits,
            "min": int(info.min),
            "max": int(info.max),
            "manual_bounds_match": (manual_min, manual_max) == (int(info.min), int(info.max)),
        }
    if np.issubdtype(dtype, np.floating):
        info = np.finfo(dtype)
        return {
            "kind": "floating",
            "bits": info.bits,
            "min": float(info.min),
            "max": float(info.max),
            "smallest_normal": float(info.smallest_normal),
            "eps": float(info.eps),
        }
    return {"kind": dtype.kind}


def audit_values(values: object, dtype: str | None = None) -> dict[str, Any]:
    normalized = replace_missing(values)
    try:
        array = np.asarray(normalized, dtype=dtype)
    except (OverflowError, TypeError, ValueError) as error:
        raise DtypeAuditError(f"cannot create dtype {dtype or 'inferred'}: {error}") from error

    if array.dtype.kind not in "iuf":
        raise DtypeAuditError(f"expected numeric dtype, got {array.dtype}")

    if array.dtype.kind == "f":
        missing_count = int(np.isnan(array).sum())
        finite = array[np.isfinite(array)]
    else:
        missing_count = 0
        finite = array

    finite_min = finite.min().item() if finite.size else None
    finite_max = finite.max().item() if finite.size else None
    integer_recommendation = None
    if finite.size and np.all(np.equal(finite, np.floor(finite))):
        integer_recommendation = smallest_integer_dtype(
            int(finite_min),
            int(finite_max),
        )

    return {
        "shape": list(array.shape),
        "size": int(array.size),
        "dtype": array.dtype.name,
        "itemsize_bytes": int(array.itemsize),
        "nbytes": int(array.nbytes),
        "missing_count": missing_count,
        "finite_min": finite_min,
        "finite_max": finite_max,
        "limits": dtype_limits(array.dtype),
        "smallest_integer_dtype": integer_recommendation,
        "integer_recommendation_usable": integer_recommendation is not None and missing_count == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a NumPy dtype contract")
    parser.add_argument("--values", default="[0, 12, 255]", help="Numeric JSON values")
    parser.add_argument("--dtype", help="Optional requested NumPy dtype")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = audit_values(parse_json(args.values), args.dtype)
    except DtypeAuditError as error:
        parser.exit(2, f"dtype-audit: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
