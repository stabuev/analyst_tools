from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb


def _value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def frame_demo() -> list[dict[str, Any]]:
    query = """
        WITH events(row_id, sort_key, amount) AS (
            VALUES (1, 1, 10), (2, 1, 20), (3, 2, 5)
        )
        SELECT
            row_id,
            sort_key,
            amount,
            sum(amount) OVER (
                ORDER BY sort_key
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS rows_sum,
            sum(amount) OVER (
                ORDER BY sort_key
                RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS range_sum
        FROM events
        ORDER BY row_id
    """
    relation = duckdb.sql(query)
    columns = [column[0] for column in relation.description]
    return [dict(zip(columns, row, strict=True)) for row in relation.fetchall()]


def build_window_metrics(orders_path: Path) -> dict[str, Any]:
    query = """
        WITH paid_orders AS (
            SELECT
                order_id,
                user_id,
                ordered_at::TIMESTAMPTZ AS ordered_at,
                amount::DECIMAL(18, 2) AS amount
            FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
            WHERE lower(trim(status)) = 'paid'
        )
        SELECT
            order_id,
            user_id,
            row_number() OVER user_order AS order_number,
            rank() OVER user_order AS order_rank,
            lag(amount) OVER user_order AS previous_amount,
            amount,
            sum(amount) OVER (
                PARTITION BY user_id
                ORDER BY ordered_at, order_id
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS cumulative_amount
        FROM paid_orders
        WINDOW user_order AS (
            PARTITION BY user_id
            ORDER BY ordered_at, order_id
        )
        ORDER BY user_id, order_number
    """
    connection = duckdb.connect()
    try:
        relation = connection.execute(query, [str(orders_path)])
        columns = [column[0] for column in relation.description]
        rows = [
            {column: _value(value) for column, value in zip(columns, row, strict=True)}
            for row in relation.fetchall()
        ]
    finally:
        connection.close()
    return {
        "grain": ["order_id"],
        "rows": rows,
        "frame_demo": frame_demo(),
        "checks": {
            "row_count": len(rows),
            "order_id_unique": len({row["order_id"] for row in rows}) == len(rows),
            "explicit_rows_frame": "ROWS BETWEEN" in query,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build checked SQL window metrics")
    parser.add_argument("--orders", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_window_metrics(args.orders)
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
