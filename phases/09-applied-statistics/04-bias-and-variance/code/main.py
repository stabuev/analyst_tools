from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
DATA = PHASE / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "bias_variance_simulator.py"
SPEC = ROOT / "outputs" / "bias_variance_spec.json"


def load_simulator():
    module_spec = importlib.util.spec_from_file_location("bias_variance_simulator", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    simulator = load_simulator()
    report = simulator.simulate(DATA / "population_users.csv", DATA / "sampling_frame.csv", SPEC)
    rows = {
        f"{row['mechanism_id']}::{row['estimator_id']}": {
            "bias": row["bias"],
            "variance": row["variance"],
            "mse": row["mse"],
            "bias_flag": row["bias_flag"],
        }
        for row in report["simulation_rows"]
    }
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "true_parameters": report["true_parameters"],
                "simulation_rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
