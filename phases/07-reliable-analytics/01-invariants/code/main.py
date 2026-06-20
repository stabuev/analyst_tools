from __future__ import annotations

import csv
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.invariant_gate import evaluate_orders


def manual_control(rows: list[dict[str, str]]) -> dict[str, Any]:
    order_ids = [row["order_id"] for row in rows]
    paid_amounts = [
        Decimal(row["amount_rub"]) for row in rows if row["status"].strip().lower() == "paid"
    ]
    return {
        "order_count": len(rows),
        "unique_order_count": len(set(order_ids)),
        "paid_order_count": len(paid_amounts),
        "paid_revenue_rub": f"{sum(paid_amounts, start=Decimal('0')):.2f}",
    }


def main() -> None:
    lesson_root = Path(__file__).resolve().parents[1]
    input_path = lesson_root.parent / "data" / "tiny" / "orders.csv"
    with input_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    print(
        json.dumps(
            {
                "manual_control": manual_control(rows),
                "invariant_gate": evaluate_orders(rows, fieldnames),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
