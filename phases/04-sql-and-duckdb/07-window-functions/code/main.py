from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT.parent / "data" / "tiny" / "orders.csv"
SEQUENCE_SQL_PATH = ROOT / "outputs" / "order_sequence_windows.sql"
LATEST_SQL_PATH = ROOT / "outputs" / "latest_paid_order_per_user.sql"
CANONICAL_ORDER_STATUSES = ("cancelled", "paid", "pending", "refunded")

EXPECTED_SEQUENCE_COLUMNS = [
    "order_id",
    "user_id",
    "ordered_at",
    "currency",
    "amount",
    "user_order_number",
    "latest_order_number",
    "amount_rank_in_currency",
    "amount_dense_rank_in_currency",
    "previous_order_id",
    "previous_currency",
    "previous_amount",
    "next_order_id",
]
EXPECTED_SEQUENCE_TYPES = [
    "VARCHAR",
    "VARCHAR",
    "TIMESTAMP WITH TIME ZONE",
    "VARCHAR",
    "DECIMAL(18,2)",
    "BIGINT",
    "BIGINT",
    "BIGINT",
    "BIGINT",
    "VARCHAR",
    "VARCHAR",
    "DECIMAL(18,2)",
    "VARCHAR",
]


def prepare_orders(
    connection: duckdb.DuckDBPyConnection,
    orders_path: Path = DATA_PATH,
) -> None:
    """Prepare a typed fixture; CSV loading is test infrastructure, not the artifact."""
    connection.execute(
        """
        CREATE OR REPLACE TABLE orders AS
        SELECT
            CAST(order_id AS VARCHAR) AS order_id,
            CAST(user_id AS VARCHAR) AS user_id,
            CAST(ordered_at AS TIMESTAMPTZ) AS ordered_at,
            CAST(status AS VARCHAR) AS status,
            CAST(currency AS VARCHAR) AS currency,
            CAST(amount AS DECIMAL(18, 2)) AS amount
        FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        """,
        [str(orders_path)],
    )


def _schema(connection: duckdb.DuckDBPyConnection, relation: str) -> dict[str, str]:
    return {
        row[0]: str(row[1])
        for row in connection.execute(f"DESCRIBE {relation}").fetchall()
    }


def _require_columns(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    required: dict[str, str],
) -> None:
    actual = _schema(connection, relation)
    for column, expected_type in required.items():
        if column not in actual:
            raise ValueError(f"{relation} is missing required column {column}")
        if actual[column] != expected_type:
            raise ValueError(
                f"{relation}.{column} must be {expected_type}, got {actual[column]}"
            )


def _require_populated_text(
    connection: duckdb.DuckDBPyConnection,
    column: str,
    *,
    where: str = "TRUE",
) -> None:
    missing = connection.execute(
        f"""
        SELECT count(*)
        FROM orders
        WHERE ({where})
          AND ({column} IS NULL OR trim({column}) = '')
        """
    ).fetchone()[0]
    if missing:
        raise ValueError(
            f"orders.{column} contains {missing} NULL or blank values where {where}"
        )


def validate_input(connection: duckdb.DuckDBPyConnection) -> None:
    _require_columns(
        connection,
        "orders",
        {
            "order_id": "VARCHAR",
            "user_id": "VARCHAR",
            "ordered_at": "TIMESTAMP WITH TIME ZONE",
            "status": "VARCHAR",
            "currency": "VARCHAR",
            "amount": "DECIMAL(18,2)",
        },
    )

    _require_populated_text(connection, "order_id")
    _require_populated_text(connection, "status")

    placeholders = ", ".join("?" for _ in CANONICAL_ORDER_STATUSES)
    unknown_statuses = [
        row[0]
        for row in connection.execute(
            f"""
            SELECT DISTINCT status
            FROM orders
            WHERE status NOT IN ({placeholders})
            ORDER BY status
            """,
            list(CANONICAL_ORDER_STATUSES),
        ).fetchall()
    ]
    if unknown_statuses:
        raise ValueError(
            "orders.status must use canonical values "
            f"{CANONICAL_ORDER_STATUSES}, got {unknown_statuses}"
        )

    duplicate = connection.execute(
        """
        SELECT order_id
        FROM orders
        GROUP BY order_id
        HAVING count(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate is not None:
        raise ValueError(f"orders grain violation for order_id: {duplicate[0]}")

    _require_populated_text(connection, "user_id", where="status = 'paid'")
    _require_populated_text(connection, "currency", where="status = 'paid'")

    missing_ordered_at = connection.execute(
        """
        SELECT count(*)
        FROM orders
        WHERE status = 'paid' AND ordered_at IS NULL
        """
    ).fetchone()[0]
    if missing_ordered_at:
        raise ValueError(
            "paid orders require ordered_at before a chronological window can be built"
        )


def execute_sql(
    connection: duckdb.DuckDBPyConnection,
    query_path: Path,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    relation = connection.execute(query_path.read_text(encoding="utf-8"))
    columns = [column[0] for column in relation.description]
    types = [str(column[1]) for column in relation.description]
    return columns, types, relation.fetchall()


def execute_sequence(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    return execute_sql(connection, SEQUENCE_SQL_PATH)


def execute_latest(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    return execute_sql(connection, LATEST_SQL_PATH)


def validate_sequence(
    columns: list[str],
    types: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    if columns != EXPECTED_SEQUENCE_COLUMNS:
        raise ValueError(
            f"sequence columns must be {EXPECTED_SEQUENCE_COLUMNS}, got {columns}"
        )
    if types != EXPECTED_SEQUENCE_TYPES:
        raise ValueError(
            f"sequence types must be {EXPECTED_SEQUENCE_TYPES}, got {types}"
        )

    order_id_at = columns.index("order_id")
    user_id_at = columns.index("user_id")
    user_number_at = columns.index("user_order_number")
    latest_number_at = columns.index("latest_order_number")
    previous_order_at = columns.index("previous_order_id")
    next_order_at = columns.index("next_order_id")

    order_ids = [row[order_id_at] for row in rows]
    if len(order_ids) != len(set(order_ids)):
        raise ValueError("sequence result changed the one-row-per-order_id grain")

    users: dict[str, list[tuple[Any, ...]]] = {}
    for row in rows:
        users.setdefault(row[user_id_at], []).append(row)

    for user_id, user_rows in users.items():
        count = len(user_rows)
        actual_forward = [row[user_number_at] for row in user_rows]
        if actual_forward != list(range(1, count + 1)):
            raise ValueError(f"user {user_id} has a broken chronological sequence")
        actual_reverse = [row[latest_number_at] for row in user_rows]
        if actual_reverse != list(range(count, 0, -1)):
            raise ValueError(f"user {user_id} has a broken reverse sequence")

        for position, row in enumerate(user_rows):
            expected_previous = (
                None if position == 0 else user_rows[position - 1][order_id_at]
            )
            expected_next = (
                None
                if position == count - 1
                else user_rows[position + 1][order_id_at]
            )
            if row[previous_order_at] != expected_previous:
                raise ValueError(f"user {user_id} has an incorrect previous_order_id")
            if row[next_order_at] != expected_next:
                raise ValueError(f"user {user_id} has an incorrect next_order_id")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def run_example() -> dict[str, Any]:
    with duckdb.connect() as connection:
        prepare_orders(connection)
        validate_input(connection)
        columns, types, rows = execute_sequence(connection)
        validate_sequence(columns, types, rows)
        latest_columns, _, latest_rows = execute_latest(connection)

    return {
        "grain": ["order_id"],
        "population": "orders where status = 'paid'",
        "columns": columns,
        "rows": [
            {
                column: _json_value(value)
                for column, value in zip(columns, row, strict=True)
            }
            for row in rows
        ],
        "latest_paid_orders": [
            {
                column: _json_value(value)
                for column, value in zip(latest_columns, row, strict=True)
            }
            for row in latest_rows
        ],
    }


def main() -> None:
    print(json.dumps(run_example(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
