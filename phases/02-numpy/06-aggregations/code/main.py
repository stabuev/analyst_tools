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
    print(AGGREGATES.aggregate([[1, 2, 3], [4, 5, 6]], axis=0))
