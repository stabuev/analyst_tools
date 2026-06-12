from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


class NumericalQualityError(ValueError):
    """Raised when a numerical result violates an explicit quality contract."""


def tolerance_report(
    actual: object,
    expected: object,
    *,
    rtol: float,
    atol: float,
    equal_nan: bool = False,
) -> dict[str, Any]:
    if rtol < 0 or atol < 0:
        raise NumericalQualityError("rtol and atol must be non-negative")
    actual_array = np.asarray(actual)
    expected_array = np.asarray(expected)
    if actual_array.shape != expected_array.shape:
        raise NumericalQualityError(
            f"shape mismatch: actual {actual_array.shape}, expected {expected_array.shape}"
        )
    if actual_array.dtype.kind not in "iuf" or expected_array.dtype.kind not in "iuf":
        raise NumericalQualityError("actual and expected must be numeric")

    close = np.isclose(
        actual_array,
        expected_array,
        rtol=rtol,
        atol=atol,
        equal_nan=equal_nan,
    )
    absolute_error = np.abs(actual_array - expected_array)
    allowed_error = atol + rtol * np.abs(expected_array)
    finite_errors = absolute_error[np.isfinite(absolute_error)]
    finite_allowed = allowed_error[np.isfinite(allowed_error)]
    return {
        "shape": list(actual_array.shape),
        "rtol": rtol,
        "atol": atol,
        "equal_nan": equal_nan,
        "all_close": bool(np.all(close)),
        "mismatch_count": int(close.size - np.count_nonzero(close)),
        "max_absolute_error": (float(finite_errors.max()) if finite_errors.size else None),
        "max_allowed_error": (float(finite_allowed.max()) if finite_allowed.size else None),
        "close_mask": close.tolist(),
    }


def assert_numerically_close(
    actual: object,
    expected: object,
    *,
    rtol: float,
    atol: float,
    equal_nan: bool = False,
) -> None:
    report = tolerance_report(
        actual,
        expected,
        rtol=rtol,
        atol=atol,
        equal_nan=equal_nan,
    )
    if not report["all_close"]:
        raise NumericalQualityError(
            f"{report['mismatch_count']} values exceed rtol={rtol}, atol={atol}; "
            f"max absolute error={report['max_absolute_error']}"
        )


def safe_divide(
    numerator: object,
    denominator: object,
    *,
    fill_value: float | None = None,
) -> np.ndarray:
    left, right = np.broadcast_arrays(
        np.asarray(numerator, dtype=float),
        np.asarray(denominator, dtype=float),
    )
    valid = np.isfinite(left) & np.isfinite(right) & (right != 0)
    if fill_value is None and not np.all(valid):
        raise NumericalQualityError(
            f"division has {valid.size - np.count_nonzero(valid)} invalid positions"
        )

    result = np.full(left.shape, fill_value if fill_value is not None else np.nan)
    with np.errstate(divide="raise", invalid="raise", over="raise"):
        try:
            np.divide(left, right, out=result, where=valid)
        except FloatingPointError as error:
            raise NumericalQualityError(f"floating-point division failed: {error}") from error
    return result


def checked_integer_add(left: object, right: object, *, dtype: str) -> np.ndarray:
    requested = np.dtype(dtype)
    if not np.issubdtype(requested, np.integer):
        raise NumericalQualityError("checked_integer_add requires an integer dtype")
    left_array, right_array = np.broadcast_arrays(
        np.asarray(left, dtype=object),
        np.asarray(right, dtype=object),
    )
    info = np.iinfo(requested)
    result_object = left_array + right_array
    flat = result_object.ravel()
    for value in flat:
        if not isinstance(value, (int, np.integer)):
            raise NumericalQualityError("integer addition received a non-integer value")
        if value < info.min or value > info.max:
            raise NumericalQualityError(
                f"result {value} is outside {requested.name} range [{info.min}, {info.max}]"
            )
    return np.asarray(result_object.tolist(), dtype=requested)


def summation_report(values: object) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float32)
    if array.size == 0 or not np.isfinite(array).all():
        raise NumericalQualityError("summation values must be non-empty and finite")
    python_reference = math.fsum(float(value) for value in array.ravel())
    float32_sum = float(np.sum(array, dtype=np.float32))
    float64_sum = float(np.sum(array, dtype=np.float64))
    return {
        "python_fsum": python_reference,
        "float32_sum": float32_sum,
        "float64_accumulator_sum": float64_sum,
        "float32_absolute_error": abs(float32_sum - python_reference),
        "float64_absolute_error": abs(float64_sum - python_reference),
    }


def json_safe_floats(values: np.ndarray) -> list[float | None]:
    return [float(value) if np.isfinite(value) else None for value in values.ravel()]


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
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = {
            "comparison": tolerance_report(
                parse_json(args.actual, name="actual"),
                parse_json(args.expected, name="expected"),
                rtol=args.rtol,
                atol=args.atol,
                equal_nan=args.equal_nan,
            ),
            "division_demo": safe_divide(
                [10.0, 20.0, 30.0],
                [2.0, 0.0, 5.0],
                fill_value=np.nan,
            ),
            "summation_demo": summation_report([1e8, 1.0, -1e8]),
        }
        report["division_demo"] = json_safe_floats(report["division_demo"])
    except (NumericalQualityError, ValueError) as error:
        parser.exit(2, f"numerical-quality: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
