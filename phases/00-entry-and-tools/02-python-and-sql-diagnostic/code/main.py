from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def select_paid_order_ids(orders: Iterable[dict[str, object]]) -> list[int]:
    """Return paid order ids in input order without mutating the rows."""
    return [
        int(order["order_id"])
        for order in orders
        if order.get("status") == "paid"
    ]


def revenue_by_customer(orders: Iterable[dict[str, object]]) -> dict[int, float]:
    """Aggregate non-null paid revenue by customer."""
    result: dict[int, float] = {}
    for order in orders:
        amount = order.get("amount")
        if order.get("status") != "paid" or amount is None:
            continue
        customer_id = int(order["customer_id"])
        result[customer_id] = result.get(customer_id, 0.0) + float(amount)
    return {customer_id: round(revenue, 2) for customer_id, revenue in result.items()}


CUSTOMER_REVENUE_SQL = """
SELECT
    customer_id,
    ROUND(SUM(amount), 2) AS revenue
FROM orders
WHERE status = 'paid' AND amount IS NOT NULL
GROUP BY customer_id
ORDER BY customer_id
"""


CUSTOMER_ACTIVITY_SQL = """
SELECT
    customers.customer_id,
    COUNT(orders.order_id) AS paid_order_count,
    ROUND(COALESCE(SUM(orders.amount), 0), 2) AS revenue
FROM customers
LEFT JOIN orders
    ON customers.customer_id = orders.customer_id
    AND orders.status = 'paid'
    AND orders.amount IS NOT NULL
GROUP BY customers.customer_id
ORDER BY customers.customer_id
"""


def main() -> None:
    runner_path = Path(__file__).resolve().parents[1] / "outputs" / "diagnostic_runner.py"
    namespace = {"__file__": str(runner_path), "__name__": "diagnostic_runner"}
    exec(compile(runner_path.read_text(encoding="utf-8"), runner_path, "exec"), namespace)
    report = namespace["evaluate_submission"](Path(__file__))
    print(namespace["render_markdown"](report))


if __name__ == "__main__":
    main()
