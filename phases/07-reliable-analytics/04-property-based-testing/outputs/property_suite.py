from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from hypothesis import find, given, settings
from hypothesis import strategies as st

STATUSES = ("paid", "refunded", "cancelled", "pending")
ORDER_ROWS = st.lists(
    st.tuples(st.sampled_from(STATUSES), st.integers(min_value=0, max_value=10_000_000)),
    max_size=50,
)
EVENT_ROWS = st.lists(
    st.tuples(
        st.integers(min_value=1, max_value=8),
        st.integers(min_value=1, max_value=20),
        st.integers(min_value=0, max_value=100_000),
    ),
    max_size=80,
)
PROPERTY_SETTINGS = settings(max_examples=100, derandomize=True, database=None)


def paid_revenue_kopecks(rows: list[tuple[str, int]]) -> int:
    return sum(amount for status, amount in rows if status == "paid")


def deduplicate_latest(rows: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    latest: dict[int, tuple[int, int, int]] = {}
    for order_id, sequence, amount in rows:
        current = latest.get(order_id)
        candidate = (order_id, sequence, amount)
        if current is None or (sequence, amount) > (current[1], current[2]):
            latest[order_id] = candidate
    return [latest[order_id] for order_id in sorted(latest)]


@PROPERTY_SETTINGS
@given(ORDER_ROWS)
def property_paid_revenue_matches_partition(rows: list[tuple[str, int]]) -> None:
    expected = sum(amount for status, amount in rows if status == "paid")
    assert paid_revenue_kopecks(rows) == expected


@PROPERTY_SETTINGS
@given(ORDER_ROWS)
def property_aggregation_is_order_invariant(rows: list[tuple[str, int]]) -> None:
    assert paid_revenue_kopecks(rows) == paid_revenue_kopecks(list(reversed(rows)))


@PROPERTY_SETTINGS
@given(EVENT_ROWS)
def property_deduplication_is_idempotent(rows: list[tuple[int, int, int]]) -> None:
    once = deduplicate_latest(rows)
    assert deduplicate_latest(once) == once


@PROPERTY_SETTINGS
@given(EVENT_ROWS)
def property_deduplication_preserves_latest_sequence(
    rows: list[tuple[int, int, int]],
) -> None:
    result = deduplicate_latest(rows)
    for order_id, sequence, _ in result:
        assert sequence == max(row[1] for row in rows if row[0] == order_id)


def buggy_rounded_total(amounts_kopecks: list[int]) -> int:
    return sum(round(amount / 100) * 100 for amount in amounts_kopecks)


def minimal_rounding_counterexample() -> list[int]:
    amounts = st.lists(st.integers(min_value=1, max_value=999), min_size=1, max_size=5)
    return find(
        amounts,
        lambda values: buggy_rounded_total(values) != sum(values),
        settings=settings(max_examples=500, derandomize=True, database=None),
    )


PROPERTIES: list[tuple[str, Callable[[], None]]] = [
    ("paid_revenue_matches_partition", property_paid_revenue_matches_partition),
    ("aggregation_is_order_invariant", property_aggregation_is_order_invariant),
    ("deduplication_is_idempotent", property_deduplication_is_idempotent),
    ("deduplication_preserves_latest_sequence", property_deduplication_preserves_latest_sequence),
]


def run_suite() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for property_id, property_check in PROPERTIES:
        try:
            property_check()
        except AssertionError as error:
            results.append({"id": property_id, "passed": False, "error": str(error)})
        else:
            results.append({"id": property_id, "passed": True, "examples": 100})
    counterexample = minimal_rounding_counterexample()
    return {
        "valid": all(result["passed"] for result in results),
        "properties": results,
        "shrunk_counterexample": {
            "bug": "round_each_amount_before_sum",
            "amounts_kopecks": counterexample,
            "expected": sum(counterexample),
            "observed": buggy_rounded_total(counterexample),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic analytical properties")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = run_suite()
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
