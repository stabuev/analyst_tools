from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

CHECKS = [
    (
        "users.user_id_unique",
        """
        SELECT user_id, count(*) AS occurrences
        FROM users
        GROUP BY user_id
        HAVING user_id IS NULL OR trim(user_id) = '' OR count(*) > 1
        """,
    ),
    (
        "orders.order_id_unique",
        """
        SELECT order_id, count(*) AS occurrences
        FROM orders
        GROUP BY order_id
        HAVING order_id IS NULL OR trim(order_id) = '' OR count(*) > 1
        """,
    ),
    (
        "order_items.key_unique",
        """
        SELECT order_id, line_number, count(*) AS occurrences
        FROM order_items
        GROUP BY order_id, line_number
        HAVING order_id IS NULL OR line_number IS NULL OR count(*) > 1
        """,
    ),
    (
        "orders.user_fk",
        """
        SELECT o.order_id, o.user_id
        FROM orders AS o
        LEFT JOIN users AS u USING (user_id)
        WHERE u.user_id IS NULL
        """,
    ),
    (
        "order_items.order_fk",
        """
        SELECT i.order_id, i.line_number
        FROM order_items AS i
        LEFT JOIN orders AS o USING (order_id)
        WHERE o.order_id IS NULL
        """,
    ),
    (
        "orders.status_domain",
        """
        SELECT order_id, status
        FROM orders
        WHERE status NOT IN ('paid', 'refunded', 'cancelled', 'pending') OR status IS NULL
        """,
    ),
    (
        "orders.amount_domain",
        """
        SELECT order_id, amount_rub
        FROM orders
        WHERE try_cast(amount_rub AS DECIMAL(18, 2)) IS NULL
           OR try_cast(amount_rub AS DECIMAL(18, 2)) < 0
        """,
    ),
    (
        "orders.items_reconcile",
        """
        WITH item_totals AS (
            SELECT
                order_id,
                sum(
                    try_cast(quantity AS BIGINT)
                    * try_cast(unit_price_rub AS DECIMAL(18, 2))
                ) AS item_total
            FROM order_items
            GROUP BY order_id
        )
        SELECT
            o.order_id,
            o.amount_rub AS order_total,
            coalesce(i.item_total, 0) AS item_total
        FROM orders AS o
        LEFT JOIN item_totals AS i USING (order_id)
        WHERE try_cast(o.amount_rub AS DECIMAL(18, 2)) IS DISTINCT FROM
              coalesce(i.item_total, 0)
        """,
    ),
]


def load_tables(connection: duckdb.DuckDBPyConnection, data_dir: str | Path) -> dict[str, int]:
    root = Path(data_dir)
    counts: dict[str, int] = {}
    for name in ("users", "orders", "order_items"):
        frame = pd.read_csv(root / f"{name}.csv", dtype=str)
        connection.register(name, frame)
        counts[name] = len(frame)
    return counts


def run_checks(data_dir: str | Path) -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        row_counts = load_tables(connection, data_dir)
        results: list[dict[str, Any]] = []
        for check_id, query in CHECKS:
            failures = connection.execute(query).fetchdf()
            results.append(
                {
                    "id": check_id,
                    "passed": failures.empty,
                    "violation_count": len(failures),
                    "sample": failures.head(5).to_dict(orient="records"),
                }
            )
    finally:
        connection.close()
    return {
        "valid": all(result["passed"] for result in results),
        "engine": f"duckdb-{duckdb.__version__}",
        "row_counts": row_counts,
        "checks": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run independent SQL quality checks")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run_checks(args.data_dir)
    except (OSError, duckdb.Error, ValueError) as error:
        report = {"valid": False, "error": {"class": "system_failure", "message": str(error)}}
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
