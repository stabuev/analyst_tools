from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb


def normalize_order_times(
    orders_path: Path,
    business_timezone: str = "Europe/Moscow",
) -> dict[str, Any]:
    query = """
        WITH orders AS (
            SELECT
                order_id,
                ordered_at,
                ordered_at::TIMESTAMPTZ AS ordered_at_instant
            FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        )
        SELECT
            order_id,
            ordered_at AS source_timestamp,
            strftime(
                timezone('UTC', ordered_at_instant),
                '%Y-%m-%dT%H:%M:%SZ'
            ) AS ordered_at_utc,
            strftime(
                timezone(?, ordered_at_instant),
                '%Y-%m-%d %H:%M:%S'
            ) AS business_local_time,
            cast(timezone(?, ordered_at_instant) AS DATE)::VARCHAR AS business_date,
            strftime(
                date_trunc('month', timezone(?, ordered_at_instant)),
                '%Y-%m-01'
            ) AS business_month
        FROM orders
        ORDER BY order_id
    """
    connection = duckdb.connect()
    try:
        relation = connection.execute(
            query,
            [
                str(orders_path),
                business_timezone,
                business_timezone,
                business_timezone,
            ],
        )
        columns = [column[0] for column in relation.description]
        rows = [dict(zip(columns, row, strict=True)) for row in relation.fetchall()]
    finally:
        connection.close()
    month_counts = Counter(
        row["business_month"] for row in rows if row["business_month"] is not None
    )
    return {
        "business_timezone": business_timezone,
        "grain": ["order_id"],
        "rows": rows,
        "summary": {
            "source_rows": len(rows),
            "parsed_timestamps": sum(row["ordered_at_utc"] is not None for row in rows),
            "missing_timestamps": sum(row["ordered_at_utc"] is None for row in rows),
            "orders_by_business_month": dict(sorted(month_counts.items())),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize SQL timestamps and periods")
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--business-timezone", default="Europe/Moscow")
    args = parser.parse_args()
    try:
        report = normalize_order_times(args.orders, args.business_timezone)
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
