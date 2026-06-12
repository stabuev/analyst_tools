from __future__ import annotations

import importlib.util
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "sampling_distribution.py"
SPEC = importlib.util.spec_from_file_location("sampling_distribution", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SIMULATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIMULATION)


if __name__ == "__main__":
    print(
        SIMULATION.simulation_report(
            population_mean=100,
            population_std=15,
            sample_size=25,
            repetitions=10_000,
            seed=42,
        )
    )
