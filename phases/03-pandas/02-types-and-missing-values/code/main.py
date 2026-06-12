from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dtype_audit.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("dtype_audit", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    audit = load_artifact()
    frame = pd.read_csv(DATA, dtype="string")
    schema = {
        "order_id": "string",
        "amount": "Float64",
        "ordered_at": "datetime_utc",
    }
    _, report = audit.audit_and_convert(frame, schema)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
