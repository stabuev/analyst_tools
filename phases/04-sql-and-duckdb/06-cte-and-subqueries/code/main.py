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
PIPELINE_PATH = ROOT / "outputs" / "checked_order_pipeline.sql"
SUBQUERY_AUDIT_PATH = ROOT / "outputs" / "subquery_audit.sql"
FINAL_MARKER = "-- FINAL RESULT"

EXPECTED_FINAL_COLUMNS = [
    "currency",
    "paid_order_rows",
    "paid_known_amount_rows",
    "paid_missing_amount_rows",
    "known_paid_amount",
    "orders_without_items",
    "orphan_user_orders",
    "amount_mismatch_orders",
    "incomplete_item_total_orders",
]
EXPECTED_FINAL_TYPES = [
    "VARCHAR",
    "BIGINT",
    "BIGINT",
    "BIGINT",
    "DECIMAL(38,2)",
    "BIGINT",
    "BIGINT",
    "BIGINT",
    "BIGINT",
]


def prepare_relations(
    connection: duckdb.DuckDBPyConnection,
    users_path: Path = USERS_PATH,
    orders_path: Path = ORDERS_PATH,
    items_path: Path = ITEMS_PATH,
) -> None:
    """Prepare typed fixtures; loading CSV is test infrastructure, not the artifact."""
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
    return {row[0]: str(row[1]) for row in connection.execute(f"DESCRIBE {relation}").fetchall()}


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
            raise ValueError(f"{relation}.{column} must be {expected_type}, got {actual[column]}")


def _validate_grain(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    key: tuple[str, ...],
) -> None:
    key_sql = ", ".join(key)
    missing_condition = " OR ".join(f"{column} IS NULL OR trim({column}) = ''" for column in key)
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
    _require_columns(connection, "users", {"user_id": "VARCHAR"})
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


def read_pipeline(query_path: Path = PIPELINE_PATH) -> str:
    query = query_path.read_text(encoding="utf-8")
    if query.count(FINAL_MARKER) != 1:
        raise ValueError(f"pipeline must contain exactly one {FINAL_MARKER!r} marker")
    return query


def _with_clause(query: str) -> str:
    return query.split(FINAL_MARKER, maxsplit=1)[0].rstrip()


def execute_stage(
    connection: duckdb.DuckDBPyConnection,
    stage: str,
    *,
    order_by: str,
    query: str | None = None,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    allowed_stages = {
        "item_totals",
        "safe_order_mart",
        "paid_order_mart",
        "currency_summary",
    }
    if stage not in allowed_stages:
        raise ValueError(f"unknown pipeline stage: {stage}")
    pipeline = query or read_pipeline()
    relation = connection.execute(
        f"{_with_clause(pipeline)}\nSELECT * FROM {stage} ORDER BY {order_by}"
    )
    columns = [column[0] for column in relation.description]
    types = [str(column[1]) for column in relation.description]
    return columns, types, relation.fetchall()


def execute_pipeline(
    connection: duckdb.DuckDBPyConnection,
    query: str | None = None,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    relation = connection.execute(query or read_pipeline())
    columns = [column[0] for column in relation.description]
    types = [str(column[1]) for column in relation.description]
    return columns, types, relation.fetchall()


def validate_pipeline(
    connection: duckdb.DuckDBPyConnection,
    columns: list[str],
    types: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    if columns != EXPECTED_FINAL_COLUMNS:
        raise ValueError(f"pipeline columns must be {EXPECTED_FINAL_COLUMNS}, got {columns}")
    if types != EXPECTED_FINAL_TYPES:
        raise ValueError(f"pipeline types must be {EXPECTED_FINAL_TYPES}, got {types}")

    stage_contracts = {
        "item_totals": ("order_id", 12, 12),
        "safe_order_mart": ("order_id", 12, 12),
        "paid_order_mart": ("order_id", 9, 9),
        "currency_summary": ("currency", 4, 4),
    }
    for stage, (key, expected_rows, expected_keys) in stage_contracts.items():
        stage_columns, _, stage_rows = execute_stage(
            connection,
            stage,
            order_by=key,
        )
        key_position = stage_columns.index(key)
        keys = [row[key_position] for row in stage_rows]
        if len(stage_rows) != expected_rows or len(set(keys)) != expected_keys:
            raise ValueError(
                f"{stage} must have {expected_rows} rows and {expected_keys} unique {key}"
            )

    currencies = [row[0] for row in rows]
    if currencies != sorted(currencies) or len(currencies) != len(set(currencies)):
        raise ValueError("final result must have one ordered row per currency")


def execute_subquery_audit(
    connection: duckdb.DuckDBPyConnection,
    query_path: Path = SUBQUERY_AUDIT_PATH,
) -> dict[str, Any]:
    relation = connection.execute(query_path.read_text(encoding="utf-8"))
    columns = [column[0] for column in relation.description]
    row = relation.fetchone()
    return dict(zip(columns, row, strict=True))


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value


def run_example() -> dict[str, Any]:
    with duckdb.connect() as connection:
        prepare_relations(connection)
        validate_input(connection)
        columns, types, rows = execute_pipeline(connection)
        validate_pipeline(connection, columns, types, rows)
        stage_counts = {}
        for stage, key in (
            ("item_totals", "order_id"),
            ("safe_order_mart", "order_id"),
            ("paid_order_mart", "order_id"),
            ("currency_summary", "currency"),
        ):
            _, _, stage_rows = execute_stage(
                connection,
                stage,
                order_by=key,
            )
            stage_counts[stage] = len(stage_rows)
        return {
            "stage_rows": stage_counts,
            "subquery_audit": execute_subquery_audit(connection),
            "currency_summary": [
                {column: _json_value(value) for column, value in zip(columns, row, strict=True)}
                for row in rows
            ],
        }


def main() -> None:
    print(json.dumps(run_example(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
