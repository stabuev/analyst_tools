from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


def read_paid_amounts(path: Path) -> np.ndarray:
    """Read amounts of paid orders from the course sample CSV."""
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        fields = set(reader.fieldnames or [])
        missing = {"status", "amount"} - fields
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"missing required columns: {names}")

        amounts: list[float] = []
        for row_number, row in enumerate(reader, start=2):
            if row["status"] != "paid":
                continue
            try:
                amounts.append(float(row["amount"]))
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"row {row_number}: amount must be a number"
                ) from error

    if not amounts:
        raise ValueError("the file contains no paid orders")
    return np.asarray(amounts, dtype=float)


def summarize_paid_orders(path: Path) -> dict[str, float | int]:
    amounts = read_paid_amounts(path)
    return {
        "paid_order_count": int(amounts.size),
        "revenue": round(float(amounts.sum()), 2),
        "average_paid_order": round(float(amounts.mean()), 2),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize paid orders from a synthetic CSV sample"
    )
    parser.add_argument("orders_csv", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = summarize_paid_orders(args.orders_csv)
    except (OSError, ValueError) as error:
        parser.exit(2, f"revenue-summary: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
