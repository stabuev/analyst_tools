from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np

MAX_SIZE = 2_000_000
MIN_REPEAT = 3
MAX_REPEAT = 101
MAX_SEED = 2**64 - 1
ROW_RTOL = 1e-12
ROW_ATOL = 1e-12
TOTAL_RTOL = 1e-12
TOTAL_ATOL = 1e-8


class BenchmarkError(ValueError):
    """Raised when benchmark inputs or results violate the contract."""


def _validate_size(size: int) -> None:
    if isinstance(size, bool) or not isinstance(size, (int, np.integer)):
        raise BenchmarkError("size must be an integer")
    if size <= 0 or size > MAX_SIZE:
        raise BenchmarkError(f"size must be between 1 and {MAX_SIZE:,}")


def _validate_repeat(repeat: int) -> None:
    if isinstance(repeat, bool) or not isinstance(repeat, (int, np.integer)):
        raise BenchmarkError("repeat must be an integer")
    if repeat < MIN_REPEAT or repeat > MAX_REPEAT:
        raise BenchmarkError(f"repeat must be between {MIN_REPEAT} and {MAX_REPEAT}")


def _validate_seed(seed: int) -> None:
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise BenchmarkError("seed must be an integer")
    if seed < 0 or seed > MAX_SEED:
        raise BenchmarkError(f"seed must be between 0 and {MAX_SEED}")


def prepare_inputs(
    prices: Any,
    quantities: Any,
    discounts: Any,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate the line-item contract and return contiguous calculation arrays."""

    raw_prices = np.asarray(prices)
    raw_quantities = np.asarray(quantities)
    raw_discounts = np.asarray(discounts)
    arrays = {
        "prices": raw_prices,
        "quantities": raw_quantities,
        "discounts": raw_discounts,
    }

    for name, values in arrays.items():
        if values.ndim != 1:
            raise BenchmarkError(f"{name} must be one-dimensional")
        if np.issubdtype(values.dtype, np.bool_):
            raise BenchmarkError(f"{name} must not use boolean dtype")
        is_real_number = np.issubdtype(values.dtype, np.integer) or np.issubdtype(
            values.dtype, np.floating
        )
        if values.dtype == np.dtype("O") or not is_real_number:
            raise BenchmarkError(f"{name} must contain real numeric values")

    if not (raw_prices.shape == raw_quantities.shape == raw_discounts.shape):
        raise BenchmarkError("input arrays must have equal shapes")
    if raw_prices.size == 0:
        raise BenchmarkError("input arrays must not be empty")
    if not np.issubdtype(raw_quantities.dtype, np.integer):
        raise BenchmarkError("quantities must use an integer dtype")

    normalized_prices = np.ascontiguousarray(raw_prices, dtype=np.float64)
    normalized_quantities = np.ascontiguousarray(raw_quantities, dtype=np.int64)
    normalized_discounts = np.ascontiguousarray(raw_discounts, dtype=np.float64)

    if not np.all(np.isfinite(normalized_prices)):
        raise BenchmarkError("prices must contain only finite values")
    if not np.all(np.isfinite(normalized_discounts)):
        raise BenchmarkError("discounts must contain only finite values")
    if np.any(normalized_prices < 0.0):
        raise BenchmarkError("prices must be non-negative")
    if np.any(normalized_quantities < 0):
        raise BenchmarkError("quantities must be non-negative")
    if np.any((normalized_discounts < 0.0) | (normalized_discounts > 1.0)):
        raise BenchmarkError("discounts must be between 0 and 1")

    return normalized_prices, normalized_quantities, normalized_discounts


def python_line_revenue(
    prices: Sequence[float],
    quantities: Sequence[int],
    discounts: Sequence[float],
) -> list[float]:
    """Transparent per-line baseline for already validated Python sequences."""

    if not (len(prices) == len(quantities) == len(discounts)):
        raise BenchmarkError("input sequences must have equal lengths")
    return [
        price * quantity * (1.0 - discount)
        for price, quantity, discount in zip(
            prices,
            quantities,
            discounts,
            strict=True,
        )
    ]


def numpy_line_revenue(
    prices: np.ndarray,
    quantities: np.ndarray,
    discounts: np.ndarray,
) -> np.ndarray:
    """Vectorized per-line calculation for prepared one-dimensional arrays."""

    if not (prices.shape == quantities.shape == discounts.shape):
        raise BenchmarkError("input arrays must have equal shapes")
    if prices.ndim != 1:
        raise BenchmarkError("input arrays must be one-dimensional")
    return prices * quantities * (1.0 - discounts)


def python_net_revenue(
    prices: Sequence[float],
    quantities: Sequence[int],
    discounts: Sequence[float],
) -> float:
    """Loop and reduction used in the timed Python baseline."""

    if not (len(prices) == len(quantities) == len(discounts)):
        raise BenchmarkError("input sequences must have equal lengths")
    total = 0.0
    for price, quantity, discount in zip(
        prices,
        quantities,
        discounts,
        strict=True,
    ):
        total += price * quantity * (1.0 - discount)
    return total


def numpy_net_revenue(
    prices: np.ndarray,
    quantities: np.ndarray,
    discounts: np.ndarray,
) -> float:
    """Vectorized expression and reduction used in the timed NumPy branch."""

    line_revenue = numpy_line_revenue(prices, quantities, discounts)
    return float(np.sum(line_revenue, dtype=np.float64))


def generate_inputs(
    size: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create reproducible line-item arrays with the declared business domain."""

    _validate_size(size)
    _validate_seed(seed)
    rng = np.random.default_rng(seed)
    prices = rng.uniform(1.0, 500.0, size=size)
    quantities = rng.integers(1, 6, size=size, dtype=np.int64)
    discounts = rng.choice(np.array([0.0, 0.05, 0.1, 0.2]), size=size)
    return prices, quantities, discounts


def compare_results(
    price_list: Sequence[float],
    quantity_list: Sequence[int],
    discount_list: Sequence[float],
    prices: np.ndarray,
    quantities: np.ndarray,
    discounts: np.ndarray,
) -> dict[str, Any]:
    """Check the most detailed output before comparing aggregate totals."""

    loop_rows = np.asarray(
        python_line_revenue(price_list, quantity_list, discount_list),
        dtype=np.float64,
    )
    vector_rows = numpy_line_revenue(prices, quantities, discounts)
    try:
        np.testing.assert_allclose(
            loop_rows,
            vector_rows,
            rtol=ROW_RTOL,
            atol=ROW_ATOL,
        )
    except AssertionError as error:
        raise BenchmarkError("line-level implementations disagree") from error

    loop_total = python_net_revenue(price_list, quantity_list, discount_list)
    vector_total = numpy_net_revenue(prices, quantities, discounts)
    if not np.isclose(
        loop_total,
        vector_total,
        rtol=TOTAL_RTOL,
        atol=TOTAL_ATOL,
    ):
        raise BenchmarkError(
            f"aggregate implementations disagree: loop={loop_total}, vectorized={vector_total}"
        )

    return {
        "line_values_close": True,
        "line_shape": list(vector_rows.shape),
        "max_line_absolute_difference": float(np.max(np.abs(loop_rows - vector_rows), initial=0.0)),
        "totals_close": True,
        "loop_total": loop_total,
        "vectorized_total": vector_total,
        "absolute_total_difference": abs(loop_total - vector_total),
        "tolerances": {
            "line_rtol": ROW_RTOL,
            "line_atol": ROW_ATOL,
            "total_rtol": TOTAL_RTOL,
            "total_atol": TOTAL_ATOL,
        },
    }


def measure_seconds(
    function: Callable[[], float],
    repeat: int,
) -> tuple[float, list[float]]:
    """Warm up once, then return the median and every measured duration."""

    _validate_repeat(repeat)
    function()
    durations: list[float] = []
    for _ in range(repeat):
        started = time.perf_counter_ns()
        function()
        elapsed_ns = max(time.perf_counter_ns() - started, 1)
        durations.append(elapsed_ns / 1_000_000_000)
    return statistics.median(durations), durations


def estimate_array_memory(size: int) -> dict[str, Any]:
    """Estimate known ndarray storage, not allocator or Python-object overhead."""

    _validate_size(size)
    float64_vector_bytes = size * np.dtype(np.float64).itemsize
    int64_vector_bytes = size * np.dtype(np.int64).itemsize
    input_array_bytes = 2 * float64_vector_bytes + int64_vector_bytes
    return {
        "input_array_bytes": input_array_bytes,
        "one_float64_vector_bytes": float64_vector_bytes,
        "straight_expression_peak_temporary_array_count": 3,
        "straight_expression_estimated_peak_temporary_bytes": (3 * float64_vector_bytes),
        "estimate_boundary": (
            "ndarray data buffers only; excludes allocator, Python lists, "
            "Python scalar objects and process overhead"
        ),
    }


def environment_report() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
    }


def benchmark(size: int, repeat: int, seed: int) -> dict[str, Any]:
    """Run a calculation-only comparison with explicit correctness gates."""

    _validate_size(size)
    _validate_repeat(repeat)
    _validate_seed(seed)

    raw_prices, raw_quantities, raw_discounts = generate_inputs(size, seed)
    prices, quantities, discounts = prepare_inputs(
        raw_prices,
        raw_quantities,
        raw_discounts,
    )
    price_list = prices.tolist()
    quantity_list = quantities.tolist()
    discount_list = discounts.tolist()

    correctness = compare_results(
        price_list,
        quantity_list,
        discount_list,
        prices,
        quantities,
        discounts,
    )

    loop_median, loop_runs = measure_seconds(
        lambda: python_net_revenue(price_list, quantity_list, discount_list),
        repeat,
    )
    vector_median, vector_runs = measure_seconds(
        lambda: numpy_net_revenue(prices, quantities, discounts),
        repeat,
    )

    return {
        "contract_version": 1,
        "experiment": "line-item net revenue: Python loop vs NumPy expression",
        "input_generation": {
            "size": size,
            "seed": seed,
            "generator": "numpy.random.Generator",
            "bit_generator": type(np.random.default_rng(seed).bit_generator).__name__,
        },
        "input_contract": {
            "axis_names": ["line_item"],
            "shape": [size],
            "dtypes": {
                "prices": str(prices.dtype),
                "quantities": str(quantities.dtype),
                "discounts": str(discounts.dtype),
            },
            "domain": {
                "prices": "finite and >= 0",
                "quantities": "integer and >= 0",
                "discounts": "finite and in [0, 1]",
            },
        },
        "correctness": correctness,
        "scope": {
            "name": "calculation_only",
            "included": [
                "line-item formula",
                "reduction to total revenue",
            ],
            "excluded": [
                "input generation",
                "input validation",
                "ndarray-to-list conversion",
                "correctness checks",
                "JSON serialization",
            ],
            "representations": {
                "loop": "prepared Python lists",
                "vectorized": "prepared contiguous NumPy arrays",
            },
        },
        "timing": {
            "timer": "time.perf_counter_ns",
            "warmup_calls_per_implementation": 1,
            "repeat": repeat,
            "summary_statistic": "median",
            "loop_seconds": {
                "median": loop_median,
                "runs": loop_runs,
            },
            "vectorized_seconds": {
                "median": vector_median,
                "runs": vector_runs,
            },
            "speedup_loop_over_vectorized": loop_median / vector_median,
        },
        "memory": estimate_array_memory(size),
        "environment": environment_report(),
        "claim_boundary": (
            "The speedup describes this input, scope, implementation and environment; "
            "it is not a universal NumPy guarantee."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare a Python loop and a NumPy line-item calculation"
    )
    parser.add_argument("--size", type=int, default=100_000)
    parser.add_argument("--repeat", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = benchmark(args.size, args.repeat, args.seed)
        text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
    except (BenchmarkError, OSError) as error:
        parser.exit(2, f"vectorization-benchmark: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
