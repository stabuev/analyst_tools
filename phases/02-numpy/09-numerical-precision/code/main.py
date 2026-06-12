from __future__ import annotations

import importlib.util
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "numerical_checks.py"
SPEC = importlib.util.spec_from_file_location("numerical_checks", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CHECKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKS)


if __name__ == "__main__":
    print(
        CHECKS.tolerance_report(
            [0.1 + 0.2, 10.0],
            [0.3, 10.0],
            rtol=1e-9,
            atol=1e-12,
        )
    )
    print(CHECKS.summation_report([1e8, 1.0, -1e8]))
