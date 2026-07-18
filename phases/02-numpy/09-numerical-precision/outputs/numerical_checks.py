from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_MAX_MISMATCHES = 5
MAX_MISMATCHES_LIMIT = 100


class NumericalQualityError(ValueError):
    """Raised when a numerical result violates an explicit quality contract."""


def _validate_tolerance(name: str, value: object) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise NumericalQualityError(f"{name} must be a real number")
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or numeric_value < 0.0:
        raise NumericalQualityError(f"{name} must be finite and non-negative")
    return numeric_value


def _validate_max_mismatches(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise NumericalQualityError("max_mismatches must be an integer")
    if value <= 0 or value > MAX_MISMATCHES_LIMIT:
        raise NumericalQualityError(f"max_mismatches must be between 1 and {MAX_MISMATCHES_LIMIT}")


def _as_real_numeric_array(values: object, *, name: str) -> np.ndarray:
    array = np.asarray(values)
    if array.size == 0:
        raise NumericalQualityError(f"{name} must not be empty")
    if array.dtype.kind not in "iuf":
        raise NumericalQualityError(f"{name} must contain real numeric values")
    return array


def _json_scalar(value: object) -> int | float | str:
    scalar = np.asarray(value).item()
    if isinstance(scalar, (int, np.integer)):
        return int(scalar)
    numeric_value = float(scalar)
    if math.isnan(numeric_value):
        return "nan"
    if math.isinf(numeric_value):
        return "inf" if numeric_value > 0 else "-inf"
    return numeric_value


def tolerance_report(
    actual: object,
    expected: object,
    *,
    rtol: float,
    atol: float,
    equal_nan: bool = False,
    require_same_dtype: bool = False,
    max_mismatches: int = DEFAULT_MAX_MISMATCHES,
) -> dict[str, Any]:
    """Compare equally shaped real arrays under an explicit numerical contract."""

    checked_rtol = _validate_tolerance("rtol", rtol)
    checked_atol = _validate_tolerance("atol", atol)
    _validate_max_mismatches(max_mismatches)
    if not isinstance(equal_nan, (bool, np.bool_)):
        raise NumericalQualityError("equal_nan must be boolean")
    if not isinstance(require_same_dtype, (bool, np.bool_)):
        raise NumericalQualityError("require_same_dtype must be boolean")

    actual_array = _as_real_numeric_array(actual, name="actual")
    expected_array = _as_real_numeric_array(expected, name="expected")
    if actual_array.shape != expected_array.shape:
        raise NumericalQualityError(
            f"shape mismatch: actual {actual_array.shape}, expected {expected_array.shape}"
        )

    actual_float = actual_array.astype(np.float64, copy=False)
    expected_float = expected_array.astype(np.float64, copy=False)
    actual_nan = np.isnan(actual_float)
    expected_nan = np.isnan(expected_float)
    actual_inf = np.isinf(actual_float)
    expected_inf = np.isinf(expected_float)
    infinity_mask = actual_inf | expected_inf
    finite_pair = np.isfinite(actual_float) & np.isfinite(expected_float)

    integer_pair = np.issubdtype(actual_array.dtype, np.integer) and np.issubdtype(
        expected_array.dtype,
        np.integer,
    )
    with np.errstate(invalid="ignore", over="ignore"):
        allowed_error = checked_atol + checked_rtol * np.abs(expected_float)
        if integer_pair:
            # np.isclose converts large integers to floating point and can make adjacent
            # int64 values above 2**53 look equal. Python integers preserve the exact
            # difference while still allowing an explicitly requested tolerance.
            exact_difference = np.abs(actual_array.astype(object) - expected_array.astype(object))
            absolute_error = np.asarray(exact_difference, dtype=np.float64)
            close = np.fromiter(
                (
                    difference <= allowed
                    for difference, allowed in zip(
                        exact_difference.flat,
                        allowed_error.flat,
                        strict=True,
                    )
                ),
                dtype=bool,
                count=actual_array.size,
            ).reshape(actual_array.shape)
        else:
            close = np.isclose(
                actual_array,
                expected_array,
                rtol=checked_rtol,
                atol=checked_atol,
                equal_nan=bool(equal_nan),
            )
            absolute_error = np.full(actual_array.shape, np.nan, dtype=np.float64)
            difference = np.empty(actual_array.shape, dtype=np.float64)
            np.subtract(
                actual_float,
                expected_float,
                out=difference,
                where=finite_pair,
            )
            np.abs(difference, out=absolute_error, where=finite_pair)

    # A matching infinity is still a failed finite-result contract. Matching NaN values
    # may pass only after the caller explicitly enables equal_nan.
    close = np.asarray(close, dtype=bool)
    close[infinity_mask] = False

    mismatch_mask = ~close
    mismatch_count = int(np.count_nonzero(mismatch_mask))
    mismatch_indices = np.argwhere(mismatch_mask)
    mismatch_examples: list[dict[str, Any]] = []
    for raw_index in mismatch_indices[:max_mismatches]:
        index = tuple(int(component) for component in raw_index)
        actual_value = actual_array[index]
        expected_value = expected_array[index]
        if np.isinf(actual_float[index]) or np.isinf(expected_float[index]):
            reason = "infinity_not_allowed"
        elif np.isnan(actual_float[index]) or np.isnan(expected_float[index]):
            reason = "nan_positions_do_not_match_or_equal_nan_is_false"
        else:
            reason = "outside_tolerance"
        mismatch_examples.append(
            {
                "index": list(index),
                "actual": _json_scalar(actual_value),
                "expected": _json_scalar(expected_value),
                "absolute_error": (
                    float(absolute_error[index]) if np.isfinite(absolute_error[index]) else None
                ),
                "allowed_error": (
                    float(allowed_error[index]) if np.isfinite(allowed_error[index]) else None
                ),
                "reason": reason,
            }
        )

    finite_absolute_errors = absolute_error[finite_pair]
    finite_allowed_errors = allowed_error[finite_pair]
    dtype_matches = actual_array.dtype == expected_array.dtype
    value_comparison_passed = mismatch_count == 0
    dtype_contract_passed = bool(dtype_matches or not require_same_dtype)
    passed = value_comparison_passed and dtype_contract_passed

    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "shape": list(actual_array.shape),
        "element_count": int(actual_array.size),
        "actual_dtype": str(actual_array.dtype),
        "expected_dtype": str(expected_array.dtype),
        "dtype_matches": bool(dtype_matches),
        "require_same_dtype": bool(require_same_dtype),
        "dtype_contract_passed": dtype_contract_passed,
        "comparison": {
            "formula": "abs(actual - expected) <= atol + rtol * abs(expected)",
            "reference": "expected",
            "rtol": checked_rtol,
            "atol": checked_atol,
            "equal_nan": bool(equal_nan),
            "infinity_policy": "always fail",
        },
        "value_comparison_passed": value_comparison_passed,
        "mismatch_count": mismatch_count,
        "mismatch_examples": mismatch_examples,
        "mismatch_examples_truncated": mismatch_count > len(mismatch_examples),
        "max_absolute_error_on_finite_pairs": (
            float(finite_absolute_errors.max()) if finite_absolute_errors.size else None
        ),
        "max_allowed_error_on_finite_pairs": (
            float(finite_allowed_errors.max()) if finite_allowed_errors.size else None
        ),
        "non_finite": {
            "actual_nan_count": int(np.count_nonzero(actual_nan)),
            "expected_nan_count": int(np.count_nonzero(expected_nan)),
            "actual_infinity_count": int(np.count_nonzero(actual_inf)),
            "expected_infinity_count": int(np.count_nonzero(expected_inf)),
        },
    }


def assert_numerically_close(
    actual: object,
    expected: object,
    *,
    rtol: float,
    atol: float,
    equal_nan: bool = False,
    require_same_dtype: bool = False,
) -> None:
    report = tolerance_report(
        actual,
        expected,
        rtol=rtol,
        atol=atol,
        equal_nan=equal_nan,
        require_same_dtype=require_same_dtype,
    )
    if report["passed"]:
        return

    reasons: list[str] = []
    if not report["dtype_contract_passed"]:
        reasons.append(
            f"dtype mismatch: actual {report['actual_dtype']}, expected {report['expected_dtype']}"
        )
    if report["mismatch_examples"]:
        first = report["mismatch_examples"][0]
        reasons.append(
            f"first mismatch at index {first['index']}: "
            f"actual={first['actual']}, expected={first['expected']}, "
            f"reason={first['reason']}"
        )
    raise NumericalQualityError(
        f"numerical contract failed with {report['mismatch_count']} value mismatches; "
        + "; ".join(reasons)
    )


def safe_divide(
    numerator: object,
    denominator: object,
    *,
    fill_value: float | None = None,
) -> np.ndarray:
    """Divide real arrays under an explicit invalid-position policy."""

    left = _as_real_numeric_array(numerator, name="numerator").astype(
        np.float64,
        copy=False,
    )
    right = _as_real_numeric_array(denominator, name="denominator").astype(
        np.float64,
        copy=False,
    )
    left, right = np.broadcast_arrays(left, right)

    checked_fill_value: float | None = None
    if fill_value is not None:
        checked_fill_value = _validate_fill_value(fill_value)

    valid = np.isfinite(left) & np.isfinite(right) & (right != 0.0)
    invalid_count = int(valid.size - np.count_nonzero(valid))
    if fill_value is None and invalid_count:
        raise NumericalQualityError(
            f"division has {invalid_count} invalid positions; choose error or fill policy"
        )

    result = np.full(
        left.shape,
        checked_fill_value if fill_value is not None else np.nan,
        dtype=np.float64,
    )
    with np.errstate(divide="raise", invalid="raise", over="raise", under="raise"):
        try:
            np.divide(left, right, out=result, where=valid)
        except FloatingPointError as error:
            raise NumericalQualityError(f"floating-point division failed: {error}") from error
    return result


def _validate_fill_value(value: object) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise NumericalQualityError("fill_value must be a real scalar")
    numeric_value = float(value)
    if math.isinf(numeric_value):
        raise NumericalQualityError("fill_value must be finite or NaN, not infinity")
    return numeric_value


def _as_integer_object_array(values: object, *, name: str) -> np.ndarray:
    array = np.asarray(values, dtype=object)
    if array.size == 0:
        raise NumericalQualityError(f"{name} must not be empty")
    for value in array.ravel():
        if isinstance(value, (bool, np.bool_)) or not isinstance(
            value,
            (int, np.integer),
        ):
            raise NumericalQualityError(f"{name} must contain integer values")
    return array


def checked_integer_add(left: object, right: object, *, dtype: str) -> np.ndarray:
    """Add with Python integers, then verify the requested fixed-width range."""

    try:
        requested = np.dtype(dtype)
    except TypeError as error:
        raise NumericalQualityError(f"unknown dtype: {dtype}") from error
    if not np.issubdtype(requested, np.integer):
        raise NumericalQualityError("checked_integer_add requires an integer dtype")

    left_array = _as_integer_object_array(left, name="left")
    right_array = _as_integer_object_array(right, name="right")
    left_array, right_array = np.broadcast_arrays(left_array, right_array)
    result_object = left_array + right_array
    info = np.iinfo(requested)
    for value in result_object.ravel():
        if value < info.min or value > info.max:
            raise NumericalQualityError(
                f"result {value} is outside {requested.name} range [{info.min}, {info.max}]"
            )
    return np.asarray(result_object.tolist(), dtype=requested)


def floating_range_report(dtype: str) -> dict[str, float | int | str]:
    try:
        requested = np.dtype(dtype)
    except TypeError as error:
        raise NumericalQualityError(f"unknown dtype: {dtype}") from error
    if requested.name not in {"float16", "float32", "float64"}:
        raise NumericalQualityError("floating_range_report supports float16, float32 and float64")
    info = np.finfo(requested)
    return {
        "dtype": requested.name,
        "bits": info.bits,
        "eps_near_one": float(info.eps),
        "max_finite": float(info.max),
        "smallest_positive_normal": float(info.tiny),
        "smallest_positive_subnormal": float(info.smallest_subnormal),
    }


def summation_report(
    values: object,
    *,
    storage_dtype: str = "float32",
    accumulator_dtype: str = "float64",
) -> dict[str, Any]:
    raw = _as_real_numeric_array(values, name="summation values")
    try:
        storage = np.dtype(storage_dtype)
        accumulator = np.dtype(accumulator_dtype)
    except TypeError as error:
        raise NumericalQualityError("unknown summation dtype") from error
    if not np.issubdtype(storage, np.floating) or not np.issubdtype(
        accumulator,
        np.floating,
    ):
        raise NumericalQualityError("summation dtypes must be floating")
    if accumulator.itemsize < storage.itemsize:
        raise NumericalQualityError("accumulator dtype must be at least as wide as storage dtype")

    with np.errstate(over="ignore", invalid="ignore"):
        stored = raw.astype(storage)
    if not np.isfinite(stored).all():
        raise NumericalQualityError("summation values must remain finite after storage conversion")

    reference = math.fsum(float(value) for value in stored.ravel())
    storage_sum = float(np.sum(stored, dtype=storage))
    accumulator_sum = float(np.sum(stored, dtype=accumulator))
    return {
        "input_shape": list(stored.shape),
        "element_count": int(stored.size),
        "storage_dtype": storage.name,
        "accumulator_dtype": accumulator.name,
        "python_fsum_reference_over_stored_values": reference,
        "storage_accumulator_sum": storage_sum,
        "chosen_accumulator_sum": accumulator_sum,
        "storage_accumulator_absolute_error": abs(storage_sum - reference),
        "chosen_accumulator_absolute_error": abs(accumulator_sum - reference),
        "reference_boundary": (
            "math.fsum is applied after conversion to storage_dtype; information "
            "lost during storage conversion cannot be restored"
        ),
    }


def parse_json(raw: str, *, name: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise NumericalQualityError(f"{name} must be valid JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a NumPy numerical quality gate")
    parser.add_argument("--actual", default="[0.30000000000000004, 10.0]")
    parser.add_argument("--expected", default="[0.3, 10.0]")
    parser.add_argument("--rtol", type=float, default=1e-9)
    parser.add_argument("--atol", type=float, default=1e-12)
    parser.add_argument("--equal-nan", action="store_true")
    parser.add_argument("--require-same-dtype", action="store_true")
    parser.add_argument("--max-mismatches", type=int, default=DEFAULT_MAX_MISMATCHES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        comparison = tolerance_report(
            parse_json(args.actual, name="actual"),
            parse_json(args.expected, name="expected"),
            rtol=args.rtol,
            atol=args.atol,
            equal_nan=args.equal_nan,
            require_same_dtype=args.require_same_dtype,
            max_mismatches=args.max_mismatches,
        )
        report = {
            "contract_version": 1,
            "gate": "numpy numerical comparison",
            "comparison": comparison,
            "decision": {
                "status": comparison["status"],
                "exit_code": 0 if comparison["passed"] else 1,
            },
        }
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
    except (NumericalQualityError, OSError) as error:
        parser.exit(2, f"numerical-quality: {error}\n")
    return 0 if comparison["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
