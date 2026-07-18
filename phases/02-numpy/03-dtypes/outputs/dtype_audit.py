from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from numbers import Integral, Real
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
    """Raised when a dtype contract cannot be evaluated."""


def manual_integer_bounds(bits: int, *, signed: bool) -> tuple[int, int]:
    if isinstance(bits, bool) or not isinstance(bits, Integral) or bits <= 0:
        raise DtypeAuditError("integer bit width must be a positive integer")
    if signed:
        return (-(2 ** (int(bits) - 1)), 2 ** (int(bits) - 1) - 1)
    return (0, 2 ** int(bits) - 1)


def smallest_integer_dtype(minimum: int, maximum: int) -> str | None:
    if minimum > maximum:
        raise DtypeAuditError("minimum cannot exceed maximum")
    preferred_kind = "u" if minimum >= 0 else "i"
    candidates = sorted(
        INTEGER_DTYPES,
        key=lambda dtype: (dtype.itemsize, dtype.kind != preferred_kind),
    )
    for dtype in candidates:
        info = np.iinfo(dtype)
        if minimum >= info.min and maximum <= info.max:
            return dtype.name
    return None


def validate_shape(shape: Sequence[int]) -> tuple[int, ...]:
    if isinstance(shape, (str, bytes)):
        raise DtypeAuditError("planned shape must be a sequence of integers")
    raw_shape = tuple(shape)
    if any(isinstance(length, bool) or not isinstance(length, Integral) for length in raw_shape):
        raise DtypeAuditError("planned shape must contain integers")
    result = tuple(int(length) for length in raw_shape)
    if any(length < 0 for length in result):
        raise DtypeAuditError("planned shape cannot contain negative lengths")
    return result


def replace_missing(value: object) -> object:
    if value is None:
        return np.nan
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [replace_missing(item) for item in value]
    return value


def parse_json(raw: str, *, name: str = "values") -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise DtypeAuditError(
            f"{name} must be valid JSON at line {error.lineno}, column {error.colno}"
        ) from error


def dtype_limits(dtype: np.dtype[Any]) -> dict[str, Any]:
    if np.issubdtype(dtype, np.integer):
        info = np.iinfo(dtype)
        manual_min, manual_max = manual_integer_bounds(
            info.bits,
            signed=np.issubdtype(dtype, np.signedinteger),
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
            "eps": float(info.eps),
        }
    raise DtypeAuditError(f"expected an integer or floating dtype, got {dtype}")


def _is_integral_number(value: Real) -> bool:
    return float(value).is_integer()


def _range_fits_dtype(minimum: Real, maximum: Real, dtype: np.dtype[Any]) -> bool:
    limits = dtype_limits(dtype)
    return minimum >= limits["min"] and maximum <= limits["max"]


def _round_trip_error(values: np.ndarray, target: np.dtype[Any]) -> float | None:
    if not values.size:
        return None
    if np.issubdtype(target, np.integer):
        return 0.0
    original = values.astype(np.longdouble)
    with np.errstate(over="ignore", invalid="ignore"):
        restored = values.astype(target).astype(np.longdouble)
    errors = np.abs(restored - original)
    return float(errors.max())


def _check(name: str, passed: bool, detail: str) -> dict[str, str | bool]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def audit_values(
    values: object,
    *,
    target_dtype: str | None = None,
    expected_min: Real | None = None,
    expected_max: Real | None = None,
    allow_missing: bool = False,
    max_abs_error: float | None = None,
    planned_shape: Sequence[int] | None = None,
) -> dict[str, Any]:
    if (expected_min is None) != (expected_max is None):
        raise DtypeAuditError("expected_min and expected_max must be provided together")
    if expected_min is not None:
        if (
            isinstance(expected_min, bool)
            or isinstance(expected_max, bool)
            or not isinstance(expected_min, Real)
            or not isinstance(expected_max, Real)
        ):
            raise DtypeAuditError("expected bounds must be numeric")
        if not math.isfinite(float(expected_min)) or not math.isfinite(float(expected_max)):
            raise DtypeAuditError("expected bounds must be finite")
        if expected_min > expected_max:
            raise DtypeAuditError("expected_min cannot exceed expected_max")
    if max_abs_error is not None and (
        not math.isfinite(max_abs_error) or max_abs_error < 0
    ):
        raise DtypeAuditError("max_abs_error must be finite and non-negative")

    normalized = replace_missing(values)
    try:
        array = np.asarray(normalized)
    except (TypeError, ValueError) as error:
        raise DtypeAuditError(f"cannot create a rectangular array: {error}") from error
    if array.dtype.kind not in "iuf":
        raise DtypeAuditError(f"expected numeric input, got dtype {array.dtype}")

    if array.dtype.kind == "f":
        missing_mask = np.isnan(array)
        infinite_mask = np.isinf(array)
        finite = array[np.isfinite(array)]
    else:
        missing_mask = np.zeros(array.shape, dtype=bool)
        infinite_mask = np.zeros(array.shape, dtype=bool)
        finite = array.reshape(-1)

    missing_count = int(missing_mask.sum())
    infinite_count = int(infinite_mask.sum())
    finite_min = finite.min().item() if finite.size else None
    finite_max = finite.max().item() if finite.size else None
    shape_for_planning = array.shape if planned_shape is None else validate_shape(planned_shape)
    planned_size = math.prod(shape_for_planning)

    recommendation_min = expected_min if expected_min is not None else finite_min
    recommendation_max = expected_max if expected_max is not None else finite_max
    integer_recommendation = None
    if (
        recommendation_min is not None
        and recommendation_max is not None
        and _is_integral_number(recommendation_min)
        and _is_integral_number(recommendation_max)
    ):
        integer_recommendation = smallest_integer_dtype(
            int(recommendation_min),
            int(recommendation_max),
        )

    checks = [
        _check(
            "missing_policy",
            allow_missing or missing_count == 0,
            (
                f"found {missing_count} missing values"
                if missing_count
                else "no missing values observed"
            ),
        ),
        _check(
            "finite_values",
            infinite_count == 0,
            (
                f"found {infinite_count} infinite values"
                if infinite_count
                else "no infinite values observed"
            ),
        ),
    ]
    warnings: list[str] = []
    if expected_min is None:
        warnings.append(
            "expected bounds are missing; an observed-value recommendation "
            "is not a production contract"
        )

    target_report = None
    if target_dtype is None:
        warnings.append("target dtype is missing; no conversion can be approved")
    else:
        try:
            target = np.dtype(target_dtype)
        except TypeError as error:
            raise DtypeAuditError(f"unknown target dtype {target_dtype!r}") from error
        if target.kind not in "iuf":
            raise DtypeAuditError(f"target dtype must be numeric, got {target}")

        target_is_integer = np.issubdtype(target, np.integer)
        observed_fits = (
            True
            if finite_min is None
            else _range_fits_dtype(finite_min, finite_max, target)
        )
        expected_fits = (
            True
            if expected_min is None
            else _range_fits_dtype(expected_min, expected_max, target)
        )
        observed_integral = bool(
            not finite.size or np.all(np.equal(finite, np.trunc(finite)))
        )
        expected_integral = bool(
            expected_min is None
            or (
                _is_integral_number(expected_min)
                and _is_integral_number(expected_max)
            )
        )
        target_supports_missing = missing_count == 0 or not target_is_integer

        checks.extend(
            [
                _check(
                    "observed_range_fits_target",
                    observed_fits,
                    (
                        "finite observed values fit the target range"
                        if observed_fits
                        else f"observed range {finite_min}..{finite_max} exceeds {target}"
                    ),
                ),
                _check(
                    "expected_range_fits_target",
                    expected_fits,
                    (
                        "expected bounds fit the target range"
                        if expected_fits
                        else f"expected range {expected_min}..{expected_max} exceeds {target}"
                    ),
                ),
                _check(
                    "integer_target_preserves_fractional_values",
                    not target_is_integer or (observed_integral and expected_integral),
                    (
                        "integer target is compatible with integral values"
                        if target_is_integer and observed_integral and expected_integral
                        else (
                            "target is floating"
                            if not target_is_integer
                            else "integer target would discard a fractional part"
                        )
                    ),
                ),
                _check(
                    "target_supports_missing_policy",
                    target_supports_missing,
                    (
                        "target can represent the observed missing-value policy"
                        if target_supports_missing
                        else f"{target} cannot represent NaN"
                    ),
                ),
            ]
        )

        can_measure_error = (
            observed_fits
            and expected_fits
            and (not target_is_integer or (observed_integral and expected_integral))
        )
        round_trip_error = _round_trip_error(finite, target) if can_measure_error else None
        if max_abs_error is not None:
            error_passed = round_trip_error is not None and round_trip_error <= max_abs_error
            checks.append(
                _check(
                    "round_trip_error_within_budget",
                    error_passed,
                    (
                        f"max absolute round-trip error {round_trip_error} <= {max_abs_error}"
                        if error_passed
                        else (
                            f"max absolute round-trip error {round_trip_error} "
                            f"exceeds {max_abs_error}"
                        )
                    ),
                )
            )
        elif np.issubdtype(target, np.floating) and target.itemsize < array.dtype.itemsize:
            warnings.append(
                "floating dtype is narrowed without max_abs_error; precision loss is not approved"
            )

        target_report = {
            "dtype": target.name,
            "itemsize_bytes": int(target.itemsize),
            "projected_nbytes": int(planned_size * target.itemsize),
            "projected_memory_change_bytes": int(
                planned_size * target.itemsize - planned_size * array.itemsize
            ),
            "limits": dtype_limits(target),
            "numpy_type_level_safe_cast": bool(
                np.can_cast(array.dtype, target, casting="safe")
            ),
            "round_trip_max_abs_error": round_trip_error,
        }

    failed_checks = [check["name"] for check in checks if not check["passed"]]
    status = "rejected" if failed_checks else ("warning" if warnings else "approved")

    return {
        "status": status,
        "source": {
            "shape": list(array.shape),
            "size": int(array.size),
            "dtype": array.dtype.name,
            "itemsize_bytes": int(array.itemsize),
            "nbytes": int(array.nbytes),
            "missing_count": missing_count,
            "infinite_count": infinite_count,
            "finite_min": finite_min,
            "finite_max": finite_max,
        },
        "contract": {
            "expected_min": expected_min,
            "expected_max": expected_max,
            "allow_missing": allow_missing,
            "max_abs_error": max_abs_error,
        },
        "planning": {
            "shape": list(shape_for_planning),
            "size": int(planned_size),
            "source_dtype_projected_nbytes": int(planned_size * array.itemsize),
        },
        "recommendation": {
            "basis": "expected_contract" if expected_min is not None else "observed_values",
            "smallest_integer_dtype": integer_recommendation,
            "production_ready": expected_min is not None,
        },
        "target": target_report,
        "checks": checks,
        "failed_checks": failed_checks,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit a NumPy dtype against range, missing-value, precision, "
            "and memory contracts"
        )
    )
    parser.add_argument("--values", default="[0, 12, 200]", help="Numeric JSON sample")
    parser.add_argument("--target-dtype", help="Candidate NumPy dtype")
    parser.add_argument("--expected-min", type=float)
    parser.add_argument("--expected-max", type=float)
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--max-abs-error", type=float)
    parser.add_argument("--planned-shape", help="JSON shape used only for memory planning")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = audit_values(
            parse_json(args.values),
            target_dtype=args.target_dtype,
            expected_min=args.expected_min,
            expected_max=args.expected_max,
            allow_missing=args.allow_missing,
            max_abs_error=args.max_abs_error,
            planned_shape=(
                parse_json(args.planned_shape, name="planned shape")
                if args.planned_shape
                else None
            ),
        )
    except DtypeAuditError as error:
        parser.exit(2, f"dtype-audit: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 1 if report["status"] == "rejected" else 0


if __name__ == "__main__":
    raise SystemExit(main())
