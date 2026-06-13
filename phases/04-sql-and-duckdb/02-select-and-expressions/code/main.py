from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "select_contract.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("select_contract", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manual = [
        {"order_id": "O1001", "amount": 1200.0, "amount_with_fee": 1260.0},
        {"order_id": "O1005", "amount": 1500.0, "amount_with_fee": 1575.0},
    ]
    report = load_artifact().run_select(
        DATA,
        currency="RUB",
        min_amount=Decimal("100"),
        fee_rate=Decimal("0.05"),
    )
    print(json.dumps({"manual": manual, "duckdb": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
