from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Mapping


class DataContractError(ValueError):
    """Raised when an input row violates the order data contract."""


@dataclass(frozen=True)
class Order:
    order_id: str
    amount: Decimal


def parse_orders(rows: Iterable[Mapping[str, str]]) -> list[Order]:
    orders: list[Order] = []
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        order_id = (row.get("order_id") or "").strip()
        raw_amount = (row.get("amount") or "").strip()
        if not order_id:
            raise DataContractError(f"row {row_number}: order_id is empty")
        if order_id in seen_ids:
            raise DataContractError(f"row {row_number}: duplicate order_id {order_id}")
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation as error:
            raise DataContractError(
                f"row {row_number}: amount is not a decimal number"
            ) from error
        if not amount.is_finite() or amount < 0:
            raise DataContractError(
                f"row {row_number}: amount must be a finite non-negative number"
            )
        seen_ids.add(order_id)
        orders.append(Order(order_id=order_id, amount=amount))
    if not orders:
        raise DataContractError("input contains no orders")
    return orders


def load_orders(path: Path) -> list[Order]:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise DataContractError(f"input file does not exist: {source}")
    try:
        with source.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise DataContractError("input has no CSV header")
            required = {"order_id", "amount"}
            missing = required - set(reader.fieldnames)
            if missing:
                raise DataContractError(
                    "missing CSV columns: " + ", ".join(sorted(missing))
                )
            return parse_orders(reader)
    except UnicodeDecodeError as error:
        raise DataContractError("input must be UTF-8 encoded") from error


def summarize_orders(orders: Iterable[Order]) -> dict[str, int | Decimal]:
    values = list(orders)
    if not values:
        raise DataContractError("cannot summarize an empty order collection")
    revenue = sum((order.amount for order in values), start=Decimal("0"))
    return {
        "orders": len(values),
        "revenue": revenue,
        "average_order_value": revenue / len(values),
    }
