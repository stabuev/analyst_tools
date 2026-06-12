from __future__ import annotations

import argparse
import json
import statistics
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np


class BenchmarkError(ValueError):
    """Raised when benchmark inputs or results violate the contract."""


def python_net_revenue(
    prices: Sequence[float],
    quantities: Sequence[int],
    discounts: Sequence[float],
) -> float:
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
    if not (prices.shape == quantities.shape == discounts.shape):
        raise BenchmarkError("input arrays must have equal shapes")
    if prices.ndim != 1:
        raise BenchmarkError("input arrays must be one-dimensional")
    return float(np.sum(prices * quantities * (1.0 - discounts), dtype=np.float64))


def generate_inputs(
    size: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if size <= 0 or size > 2_000_000:
        raise BenchmarkError("size must be between 1 and 2,000,000")
    if seed < 0:
        raise BenchmarkError("seed must be non-negative")
    rng = np.random.default_rng(seed)
    prices = rng.uniform(1.0, 500.0, size=size)
    quantities = rng.integers(1, 6, size=size, dtype=np.int64)
    discounts = rng.choice(np.array([0.0, 0.05, 0.1, 0.2]), size=size)
    return prices, quantities, discounts


def measure_seconds(function: Callable[[], float], repeat: int) -> tuple[float, list[float]]:
    if repeat < 3:
        raise BenchmarkError("repeat must be at least 3")
    function()
    durations: list[float] = []
    for _ in range(repeat):
        started = time.perf_counter()
        function()
        durations.append(time.perf_counter() - started)
    return statistics.median(durations), durations


def benchmark(size: int, repeat: int, seed: int) -> dict[str, Any]:
    prices, quantities, discounts = generate_inputs(size, seed)
    price_list = prices.tolist()
    quantity_list = quantities.tolist()
    discount_list = discounts.tolist()

    loop_result = python_net_revenue(price_list, quantity_list, discount_list)
    vector_result = numpy_net_revenue(prices, quantities, discounts)
    if not np.isclose(loop_result, vector_result, rtol=1e-12, atol=1e-8):
        raise BenchmarkError(
            f"implementations disagree: loop={loop_result}, vector={vector_result}"
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
        "size": size,
        "repeat": repeat,
        "seed": seed,
        "result": vector_result,
        "results_close": True,
        "timing_scope": "calculation only; input conversion excluded",
        "loop_seconds": {
            "median": loop_median,
            "runs": loop_runs,
        },
        "vectorized_seconds": {
            "median": vector_median,
            "runs": vector_runs,
        },
        "speedup": loop_median / vector_median,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark loop and NumPy revenue")
    parser.add_argument("--size", type=int, default=100_000)
    parser.add_argument("--repeat", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = benchmark(args.size, args.repeat, args.seed)
    except BenchmarkError as error:
        parser.exit(2, f"vectorization-benchmark: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
