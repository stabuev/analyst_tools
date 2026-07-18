from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "numerical_checks.py"
SPEC = importlib.util.spec_from_file_location("numerical_checks", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CHECKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKS)


if __name__ == "__main__":
    division = CHECKS.safe_divide(
        [10.0, 20.0, 30.0],
        [2.0, 0.0, 5.0],
        fill_value=np.nan,
    )
    report = {
        "comparison": CHECKS.tolerance_report(
            [0.1 + 0.2, 10.0],
            [0.3, 10.0],
            rtol=1e-9,
            atol=1e-12,
        ),
        "safe_divide": [float(value) if np.isfinite(value) else None for value in division],
        "checked_integer_add": CHECKS.checked_integer_add(
            [100, 10],
            20,
            dtype="int8",
        ).tolist(),
        "float32_range": CHECKS.floating_range_report("float32"),
        "summation": CHECKS.summation_report([1e8, 1.0, -1e8]),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
