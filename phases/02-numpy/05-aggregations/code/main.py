from __future__ import annotations

import importlib.util
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "axis_aggregates.py"
SPEC = importlib.util.spec_from_file_location("axis_aggregates", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AGGREGATES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGGREGATES)


if __name__ == "__main__":
    daily_metrics = [
        [[10, 1000], [12, 1440], [8, 880]],
        [[7, 840], [9, 990], [11, 1320]],
    ]
    print(
        AGGREGATES.aggregate(
            daily_metrics,
            axis=(0, 1),
            axis_names=("store", "day", "metric"),
            keepdims=True,
        )
    )
