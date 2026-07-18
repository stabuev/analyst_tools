from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "dtype_audit.py"
SPEC = importlib.util.spec_from_file_location("dtype_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


if __name__ == "__main__":
    report = AUDIT.audit_values(
        [0, 12, 200],
        target_dtype="uint16",
        expected_min=0,
        expected_max=20_000,
        planned_shape=(500, 365, 24),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
