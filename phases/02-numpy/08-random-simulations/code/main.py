from __future__ import annotations

import importlib.util
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "reproducible_event_simulator.py"
SPEC = importlib.util.spec_from_file_location("reproducible_event_simulator", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SIMULATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIMULATION)


if __name__ == "__main__":
    print(
        SIMULATION.simulation_report(
            probabilities=[0.08, 0.15, 0.30],
            group_names=["chat", "email", "phone"],
            scenario_count=1_000,
            observations_per_group=50,
            seed=42,
        )
    )
