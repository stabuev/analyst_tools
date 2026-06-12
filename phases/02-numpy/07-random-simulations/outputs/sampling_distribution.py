from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

MAX_GENERATED_VALUES = 10_000_000


class SimulationError(ValueError):
    """Raised when simulation parameters violate the experiment contract."""


def validate_parameters(
    *,
    population_std: float,
    sample_size: int,
    repetitions: int,
    seed: int,
) -> None:
    if not math.isfinite(population_std) or population_std <= 0:
        raise SimulationError("population_std must be a positive finite number")
    if sample_size <= 0:
        raise SimulationError("sample_size must be positive")
    if repetitions < 2:
        raise SimulationError("repetitions must be at least 2")
    if sample_size * repetitions > MAX_GENERATED_VALUES:
        raise SimulationError(
            f"simulation exceeds the limit of {MAX_GENERATED_VALUES} generated values"
        )
    if seed < 0:
        raise SimulationError("seed must be non-negative")


def simulate_sample_means(
    *,
    population_mean: float,
    population_std: float,
    sample_size: int,
    repetitions: int,
    seed: int,
) -> np.ndarray:
    validate_parameters(
        population_std=population_std,
        sample_size=sample_size,
        repetitions=repetitions,
        seed=seed,
    )
    if not math.isfinite(population_mean):
        raise SimulationError("population_mean must be finite")
    rng = np.random.default_rng(seed)
    samples = rng.normal(
        loc=population_mean,
        scale=population_std,
        size=(repetitions, sample_size),
    )
    return samples.mean(axis=1)


def simulation_report(
    *,
    population_mean: float,
    population_std: float,
    sample_size: int,
    repetitions: int,
    seed: int,
) -> dict[str, Any]:
    means = simulate_sample_means(
        population_mean=population_mean,
        population_std=population_std,
        sample_size=sample_size,
        repetitions=repetitions,
        seed=seed,
    )
    theoretical_standard_error = population_std / math.sqrt(sample_size)
    empirical_standard_error = float(means.std(ddof=1))
    return {
        "generator": "numpy.random.Generator",
        "seed": seed,
        "population_mean": population_mean,
        "population_std": population_std,
        "sample_size": sample_size,
        "repetitions": repetitions,
        "theoretical_standard_error": theoretical_standard_error,
        "empirical_mean": float(means.mean()),
        "empirical_standard_error": empirical_standard_error,
        "standard_error_ratio": empirical_standard_error / theoretical_standard_error,
        "quantiles": {
            "0.025": float(np.quantile(means, 0.025)),
            "0.500": float(np.quantile(means, 0.5)),
            "0.975": float(np.quantile(means, 0.975)),
        },
        "first_five_means": means[:5].tolist(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simulate a sampling distribution with NumPy Generator"
    )
    parser.add_argument("--mean", type=float, default=100.0)
    parser.add_argument("--std", type=float, default=15.0)
    parser.add_argument("--sample-size", type=int, default=25)
    parser.add_argument("--repetitions", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = simulation_report(
            population_mean=args.mean,
            population_std=args.std,
            sample_size=args.sample_size,
            repetitions=args.repetitions,
            seed=args.seed,
        )
    except SimulationError as error:
        parser.exit(2, f"sampling-distribution: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
