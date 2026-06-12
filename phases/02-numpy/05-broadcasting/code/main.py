from __future__ import annotations

import importlib.util
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "feature_normalization.py"
SPEC = importlib.util.spec_from_file_location("feature_normalization", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
NORMALIZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NORMALIZE)


if __name__ == "__main__":
    print(NORMALIZE.build_report([[1, 10], [3, 14], [5, 18]]))
