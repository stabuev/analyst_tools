from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parent
SAMPLE_SEED = 20_260_613
SAMPLE_USERS = 1_000
SAMPLE_ORDERS = 5_000
MOSCOW = timezone(timedelta(hours=3))

USER_COLUMNS = ("user_id", "registered_at", "country", "plan")
ORDER_COLUMNS = (
    "order_id",
    "user_id",
    "ordered_at",
    "status",
    "currency",
    "amount_rub",
)
ITEM_COLUMNS = (
    "order_id",
    "line_number",
    "product_id",
    "quantity",
    "unit_price_rub",
)

TINY_USERS = [
    ("U001", "2026-05-01T09:00:00+03:00", "RU", "basic"),
    ("U002", "2026-05-02T11:00:00+03:00", "KZ", "premium"),
    ("U003", "2026-05-03T13:00:00+03:00", "RU", "trial"),
    ("U004", "2026-05-04T15:00:00+03:00", "AM", "basic"),
    ("U005", "2026-05-05T17:00:00+03:00", "RU", "premium"),
    ("U006", "2026-05-06T19:00:00+03:00", "DE", "basic"),
]

TINY_ORDERS = [
    ("O001", "U001", "2026-06-08T09:10:00+03:00", "paid", "RUB", "1200.00"),
    ("O002", "U001", "2026-06-08T10:20:00+03:00", "paid", "RUB", "800.00"),
    ("O003", "U002", "2026-06-08T11:30:00+03:00", "refunded", "RUB", "2400.00"),
    ("O004", "U003", "2026-06-08T12:40:00+03:00", "cancelled", "RUB", "500.00"),
    ("O005", "U004", "2026-06-09T09:15:00+03:00", "paid", "RUB", "1500.00"),
    ("O006", "U005", "2026-06-09T10:25:00+03:00", "paid", "RUB", "3200.00"),
    ("O007", "U006", "2026-06-09T11:35:00+03:00", "pending", "RUB", "900.00"),
    ("O008", "U002", "2026-06-09T12:45:00+03:00", "paid", "RUB", "750.50"),
    ("O009", "U003", "2026-06-10T09:50:00+03:00", "paid", "RUB", "1100.00"),
    ("O010", "U004", "2026-06-10T10:55:00+03:00", "paid", "RUB", "600.00"),
]

TINY_ITEMS = [
    ("O001", "1", "P001", "1", "700.00"),
    ("O001", "2", "P002", "1", "500.00"),
    ("O002", "1", "P003", "2", "400.00"),
    ("O003", "1", "P004", "1", "2400.00"),
    ("O004", "1", "P005", "1", "500.00"),
    ("O005", "1", "P006", "3", "500.00"),
    ("O006", "1", "P007", "1", "2000.00"),
    ("O006", "2", "P008", "2", "600.00"),
    ("O007", "1", "P009", "1", "900.00"),
    ("O008", "1", "P010", "1", "750.50"),
    ("O009", "1", "P011", "2", "550.00"),
    ("O010", "1", "P012", "1", "600.00"),
]


def rows(columns: tuple[str, ...], values: list[tuple[str, ...]]) -> list[dict[str, str]]:
    return [dict(zip(columns, value, strict=True)) for value in values]


def write_csv(path: Path, fieldnames: tuple[str, ...], records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def tiny_records() -> dict[str, list[dict[str, str]]]:
    return {
        "users": rows(USER_COLUMNS, TINY_USERS),
        "orders": rows(ORDER_COLUMNS, TINY_ORDERS),
        "order_items": rows(ITEM_COLUMNS, TINY_ITEMS),
    }


def sample_records() -> dict[str, list[dict[str, str]]]:
    rng = random.Random(SAMPLE_SEED)
    start = datetime(2026, 5, 1, 9, tzinfo=MOSCOW)
    users: list[dict[str, str]] = []
    for index in range(1, SAMPLE_USERS + 1):
        users.append(
            {
                "user_id": f"U{index:05d}",
                "registered_at": (start + timedelta(minutes=index * 17)).isoformat(),
                "country": rng.choice(["RU", "KZ", "AM", "DE"]),
                "plan": rng.choice(["trial", "basic", "premium"]),
            }
        )

    orders: list[dict[str, str]] = []
    items: list[dict[str, str]] = []
    order_start = datetime(2026, 6, 1, 0, tzinfo=MOSCOW)
    for index in range(1, SAMPLE_ORDERS + 1):
        order_id = f"O{index:06d}"
        item_count = rng.randint(1, 3)
        total_kopecks = 0
        for line_number in range(1, item_count + 1):
            quantity = rng.randint(1, 3)
            unit_kopecks = rng.choice([19_900, 35_000, 49_900, 75_050, 120_000])
            total_kopecks += quantity * unit_kopecks
            items.append(
                {
                    "order_id": order_id,
                    "line_number": str(line_number),
                    "product_id": f"P{rng.randint(1, 200):04d}",
                    "quantity": str(quantity),
                    "unit_price_rub": f"{unit_kopecks / 100:.2f}",
                }
            )
        orders.append(
            {
                "order_id": order_id,
                "user_id": f"U{rng.randint(1, SAMPLE_USERS):05d}",
                "ordered_at": (
                    order_start + timedelta(minutes=rng.randint(0, 20 * 24 * 60))
                ).isoformat(),
                "status": rng.choices(
                    ["paid", "refunded", "cancelled", "pending"],
                    weights=[72, 8, 12, 8],
                    k=1,
                )[0],
                "currency": "RUB",
                "amount_rub": f"{total_kopecks / 100:.2f}",
            }
        )
    return {"users": users, "orders": orders, "order_items": items}


def write_profile(profile: str, output_root: Path) -> dict[str, Any]:
    records = tiny_records() if profile == "tiny" else sample_records()
    output_root.mkdir(parents=True, exist_ok=True)
    specs = {
        "users": ("users.csv", USER_COLUMNS),
        "orders": ("orders.csv", ORDER_COLUMNS),
        "order_items": ("order_items.csv", ITEM_COLUMNS),
    }
    files: dict[str, dict[str, Any]] = {}
    for name, (filename, columns) in specs.items():
        path = output_root / filename
        write_csv(path, columns, records[name])
        files[filename] = {
            "rows": len(records[name]),
            "sha256": checksum(path),
        }
    manifest = {
        "profile": profile,
        "generator": "generate_data.py",
        "seed": SAMPLE_SEED if profile == "sample" else None,
        "files": files,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def check_tiny() -> None:
    expected_root = ROOT / "tiny"
    with TemporaryDirectory() as directory:
        actual_root = Path(directory) / "tiny"
        write_profile("tiny", actual_root)
        expected_files = sorted(path.name for path in expected_root.iterdir())
        actual_files = sorted(path.name for path in actual_root.iterdir())
        if expected_files != actual_files:
            raise SystemExit(
                f"tiny file set differs: expected={expected_files}, actual={actual_files}"
            )
        for filename in expected_files:
            if (expected_root / filename).read_bytes() != (actual_root / filename).read_bytes():
                raise SystemExit(f"tiny profile is stale: {filename}")
    print("Tiny reliability dataset is reproducible.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate phase 07 reliability datasets")
    parser.add_argument("--profile", choices=("tiny", "sample"), default="tiny")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check_tiny()
        return
    output_dir = args.output_dir or ROOT / args.profile
    manifest = write_profile(args.profile, output_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
