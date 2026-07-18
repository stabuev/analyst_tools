from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "shape_contract.py"
SPEC = importlib.util.spec_from_file_location("shape_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SHAPES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHAPES)


if __name__ == "__main__":
    # Продолжение примера первого урока: к осям store и day добавилась ось metric.
    daily_metrics = np.array(
        [
            [[12, 1200], [15, 1500], [9, 900]],
            [[10, 1000], [11, 1100], [14, 1400]],
        ]
    )
    axis_names = ("store", "day", "metric")

    report = SHAPES.build_report(
        daily_metrics.shape,
        axis_names=axis_names,
        axis=1,
        reshape=(6, 2),
        reshape_axis_names=("store_day", "metric"),
        transpose=(2, 0, 1),
        expand_axis=-1,
        expand_axis_name="scenario",
    )

    SHAPES.assert_shape(
        daily_metrics.sum(axis=1),
        (2, 2),
        name="store_totals",
        axis_names=("store", "metric"),
    )
    SHAPES.assert_shape(
        daily_metrics.reshape(6, 2),
        (6, 2),
        name="store_day_rows",
        axis_names=("store_day", "metric"),
    )
    SHAPES.assert_shape(
        np.transpose(daily_metrics, (2, 0, 1)),
        (2, 2, 3),
        name="metric_first",
        axis_names=("metric", "store", "day"),
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
