from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb


def truth_table() -> list[dict[str, Any]]:
    query = """
        WITH values_table(label, value) AS (
            VALUES ('TRUE', TRUE), ('FALSE', FALSE), ('UNKNOWN', NULL::BOOLEAN)
        )
        SELECT
            left_side.label AS left_value,
            right_side.label AS right_value,
            CASE
                WHEN left_side.value AND right_side.value THEN 'TRUE'
                WHEN (left_side.value AND right_side.value) = FALSE THEN 'FALSE'
                ELSE 'UNKNOWN'
            END AS and_result,
            CASE
                WHEN left_side.value OR right_side.value THEN 'TRUE'
                WHEN (left_side.value OR right_side.value) = FALSE THEN 'FALSE'
                ELSE 'UNKNOWN'
            END AS or_result
        FROM values_table AS left_side
        CROSS JOIN values_table AS right_side
        ORDER BY left_side.label, right_side.label
    """
    connection = duckdb.connect()
    try:
        relation = connection.execute(query)
        columns = [column[0] for column in relation.description]
        return [dict(zip(columns, row, strict=True)) for row in relation.fetchall()]
    finally:
        connection.close()


def audit_null_filter(orders_path: Path, threshold: float = 100.0) -> dict[str, Any]:
    query = """
        WITH orders AS (
            SELECT amount::DOUBLE AS amount
            FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        )
        SELECT
            count(*) AS total_rows,
            count(*) FILTER (WHERE amount > ?) AS true_rows,
            count(*) FILTER (WHERE NOT (amount > ?)) AS false_rows,
            count(*) FILTER (WHERE (amount > ?) IS NULL) AS unknown_rows,
            count(*) FILTER (WHERE amount IS NULL) AS null_amount_rows,
            count(amount) AS non_null_amount_rows,
            count(coalesce(amount, 0)) AS coalesced_count
        FROM orders
    """
    connection = duckdb.connect()
    try:
        row = connection.execute(
            query,
            [str(orders_path), threshold, threshold, threshold],
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError("null audit returned no row")
    keys = [
        "total_rows",
        "true_rows",
        "false_rows",
        "unknown_rows",
        "null_amount_rows",
        "non_null_amount_rows",
        "coalesced_count",
    ]
    counts = dict(zip(keys, row, strict=True))
    counts["partition_is_complete"] = (
        counts["true_rows"] + counts["false_rows"] + counts["unknown_rows"] == counts["total_rows"]
    )
    return {"threshold": threshold, "counts": counts, "truth_table": truth_table()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Show SQL three-valued logic and NULL loss")
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=100.0)
    args = parser.parse_args()
    try:
        report = audit_null_filter(args.orders, args.threshold)
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
