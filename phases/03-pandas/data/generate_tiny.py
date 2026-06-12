from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

TABLES: dict[str, list[dict[str, str]]] = {
    "order_items.csv": [
        {
            "order_id": "O1001",
            "product_id": "P01",
            "category": " add-on ",
            "quantity": "1",
            "unit_price": "800.00",
        },
        {
            "order_id": "O1001",
            "product_id": "P02",
            "category": "Addon",
            "quantity": "2",
            "unit_price": "200.00",
        },
        {
            "order_id": "O1002",
            "product_id": "P03",
            "category": "subscription",
            "quantity": "1",
            "unit_price": "800.00",
        },
        {
            "order_id": "O1003",
            "product_id": "P01",
            "category": "ADD-ON",
            "quantity": "1",
            "unit_price": "5500.00",
        },
        {
            "order_id": "O1004",
            "product_id": "P04",
            "category": "service",
            "quantity": "1",
            "unit_price": "2300.00",
        },
        {
            "order_id": "O1005",
            "product_id": "P05",
            "category": "Subscription",
            "quantity": "1",
            "unit_price": "49.99",
        },
        {
            "order_id": "O1006",
            "product_id": "P06",
            "category": "service",
            "quantity": "1",
            "unit_price": "0.00",
        },
        {
            "order_id": "O1007",
            "product_id": "P07",
            "category": "add-on",
            "quantity": "1",
            "unit_price": "75.50",
        },
    ],
    "orders.csv": [
        {
            "order_id": "O1001",
            "user_id": "U001",
            "ordered_at": "2026-02-01T10:00:00+03:00",
            "status": "paid",
            "currency": "RUB",
            "amount": "1200.00",
        },
        {
            "order_id": "O1002",
            "user_id": "U001",
            "ordered_at": "2026-02-01T23:30:00Z",
            "status": "refunded",
            "currency": "RUB",
            "amount": "800.00",
        },
        {
            "order_id": "O1003",
            "user_id": "U002",
            "ordered_at": "2026-02-02T01:15:00+06:00",
            "status": " paid ",
            "currency": "KZT",
            "amount": "5500.00",
        },
        {
            "order_id": "O1004",
            "user_id": "U003",
            "ordered_at": "2026-02-03T12:00:00+05:00",
            "status": "pending",
            "currency": "KZT",
            "amount": "",
        },
        {
            "order_id": "O1005",
            "user_id": "U999",
            "ordered_at": "2026-02-04T20:45:00-05:00",
            "status": "paid",
            "currency": "USD",
            "amount": "49.99",
        },
        {
            "order_id": "O1006",
            "user_id": "U004",
            "ordered_at": "",
            "status": "cancelled",
            "currency": "USD",
            "amount": "0.00",
        },
        {
            "order_id": "O1007",
            "user_id": "U005",
            "ordered_at": "2026-02-06T09:30:00+01:00",
            "status": "PAID",
            "currency": "EUR",
            "amount": "75.50",
        },
    ],
    "users.csv": [
        {
            "user_id": "U001",
            "registered_at": "2026-01-02T08:15:00+03:00",
            "country": "RU",
            "plan": "basic",
            "is_marketing_opt_in": "true",
        },
        {
            "user_id": "U002",
            "registered_at": "2026-01-03T19:20:00Z",
            "country": " kz ",
            "plan": "Premium",
            "is_marketing_opt_in": "false",
        },
        {
            "user_id": "U003",
            "registered_at": "2026-01-05T10:00:00+05:00",
            "country": "",
            "plan": "basic",
            "is_marketing_opt_in": "",
        },
        {
            "user_id": "U004",
            "registered_at": "2026-01-08T23:30:00-05:00",
            "country": "US",
            "plan": "trial",
            "is_marketing_opt_in": "true",
        },
        {
            "user_id": "U005",
            "registered_at": "2026-01-10T09:00:00+01:00",
            "country": "DE",
            "plan": "premium",
            "is_marketing_opt_in": "false",
        },
    ],
}


def write_table(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "version": "1.0.0",
        "generated_by": "generate_tiny.py",
        "files": {},
    }
    for filename in sorted(TABLES):
        path = output_dir / filename
        rows = TABLES[filename]
        write_table(path, rows)
        manifest["files"][filename] = {
            "rows": len(rows),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic tiny pandas data")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "tiny",
        help="Output directory for CSV files and manifest.json",
    )
    args = parser.parse_args()
    manifest = generate(args.output)
    print(f"Generated {len(manifest['files'])} tables in {args.output}")


if __name__ == "__main__":
    main()
