from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Sequence
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import numpy as np


class SimulationError(ValueError):
    """Raised when a simulation contract is incomplete or unsafe."""


def normalize_positive_integer(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise SimulationError(f"{name} must be an integer")
    normalized = int(value)
    if normalized <= 0:
        raise SimulationError(f"{name} must be positive")
    return normalized


def normalize_seed(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise SimulationError("seed must be an integer")
    seed = int(value)
    if seed < 0:
        raise SimulationError("seed must be non-negative")
    return seed


def normalize_probabilities(values: object) -> np.ndarray:
    if isinstance(values, np.ndarray):
        if values.ndim != 1:
            raise SimulationError("probabilities must be one-dimensional")
        raw_values: Sequence[object] = values.tolist()
    elif isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise SimulationError("probabilities must be a non-empty sequence")
    else:
        raw_values = values
    if not raw_values:
        raise SimulationError("probabilities must be a non-empty sequence")
    normalized: list[float] = []
    for value in raw_values:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise SimulationError("each probability must be a real number")
        probability = float(value)
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise SimulationError("each probability must be finite and between 0 and 1")
        normalized.append(probability)
    return np.asarray(normalized, dtype=np.float64)


def normalize_group_names(values: object, *, group_count: int) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise SimulationError("group_names must be a sequence")
    names = tuple(values)
    if len(names) != group_count:
        raise SimulationError(f"expected {group_count} group names, received {len(names)}")
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise SimulationError("group names must be non-empty strings")
    if len(set(names)) != len(names):
        raise SimulationError("group names must be unique")
    return names


def memory_contract(
    *,
    scenario_count: int,
    observations_per_group: int,
    group_count: int,
    memory_limit_mb: float,
) -> dict[str, int | float]:
    if (
        isinstance(memory_limit_mb, bool)
        or not isinstance(memory_limit_mb, Real)
        or not math.isfinite(float(memory_limit_mb))
        or memory_limit_mb <= 0
    ):
        raise SimulationError("memory_limit_mb must be a positive finite number")

    element_count = scenario_count * observations_per_group * group_count
    draws_nbytes = element_count * np.dtype(np.float64).itemsize
    events_nbytes = element_count * np.dtype(np.bool_).itemsize
    estimated_working_nbytes = draws_nbytes + events_nbytes
    memory_limit_bytes = int(float(memory_limit_mb) * 1024 * 1024)
    if estimated_working_nbytes > memory_limit_bytes:
        raise SimulationError(
            "simulation needs approximately "
            f"{estimated_working_nbytes} bytes, above limit {memory_limit_bytes}"
        )
    return {
        "element_count": element_count,
        "draws_nbytes": draws_nbytes,
        "events_nbytes": events_nbytes,
        "estimated_working_nbytes": estimated_working_nbytes,
        "memory_limit_mb": float(memory_limit_mb),
    }


def simulate_binary_events(
    *,
    probabilities: Sequence[object],
    scenario_count: int,
    observations_per_group: int,
    rng: np.random.Generator,
    memory_limit_mb: float = 256.0,
) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(rng, np.random.Generator):
        raise SimulationError("rng must be a numpy.random.Generator")
    normalized_probabilities = normalize_probabilities(probabilities)
    scenarios = normalize_positive_integer(scenario_count, name="scenario_count")
    observations = normalize_positive_integer(
        observations_per_group,
        name="observations_per_group",
    )
    shape = (scenarios, observations, normalized_probabilities.size)
    memory_contract(
        scenario_count=scenarios,
        observations_per_group=observations,
        group_count=normalized_probabilities.size,
        memory_limit_mb=memory_limit_mb,
    )

    draws = rng.random(shape)
    events = draws < normalized_probabilities
    return draws, events


def array_fingerprint(array: np.ndarray) -> str:
    contiguous = np.ascontiguousarray(array)
    return hashlib.sha256(contiguous.tobytes()).hexdigest()


def simulation_report(
    *,
    probabilities: Sequence[object],
    group_names: Sequence[object],
    scenario_count: int,
    observations_per_group: int,
    seed: int,
    memory_limit_mb: float = 256.0,
) -> dict[str, Any]:
    normalized_probabilities = normalize_probabilities(probabilities)
    names = normalize_group_names(
        group_names,
        group_count=normalized_probabilities.size,
    )
    scenarios = normalize_positive_integer(scenario_count, name="scenario_count")
    observations = normalize_positive_integer(
        observations_per_group,
        name="observations_per_group",
    )
    normalized_seed = normalize_seed(seed)
    memory = memory_contract(
        scenario_count=scenarios,
        observations_per_group=observations,
        group_count=normalized_probabilities.size,
        memory_limit_mb=memory_limit_mb,
    )

    rng = np.random.default_rng(normalized_seed)
    draws, events = simulate_binary_events(
        probabilities=normalized_probabilities,
        scenario_count=scenarios,
        observations_per_group=observations,
        rng=rng,
        memory_limit_mb=memory_limit_mb,
    )
    group_event_counts = events.sum(axis=(0, 1), dtype=np.int64)
    group_event_rates = events.mean(axis=(0, 1))
    scenario_event_counts = events.sum(axis=(1, 2), dtype=np.int64)

    return {
        "manifest": {
            "generator": type(rng).__name__,
            "bit_generator": type(rng.bit_generator).__name__,
            "seed": normalized_seed,
            "call_contract": {
                "method": "Generator.random",
                "size": list(draws.shape),
                "dtype": str(draws.dtype),
            },
        },
        "model": {
            "description": (
                "событие происходит, когда равномерное число меньше вероятности группы"
            ),
            "group_names": list(names),
            "event_probabilities": normalized_probabilities.tolist(),
        },
        "arrays": {
            "draws": {
                "shape": list(draws.shape),
                "axis_names": ["scenario", "observation", "group"],
                "dtype": str(draws.dtype),
                "minimum": float(draws.min()),
                "maximum": float(draws.max()),
                "sha256": array_fingerprint(draws),
            },
            "events": {
                "shape": list(events.shape),
                "axis_names": ["scenario", "observation", "group"],
                "dtype": str(events.dtype),
                "sha256": array_fingerprint(events),
            },
        },
        "summary": {
            "event_count_by_group": dict(zip(names, group_event_counts.tolist(), strict=True)),
            "event_rate_by_group": dict(zip(names, group_event_rates.tolist(), strict=True)),
            "first_five_scenario_event_counts": scenario_event_counts[:5].tolist(),
            "first_three_observations": events[0, :3, :].tolist(),
        },
        "memory": memory,
    }


def parse_json(raw: str, *, name: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise SimulationError(f"{name} must be valid JSON") from error


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a reproducible binary-event simulation with a manifest"
    )
    parser.add_argument(
        "--probabilities",
        default="[0.08, 0.15, 0.30]",
        help="JSON array with one event probability per group",
    )
    parser.add_argument(
        "--group-names",
        default='["chat", "email", "phone"]',
        help="JSON array with semantic names for the group axis",
    )
    parser.add_argument("--scenarios", type=int, default=1_000)
    parser.add_argument("--observations-per-group", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--memory-limit-mb", type=float, default=256.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        probabilities = parse_json(args.probabilities, name="probabilities")
        group_names = parse_json(args.group_names, name="group_names")
        report = simulation_report(
            probabilities=probabilities,
            group_names=group_names,
            scenario_count=args.scenarios,
            observations_per_group=args.observations_per_group,
            seed=args.seed,
            memory_limit_mb=args.memory_limit_mb,
        )
    except SimulationError as error:
        parser.exit(2, f"event-simulator: {error}\n")

    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
