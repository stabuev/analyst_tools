from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal


def average(values: Iterable[Decimal]) -> Decimal:
    collected = list(values)
    if not collected:
        raise ValueError("values must not be empty")
    return sum(collected, start=Decimal("0")) / len(collected)


def build_report(amounts: Iterable[Decimal]) -> dict[str, int | Decimal]:
    collected = list(amounts)
    return {
        "rows": len(collected),
        "average": average(collected),
    }
