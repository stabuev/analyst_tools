from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / "data" / "tiny"
USERS_PATH = DATA / "users.csv"
ORDERS_PATH = DATA / "orders.csv"
ITEMS_PATH = DATA / "order_items.csv"
ITEM_TOTALS_QUERY = ROOT / "outputs" / "item_totals.sql"
SAFE_MART_QUERY = ROOT / "outputs" / "safe_order_mart.sql"

EXPECTED_COLUMNS = [
    "order_id",
    "user_id",
    "status",
    "currency",
    "amount",
    "item_rows",
    "known_item_amount_rows",
    "item_total",
    "item_amount_complete",
    "item_match_state",
    "user_match_state",
    "amount_reconciliation_state",
]
EXPECTED_TYPES = [
    "VARCHAR",
    "VARCHAR",
    "VARCHAR",
    "VARCHAR",
    "DECIMAL(18,2)",
    "BIGINT",
    "BIGINT",
    "DECIMAL(38,2)",
    "BOOLEAN",
    "VARCHAR",
    "VARCHAR",
    "VARCHAR",
]


def prepare_relations(
    connection: duckdb.DuckDBPyConnection,
    users_path: Path = USERS_PATH,
    orders_path: Path = ORDERS_PATH,
    items_path: Path = ITEMS_PATH,
) -> None:
    """Prepare typed fixtures; CSV ingestion and Python API are not lesson outcomes."""
    connection.execute(
        """
        CREATE OR REPLACE TABLE users AS
        SELECT
            CAST(user_id AS VARCHAR) AS user_id,
            CAST(registered_at AS VARCHAR) AS registered_at,
            CAST(country AS VARCHAR) AS country,
            CAST(plan AS VARCHAR) AS plan
        FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        """,
        [str(users_path)],
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE orders AS
        SELECT
            CAST(order_id AS VARCHAR) AS order_id,
            CAST(user_id AS VARCHAR) AS user_id,
            CAST(ordered_at AS VARCHAR) AS ordered_at,
            CAST(status AS VARCHAR) AS status,
            CAST(currency AS VARCHAR) AS currency,
            CAST(amount AS DECIMAL(18, 2)) AS amount
        FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        """,
        [str(orders_path)],
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE order_items AS
        SELECT
            CAST(order_id AS VARCHAR) AS order_id,
            CAST(product_id AS VARCHAR) AS product_id,
            CAST(category AS VARCHAR) AS category,
            CAST(quantity AS INTEGER) AS quantity,
            CAST(unit_price AS DECIMAL(18, 2)) AS unit_price
        FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        """,
        [str(items_path)],
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


def _validate_grain(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    key: tuple[str, ...],
) -> None:
    key_sql = ", ".join(key)
    missing_condition = " OR ".join(
        f"{column} IS NULL OR trim({column}) = ''" for column in key
    )
    missing = connection.execute(
        f"SELECT count(*) FROM {relation} WHERE {missing_condition}"
    ).fetchone()[0]
    if missing:
        raise ValueError(f"{relation} grain {key} contains NULL or blank values")

    duplicate = connection.execute(
        f"""
        SELECT {key_sql}
        FROM {relation}
        GROUP BY {key_sql}
        HAVING count(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate is not None:
        raise ValueError(f"{relation} grain violation for {key}: {duplicate}")


def validate_input(connection: duckdb.DuckDBPyConnection) -> None:
    _require_columns(
        connection,
        "orders",
        {
            "order_id": "VARCHAR",
            "user_id": "VARCHAR",
            "status": "VARCHAR",
            "currency": "VARCHAR",
            "amount": "DECIMAL(18,2)",
        },
    )
    _require_columns(
        connection,
        "users",
        {"user_id": "VARCHAR"},
    )
    _require_columns(
        connection,
        "order_items",
        {
            "order_id": "VARCHAR",
            "product_id": "VARCHAR",
            "quantity": "INTEGER",
            "unit_price": "DECIMAL(18,2)",
        },
    )
    _validate_grain(connection, "orders", ("order_id",))
    _validate_grain(connection, "users", ("user_id",))
    _validate_grain(connection, "order_items", ("order_id", "product_id"))


def prepare_item_totals(
    connection: duckdb.DuckDBPyConnection,
    query_path: Path = ITEM_TOTALS_QUERY,
) -> None:
    """Expose the first SQL result to the second query inside the lesson runner."""
    query = query_path.read_text(encoding="utf-8").strip().removesuffix(";")
    connection.execute(f"CREATE OR REPLACE TEMP TABLE item_totals AS {query}")
    _validate_grain(connection, "item_totals", ("order_id",))


def execute_safe_mart(
    connection: duckdb.DuckDBPyConnection,
    query_path: Path = SAFE_MART_QUERY,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    relation = connection.execute(query_path.read_text(encoding="utf-8"))
    columns = [column[0] for column in relation.description]
    types = [str(column[1]) for column in relation.description]
    return columns, types, relation.fetchall()


def validate_safe_mart(
    connection: duckdb.DuckDBPyConnection,
    columns: list[str],
    types: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    if columns != EXPECTED_COLUMNS:
        raise ValueError(
            f"safe mart columns must be {EXPECTED_COLUMNS}, got {columns}"
        )
    if types != EXPECTED_TYPES:
        raise ValueError(f"safe mart types must be {EXPECTED_TYPES}, got {types}")

    positions = {column: index for index, column in enumerate(columns)}
    order_ids = [row[positions["order_id"]] for row in rows]
    source_order_ids = [
        row[0]
        for row in connection.execute(
            "SELECT order_id FROM orders ORDER BY order_id"
        ).fetchall()
    ]
    if order_ids != source_order_ids:
        raise ValueError("safe mart must preserve every order exactly once")

    allowed_item_states = {"matched", "no_items"}
    allowed_user_states = {"matched", "missing_reference", "orphan_reference"}
    allowed_amount_states = {
        "both_missing",
        "order_amount_missing",
        "item_total_missing",
        "item_total_incomplete",
        "matches",
        "differs",
    }
    for row in rows:
        if row[positions["item_match_state"]] not in allowed_item_states:
            raise ValueError("unknown item_match_state")
        if row[positions["user_match_state"]] not in allowed_user_states:
            raise ValueError("unknown user_match_state")
        if (
            row[positions["amount_reconciliation_state"]]
            not in allowed_amount_states
        ):
            raise ValueError("unknown amount_reconciliation_state")


def fanout_by_currency(
    connection: duckdb.DuckDBPyConnection,
) -> list[dict[str, Any]]:
    source_rows = connection.execute(
        """
        SELECT
            currency,
            sum(amount) FILTER (WHERE status = 'paid') AS source_paid_amount
        FROM orders
        GROUP BY currency
        ORDER BY currency ASC NULLS LAST
        """
    ).fetchall()
    naive_rows = connection.execute(
        """
        SELECT
            o.currency,
            sum(o.amount) FILTER (WHERE o.status = 'paid') AS joined_paid_amount
        FROM orders AS o
        INNER JOIN order_items AS i
            ON o.order_id = i.order_id
        GROUP BY o.currency
        ORDER BY o.currency ASC NULLS LAST
        """
    ).fetchall()
    naive_by_currency = {currency: amount for currency, amount in naive_rows}

    result = []
    for currency, source_amount in source_rows:
        joined_amount = naive_by_currency.get(currency)
        extra = (
            None
            if source_amount is None or joined_amount is None
            else joined_amount - source_amount
        )
        result.append(
            {
                "currency": currency,
                "source_paid_amount": source_amount,
                "joined_paid_amount": joined_amount,
                "fanout_extra": extra,
            }
        )
    return result


def coverage_counts(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, int]:
    return {
        "orders_with_missing_user_id": connection.execute(
            "SELECT count(*) FROM orders WHERE user_id IS NULL"
        ).fetchone()[0],
        "orders_with_orphan_user_id": connection.execute(
            """
            SELECT count(*)
            FROM orders AS o
            ANTI JOIN users AS u
                ON o.user_id = u.user_id
            WHERE o.user_id IS NOT NULL
            """
        ).fetchone()[0],
        "orders_without_items": connection.execute(
            """
            SELECT count(*)
            FROM orders AS o
            ANTI JOIN order_items AS i
                ON o.order_id = i.order_id
            """
        ).fetchone()[0],
        "item_rows_without_order": connection.execute(
            """
            SELECT count(*)
            FROM order_items AS i
            ANTI JOIN orders AS o
                ON i.order_id = o.order_id
            """
        ).fetchone()[0],
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def rows_as_dicts(
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> list[dict[str, Any]]:
    return [
        {
            column: _json_value(value)
            for column, value in zip(columns, row, strict=True)
        }
        for row in rows
    ]


def run_example(
    users_path: Path = USERS_PATH,
    orders_path: Path = ORDERS_PATH,
    items_path: Path = ITEMS_PATH,
) -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        prepare_relations(connection, users_path, orders_path, items_path)
        validate_input(connection)
        direct_join_rows = connection.execute(
            """
            SELECT count(*)
            FROM orders AS o
            INNER JOIN order_items AS i
                ON o.order_id = i.order_id
            """
        ).fetchone()[0]
        prepare_item_totals(connection)
        columns, types, rows = execute_safe_mart(connection)
        validate_safe_mart(connection, columns, types, rows)
        fanout = fanout_by_currency(connection)
        coverage = coverage_counts(connection)
    finally:
        connection.close()

    amount_state_position = columns.index("amount_reconciliation_state")
    amount_states: dict[str, int] = {}
    for row in rows:
        state = row[amount_state_position]
        amount_states[state] = amount_states.get(state, 0) + 1

    return {
        "input_grains": {
            "orders": ["order_id"],
            "order_items": ["order_id", "product_id"],
            "users": ["user_id"],
        },
        "output_grain": ["order_id"],
        "row_counts": {
            "orders": len(rows),
            "direct_orders_to_items_join": direct_join_rows,
            "safe_order_mart": len(rows),
        },
        "coverage": coverage,
        "amount_reconciliation_states": amount_states,
        "fanout_by_currency": [
            {key: _json_value(value) for key, value in row.items()}
            for row in fanout
        ],
        "safe_order_mart": rows_as_dicts(columns, rows),
    }


def main() -> None:
    print(json.dumps(run_example(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
