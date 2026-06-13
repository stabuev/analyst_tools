from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "null_semantics.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("null_semantics", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manual = {"TRUE": 6, "FALSE": 4, "UNKNOWN": 2}
    report = load_artifact().audit_null_filter(DATA, threshold=100)
    print(json.dumps({"manual": manual, "duckdb": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
