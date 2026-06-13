from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

PIPELINE_SQL = """
WITH
raw_orders AS (
    SELECT *
    FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
),
typed_orders AS (
    SELECT
        order_id,
        user_id,
        ordered_at::TIMESTAMPTZ AS ordered_at,
        lower(trim(status)) AS status,
        upper(trim(currency)) AS currency,
        amount::DECIMAL(18, 2) AS amount
    FROM raw_orders
),
paid_orders AS (
    SELECT *
    FROM typed_orders
    WHERE status = 'paid'
),
raw_items AS (
    SELECT *
    FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
),
item_totals AS (
    SELECT
        order_id,
        count(*) AS item_rows,
        sum(quantity::INTEGER * unit_price::DECIMAL(18, 2)) AS item_total
    FROM raw_items
    GROUP BY order_id
),
final AS (
    SELECT
        paid_orders.order_id,
        paid_orders.user_id,
        paid_orders.currency,
        paid_orders.amount,
        item_totals.item_rows,
        item_totals.item_total
    FROM paid_orders
    LEFT JOIN item_totals USING (order_id)
)
SELECT
    (SELECT count(*) FROM raw_orders) AS raw_order_rows,
    (SELECT count(*) FROM typed_orders) AS typed_order_rows,
    (SELECT count(*) FROM paid_orders) AS paid_order_rows,
    (SELECT count(*) FROM item_totals) AS item_total_rows,
    (SELECT count(*) FROM final) AS final_rows,
    (SELECT count(*) FROM (
        SELECT order_id FROM final GROUP BY order_id HAVING count(*) > 1
    )) AS duplicate_final_keys,
    (SELECT count(*) FROM final WHERE item_total IS NULL) AS missing_item_totals,
    (SELECT sum(amount) FROM final) AS paid_revenue,
    (SELECT count(*) FROM final WHERE abs(amount - item_total) > 0.0001)
        AS amount_item_mismatches
"""


def _number(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def run_pipeline(orders_path: Path, items_path: Path) -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        relation = connection.execute(
            PIPELINE_SQL,
            [str(orders_path), str(items_path)],
        )
        columns = [column[0] for column in relation.description]
        row = relation.fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("pipeline returned no audit row")
    stages = {column: _number(value) for column, value in zip(columns, row, strict=True)}
    checks = {
        "typing_preserves_rows": stages["raw_order_rows"] == stages["typed_order_rows"],
        "final_matches_paid_grain": stages["paid_order_rows"] == stages["final_rows"],
        "final_key_unique": stages["duplicate_final_keys"] == 0,
        "all_paid_orders_have_items": stages["missing_item_totals"] == 0,
        "amounts_reconcile": stages["amount_item_mismatches"] == 0,
    }
    return {"stages": stages, "checks": checks, "valid": all(checks.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a checked CTE SQL pipeline")
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_pipeline(args.orders, args.items)
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
