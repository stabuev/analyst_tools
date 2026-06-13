from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb


def _number(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def audit_join(users_path: Path, orders_path: Path, items_path: Path) -> dict[str, Any]:
    query = """
        WITH
        users AS (
            SELECT * FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        ),
        orders AS (
            SELECT
                order_id,
                user_id,
                lower(trim(status)) AS status,
                amount::DECIMAL(18, 2) AS amount
            FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        ),
        items AS (
            SELECT
                order_id,
                product_id,
                quantity::INTEGER AS quantity,
                unit_price::DECIMAL(18, 2) AS unit_price
            FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        ),
        item_totals AS (
            SELECT
                order_id,
                count(*) AS item_rows,
                sum(quantity * unit_price) AS item_total
            FROM items
            GROUP BY order_id
        ),
        safe_mart AS (
            SELECT
                orders.order_id,
                orders.user_id,
                orders.status,
                orders.amount,
                item_totals.item_rows,
                item_totals.item_total,
                users.user_id IS NOT NULL AS user_found
            FROM orders
            LEFT JOIN item_totals USING (order_id)
            LEFT JOIN users USING (user_id)
        ),
        naive AS (
            SELECT
                sum(orders.amount) FILTER (WHERE orders.status = 'paid') AS revenue,
                count(*) AS rows
            FROM orders
            JOIN items USING (order_id)
        )
        SELECT
            (SELECT count(*) FROM orders) AS order_rows,
            (SELECT count(*) FROM safe_mart) AS safe_rows,
            (SELECT rows FROM naive) AS naive_rows,
            (SELECT revenue FROM naive) AS naive_paid_revenue,
            (SELECT sum(amount) FILTER (WHERE status = 'paid') FROM safe_mart)
                AS safe_paid_revenue,
            (SELECT count(*) FROM safe_mart WHERE NOT user_found) AS unmatched_user_orders,
            (SELECT count(*) FROM safe_mart WHERE item_rows > 1) AS multi_item_orders,
            (SELECT count(*) FROM safe_mart WHERE abs(amount - item_total) > 0.0001)
                AS amount_item_mismatches
    """
    connection = duckdb.connect()
    try:
        relation = connection.execute(
            query,
            [str(users_path), str(orders_path), str(items_path)],
        )
        columns = [column[0] for column in relation.description]
        row = relation.fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("join audit returned no row")
    metrics = {column: _number(value) for column, value in zip(columns, row, strict=True)}
    metrics["fanout_extra_revenue"] = round(
        metrics["naive_paid_revenue"] - metrics["safe_paid_revenue"],
        2,
    )
    return {
        "expected_cardinality": {
            "orders_to_items": "one-to-many",
            "orders_to_item_totals": "one-to-one",
            "orders_to_users": "many-to-one",
        },
        "metrics": metrics,
        "checks": {
            "safe_grain_preserved": metrics["safe_rows"] == metrics["order_rows"],
            "fanout_detected": metrics["naive_rows"] > metrics["order_rows"],
            "safe_revenue": metrics["safe_paid_revenue"] == 5005.0,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit JOIN cardinality and metric fanout")
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit_join(args.users, args.orders, args.items)
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
