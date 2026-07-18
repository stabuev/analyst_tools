from __future__ import annotations

import importlib.util
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "broadcast_contract.py"
SPEC = importlib.util.spec_from_file_location("broadcast_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BROADCAST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROADCAST)


if __name__ == "__main__":
    report = BROADCAST.analyze_broadcast(
        [
            {
                "name": "daily_metrics",
                "shape": [2, 3, 2],
                "axis_names": ["store", "day", "metric"],
                "dtype": "float64",
            },
            {
                "name": "metric_means",
                "shape": [1, 1, 2],
                "axis_names": [
                    "summarized_store",
                    "summarized_day",
                    "metric",
                ],
                "dtype": "float64",
            },
        ],
        operation="subtract",
    )
    print(report)
