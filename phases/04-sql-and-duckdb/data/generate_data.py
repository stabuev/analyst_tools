from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SAMPLE_USERS = 25_000
SAMPLE_ORDERS_PER_USER = 4
SAMPLE_EVENTS_PER_USER = 8

TINY_TABLES: dict[str, list[dict[str, str]]] = {
    "events.csv": [
        {
            "event_id": "E0001",
            "user_id": "U001",
            "occurred_at": "2026-01-01T09:00:00Z",
            "event_name": "app_open",
            "session_id": "S001",
        },
        {
            "event_id": "E0002",
            "user_id": "U001",
            "occurred_at": "2026-01-05T07:00:00Z",
            "event_name": "order_paid",
            "session_id": "S002",
        },
        {
            "event_id": "E0003",
            "user_id": "U002",
            "occurred_at": "2026-01-15T18:30:00Z",
            "event_name": "app_open",
            "session_id": "S003",
        },
        {
            "event_id": "E0004",
            "user_id": "U003",
            "occurred_at": "2026-02-01T10:00:00Z",
            "event_name": "app_open",
            "session_id": "",
        },
        {
            "event_id": "E0005",
            "user_id": "U001",
            "occurred_at": "2026-02-05T08:00:00Z",
            "event_name": "order_paid",
            "session_id": "S004",
        },
        {
            "event_id": "E0005",
            "user_id": "U001",
            "occurred_at": "2026-02-05T08:00:00Z",
            "event_name": "order_paid",
            "session_id": "S004",
        },
        {
            "event_id": "E0006",
            "user_id": "U004",
            "occurred_at": "2026-02-10T12:00:00Z",
            "event_name": "trial_started",
            "session_id": "S005",
        },
        {
            "event_id": "E0007",
            "user_id": "U005",
            "occurred_at": "2026-02-20T09:15:00Z",
            "event_name": "app_open",
            "session_id": "S006",
        },
        {
            "event_id": "E0008",
            "user_id": "U002",
            "occurred_at": "2026-03-03T06:45:00Z",
            "event_name": "order_paid",
            "session_id": "S007",
        },
        {
            "event_id": "E0009",
            "user_id": "U006",
            "occurred_at": "2026-03-05T11:00:00Z",
            "event_name": "app_open",
            "session_id": "",
        },
        {
            "event_id": "E0010",
            "user_id": "U007",
            "occurred_at": "2026-03-07T14:00:00Z",
            "event_name": "order_paid",
            "session_id": "S008",
        },
        {
            "event_id": "E0011",
            "user_id": "U003",
            "occurred_at": "2026-03-12T16:30:00Z",
            "event_name": "app_open",
            "session_id": "S009",
        },
        {
            "event_id": "E0012",
            "user_id": "U008",
            "occurred_at": "2026-03-20T10:10:00Z",
            "event_name": "trial_started",
            "session_id": "S010",
        },
        {
            "event_id": "E0013",
            "user_id": "U001",
            "occurred_at": "2026-04-01T08:00:00Z",
            "event_name": "app_open",
            "session_id": "S011",
        },
        {
            "event_id": "E0014",
            "user_id": "U007",
            "occurred_at": "2026-04-05T07:30:00Z",
            "event_name": "order_paid",
            "session_id": "S012",
        },
        {
            "event_id": "E0015",
            "user_id": "U005",
            "occurred_at": "2026-04-07T12:15:00Z",
            "event_name": "app_open",
            "session_id": "",
        },
    ],
    "order_items.csv": [
        {
            "order_id": "O1001",
            "product_id": "P01",
            "category": "subscription",
            "quantity": "1",
            "unit_price": "1000.00",
        },
        {
            "order_id": "O1001",
            "product_id": "P02",
            "category": " add-on ",
            "quantity": "2",
            "unit_price": "100.00",
        },
        {
            "order_id": "O1002",
            "product_id": "P03",
            "category": "Subscription",
            "quantity": "1",
            "unit_price": "800.00",
        },
        {
            "order_id": "O1003",
            "product_id": "P04",
            "category": "service",
            "quantity": "1",
            "unit_price": "75.00",
        },
        {
            "order_id": "O1004",
            "product_id": "P05",
            "category": "ADD-ON",
            "quantity": "1",
            "unit_price": "50.00",
        },
        {
            "order_id": "O1005",
            "product_id": "P01",
            "category": "subscription",
            "quantity": "1",
            "unit_price": "1200.00",
        },
        {
            "order_id": "O1005",
            "product_id": "P06",
            "category": "service",
            "quantity": "1",
            "unit_price": "300.00",
        },
        {
            "order_id": "O1006",
            "product_id": "P07",
            "category": "subscription",
            "quantity": "1",
            "unit_price": "25.00",
        },
        {
            "order_id": "O1007",
            "product_id": "P08",
            "category": "add-on",
            "quantity": "1",
            "unit_price": "500.00",
        },
        {
            "order_id": "O1008",
            "product_id": "P09",
            "category": "service",
            "quantity": "2",
            "unit_price": "40.00",
        },
        {
            "order_id": "O1009",
            "product_id": "P10",
            "category": "subscription",
            "quantity": "1",
            "unit_price": "900.00",
        },
        {
            "order_id": "O1010",
            "product_id": "P11",
            "category": "add-on",
            "quantity": "1",
            "unit_price": "60.00",
        },
        {
            "order_id": "O1011",
            "product_id": "P12",
            "category": "service",
            "quantity": "1",
            "unit_price": "45.00",
        },
        {
            "order_id": "O1012",
            "product_id": "P13",
            "category": "subscription",
            "quantity": "1",
            "unit_price": "700.00",
        },
    ],
    "orders.csv": [
        {
            "order_id": "O1001",
            "user_id": "U001",
            "ordered_at": "2026-01-05T10:00:00+03:00",
            "status": "paid",
            "currency": "RUB",
            "amount": "1200.00",
        },
        {
            "order_id": "O1002",
            "user_id": "U002",
            "ordered_at": "2026-01-15T19:00:00Z",
            "status": "refunded",
            "currency": "RUB",
            "amount": "800.00",
        },
        {
            "order_id": "O1003",
            "user_id": "U003",
            "ordered_at": "2026-02-01T15:00:00+05:00",
            "status": "paid",
            "currency": "USD",
            "amount": "75.00",
        },
        {
            "order_id": "O1004",
            "user_id": "U004",
            "ordered_at": "2026-02-10T07:00:00-05:00",
            "status": "pending",
            "currency": "USD",
            "amount": "",
        },
        {
            "order_id": "O1005",
            "user_id": "U001",
            "ordered_at": "2026-02-05T11:00:00+03:00",
            "status": "paid",
            "currency": "RUB",
            "amount": "1500.00",
        },
        {
            "order_id": "O1006",
            "user_id": "U005",
            "ordered_at": "2026-02-20T10:15:00+01:00",
            "status": "paid",
            "currency": "EUR",
            "amount": "25.00",
        },
        {
            "order_id": "O1007",
            "user_id": "U002",
            "ordered_at": "2026-03-03T12:45:00+06:00",
            "status": "paid",
            "currency": "KZT",
            "amount": "500.00",
        },
        {
            "order_id": "O1008",
            "user_id": "U006",
            "ordered_at": "",
            "status": "cancelled",
            "currency": "EUR",
            "amount": "",
        },
        {
            "order_id": "O1009",
            "user_id": "U007",
            "ordered_at": "2026-03-07T15:00:00+01:00",
            "status": "paid",
            "currency": "EUR",
            "amount": "900.00",
        },
        {
            "order_id": "O1010",
            "user_id": "U999",
            "ordered_at": "2026-03-10T18:30:00Z",
            "status": "paid",
            "currency": "USD",
            "amount": "60.00",
        },
        {
            "order_id": "O1011",
            "user_id": "U003",
            "ordered_at": "2026-04-01T08:00:00Z",
            "status": "paid",
            "currency": "USD",
            "amount": "45.00",
        },
        {
            "order_id": "O1012",
            "user_id": "U007",
            "ordered_at": "2026-04-05T09:30:00+01:00",
            "status": "paid",
            "currency": "EUR",
            "amount": "700.00",
        },
    ],
    "users.csv": [
        {
            "user_id": "U001",
            "registered_at": "2025-12-15T08:00:00Z",
            "country": "RU",
            "plan": "basic",
        },
        {
            "user_id": "U002",
            "registered_at": "2025-12-20T12:00:00+03:00",
            "country": "ru",
            "plan": "premium",
        },
        {
            "user_id": "U003",
            "registered_at": "2026-01-03T10:00:00+05:00",
            "country": "KZ",
            "plan": "basic",
        },
        {
            "user_id": "U004",
            "registered_at": "2026-01-08T23:30:00-05:00",
            "country": "US",
            "plan": "trial",
        },
        {
            "user_id": "U005",
            "registered_at": "2026-01-10T09:00:00+01:00",
            "country": "DE",
            "plan": "premium",
        },
        {
            "user_id": "U006",
            "registered_at": "2026-02-01T08:00:00Z",
            "country": "",
            "plan": "trial",
        },
        {
            "user_id": "U007",
            "registered_at": "2026-02-05T17:00:00+03:00",
            "country": "RU",
            "plan": "premium",
        },
        {
            "user_id": "U008",
            "registered_at": "2026-02-10T09:00:00+01:00",
            "country": "FR",
            "plan": "basic",
        },
    ],
}


def iso_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sample_users(count: int) -> Iterator[dict[str, str]]:
    base = datetime(2025, 1, 1, tzinfo=UTC)
    countries = ("RU", "KZ", "US", "DE", "FR", "")
    plans = ("basic", "premium", "trial")
    for index in range(1, count + 1):
        registered_at = base + timedelta(days=index % 365, minutes=(index * 13) % 1440)
        yield {
            "user_id": f"U{index:06d}",
            "registered_at": iso_timestamp(registered_at),
            "country": countries[index % len(countries)],
            "plan": plans[index % len(plans)],
        }


def sample_orders(user_count: int, orders_per_user: int) -> Iterator[dict[str, str]]:
    base = datetime(2025, 1, 8, tzinfo=UTC)
    currencies = ("RUB", "KZT", "USD", "EUR")
    for index in range(1, user_count * orders_per_user + 1):
        user_index = ((index * 37) % user_count) + 1
        status = "paid"
        if index % 37 == 0:
            status = "cancelled"
        elif index % 20 == 0:
            status = "pending"
        elif index % 10 == 0:
            status = "refunded"
        amount = "" if status in {"cancelled", "pending"} else f"{35 + index % 170}.00"
        ordered_at = base + timedelta(days=index % 450, minutes=(index * 17) % 1440)
        yield {
            "order_id": f"O{index:07d}",
            "user_id": "U999999" if index % 25_000 == 0 else f"U{user_index:06d}",
            "ordered_at": "" if index % 33_333 == 0 else iso_timestamp(ordered_at),
            "status": status,
            "currency": currencies[index % len(currencies)],
            "amount": amount,
        }


def sample_order_items(order_count: int) -> Iterator[dict[str, str]]:
    categories = ("subscription", "add-on", "service")
    for order_index in range(1, order_count + 1):
        total = 35 + order_index % 170
        first_price = total - 10
        for item_index, price in ((1, first_price), (2, 10)):
            yield {
                "order_id": f"O{order_index:07d}",
                "product_id": f"P{item_index:02d}",
                "category": categories[(order_index + item_index) % len(categories)],
                "quantity": "1",
                "unit_price": f"{price}.00",
            }


def sample_events(user_count: int, events_per_user: int) -> Iterator[dict[str, str]]:
    base = datetime(2025, 1, 1, tzinfo=UTC)
    event_names = ("app_open", "catalog_view", "checkout_started", "order_paid")
    event_index = 0
    for user_index in range(1, user_count + 1):
        for sequence in range(events_per_user):
            event_index += 1
            row = {
                "event_id": f"E{event_index:08d}",
                "user_id": f"U{user_index:06d}",
                "occurred_at": iso_timestamp(
                    base
                    + timedelta(
                        days=(user_index + sequence * 30) % 500,
                        minutes=(event_index * 19) % 1440,
                    )
                ),
                "event_name": event_names[sequence % len(event_names)],
                "session_id": "" if event_index % 23 == 0 else f"S{user_index:06d}-{sequence:02d}",
            }
            yield row
            if user_index % 5_000 == 0 and sequence == events_per_user - 1:
                yield row.copy()


def write_table(path: Path, rows: Iterable[dict[str, str]]) -> int:
    iterator = iter(rows)
    try:
        first = next(iterator)
    except StopIteration as error:
        raise ValueError(f"Cannot write empty table: {path.name}") from error

    count = 1
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(first), lineterminator="\n")
        writer.writeheader()
        writer.writerow(first)
        for row in iterator:
            writer.writerow(row)
            count += 1
    return count


def table_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(
    output_dir: Path,
    profile: str,
    *,
    sample_user_count: int = SAMPLE_USERS,
    sample_orders_per_user: int = SAMPLE_ORDERS_PER_USER,
    sample_events_per_user: int = SAMPLE_EVENTS_PER_USER,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "version": "1.0.0",
        "generated_by": "generate_data.py",
        "profile": profile,
        "files": {},
    }

    if profile == "tiny":
        tables: dict[str, Iterable[dict[str, str]]] = TINY_TABLES
    elif profile == "sample":
        order_count = sample_user_count * sample_orders_per_user
        tables = {
            "events.csv": sample_events(sample_user_count, sample_events_per_user),
            "order_items.csv": sample_order_items(order_count),
            "orders.csv": sample_orders(sample_user_count, sample_orders_per_user),
            "users.csv": sample_users(sample_user_count),
        }
        manifest["parameters"] = {
            "users": sample_user_count,
            "orders_per_user": sample_orders_per_user,
            "events_per_user": sample_events_per_user,
        }
    else:
        raise ValueError(f"Unsupported profile: {profile}")

    for filename in sorted(tables):
        path = output_dir / filename
        row_count = write_table(path, tables[filename])
        manifest["files"][filename] = {
            "rows": row_count,
            "sha256": table_sha256(path),
        }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic SQL course data")
    parser.add_argument("--profile", choices=("tiny", "sample"), default="tiny")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sample-users", type=int, default=SAMPLE_USERS)
    parser.add_argument("--orders-per-user", type=int, default=SAMPLE_ORDERS_PER_USER)
    parser.add_argument("--events-per-user", type=int, default=SAMPLE_EVENTS_PER_USER)
    args = parser.parse_args()

    if min(args.sample_users, args.orders_per_user, args.events_per_user) <= 0:
        parser.error("sample sizes must be positive")
    output = args.output or Path(__file__).parent / args.profile
    manifest = generate(
        output,
        args.profile,
        sample_user_count=args.sample_users,
        sample_orders_per_user=args.orders_per_user,
        sample_events_per_user=args.events_per_user,
    )
    row_count = sum(file["rows"] for file in manifest["files"].values())
    print(f"Generated {len(manifest['files'])} tables and {row_count} rows in {output}")


if __name__ == "__main__":
    main()
