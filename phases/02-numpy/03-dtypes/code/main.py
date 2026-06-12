from __future__ import annotations

import importlib.util
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "dtype_audit.py"
SPEC = importlib.util.spec_from_file_location("dtype_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


if __name__ == "__main__":
    print(AUDIT.audit_values([0, 12, 255], dtype="uint8"))
    print(AUDIT.audit_values([12.5, None, 18.0]))
