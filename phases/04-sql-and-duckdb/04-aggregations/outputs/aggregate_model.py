from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb


def _json_value(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def build_aggregates(orders_path: Path) -> dict[str, Any]:
    query = """
        WITH orders AS (
            SELECT
                upper(trim(currency)) AS currency,
                lower(trim(status)) AS status,
                amount::DECIMAL(18, 2) AS amount
            FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        )
        SELECT
            currency,
            count(*) AS order_rows,
            count(amount) AS known_amount_rows,
            sum(amount) FILTER (WHERE status = 'paid') AS paid_revenue,
            count(*) FILTER (WHERE status = 'paid') AS paid_orders,
            avg(amount) FILTER (WHERE status = 'paid') AS average_paid_amount
        FROM orders
        GROUP BY currency
        ORDER BY currency
    """
    connection = duckdb.connect()
    try:
        relation = connection.execute(query, [str(orders_path)])
        columns = [column[0] for column in relation.description]
        rows = [
            {column: _json_value(value) for column, value in zip(columns, row, strict=True)}
            for row in relation.fetchall()
        ]
    finally:
        connection.close()

    paid_total = sum(row["paid_revenue"] or 0 for row in rows)
    return {
        "grain": ["currency"],
        "rows": rows,
        "checks": {
            "grain_unique": len({row["currency"] for row in rows}) == len(rows),
            "paid_revenue_total": round(paid_total, 2),
            "source_rows": sum(row["order_rows"] for row in rows),
            "known_amount_rows": sum(row["known_amount_rows"] for row in rows),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build checked SQL aggregates by currency")
    parser.add_argument("--orders", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build_aggregates(args.orders)
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
