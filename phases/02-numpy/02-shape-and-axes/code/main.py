from __future__ import annotations

import importlib.util
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "shape_contract.py"
SPEC = importlib.util.spec_from_file_location("shape_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SHAPES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHAPES)


if __name__ == "__main__":
    report = SHAPES.build_report(
        (2, 3, 4),
        axis=1,
        keepdims=True,
        reshape=(6, 4),
        transpose=(2, 0, 1),
        expand_axis=-1,
    )
    print(report)
