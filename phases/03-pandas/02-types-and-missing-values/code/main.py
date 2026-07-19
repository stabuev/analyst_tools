from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dtype_audit.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("dtype_audit", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_example() -> tuple[pd.DataFrame, dict[str, dict[str, object]]]:
    frame = pd.DataFrame(
        {
            "order_id": ["O1001", "O1002", "O1003"],
            "amount": ["1200.00", "", "oops"],
        },
        dtype="string",
    )
    schema = {
        "order_id": {"dtype": "string", "nullable": False},
        "amount": {"dtype": "Float64", "nullable": True},
    }
    return frame, schema


def main() -> None:
    audit = load_artifact()
    frame, schema = build_example()
    converted, report = audit.audit_and_convert(frame, schema)

    print("Converted dtypes:")
    print(converted.dtypes.to_string())
    print("\nAudit report:")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
