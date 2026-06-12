from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "numeric_filters.py"
SPEC = importlib.util.spec_from_file_location("numeric_filters", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
FILTERS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FILTERS)


if __name__ == "__main__":
    values = np.array([5.0, 12.0, np.nan, 18.0, 27.0])
    print(FILTERS.range_mask(values, lower=10, upper=20))
    print(FILTERS.filter_observations(values, lower=10, upper=20))
    print(FILTERS.memory_report([5, 12, 18, 27]))
