from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT.parent / "data" / "tiny" / "orders.csv"
MODEL_SQL_PATH = ROOT / "outputs" / "order_time_model.sql"
EXPERIMENT_SQL_PATH = ROOT / "outputs" / "temporal_semantics_experiment.sql"

EXPECTED_MODEL_COLUMNS = [
    "order_id",
    "source_timestamp",
    "timestamp_status",
    "ordered_at_instant",
    "business_timezone",
    "business_local_time",
    "business_date",
    "business_month",
]
EXPECTED_MODEL_TYPES = [
    "VARCHAR",
    "VARCHAR",
    "VARCHAR",
    "TIMESTAMP WITH TIME ZONE",
    "VARCHAR",
    "TIMESTAMP",
    "DATE",
    "DATE",
]


def prepare_orders_source(
    connection: duckdb.DuckDBPyConnection,
    orders_path: Path = DATA_PATH,
) -> None:
    """Load the raw strings; file ingestion is infrastructure, not the SQL artifact."""
    connection.execute(
        """
        CREATE OR REPLACE TABLE orders_source AS
        SELECT
            CAST(order_id AS VARCHAR) AS order_id,
            CAST(ordered_at AS VARCHAR) AS ordered_at
        FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        """,
        [str(orders_path)],
    )


def validate_source(connection: duckdb.DuckDBPyConnection) -> None:
    schema = {
        row[0]: str(row[1]) for row in connection.execute("DESCRIBE orders_source").fetchall()
    }
    expected = {"order_id": "VARCHAR", "ordered_at": "VARCHAR"}
    if schema != expected:
        raise ValueError(f"orders_source schema must be {expected}, got {schema}")

    missing_id = connection.execute(
        """
        SELECT count(*)
        FROM orders_source
        WHERE order_id IS NULL OR trim(order_id) = ''
        """
    ).fetchone()[0]
    if missing_id:
        raise ValueError("orders_source.order_id must be populated")

    duplicate_id = connection.execute(
        """
        SELECT order_id
        FROM orders_source
        GROUP BY order_id
        HAVING count(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate_id is not None:
        raise ValueError(f"orders_source grain violation for order_id: {duplicate_id[0]}")


def execute_sql(
    connection: duckdb.DuckDBPyConnection,
    query_path: Path,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    relation = connection.execute(query_path.read_text(encoding="utf-8"))
    columns = [description[0] for description in relation.description]
    types = [str(description[1]) for description in relation.description]
    return columns, types, relation.fetchall()


def execute_time_model(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    return execute_sql(connection, MODEL_SQL_PATH)


def execute_temporal_experiment(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    return execute_sql(connection, EXPERIMENT_SQL_PATH)


def validate_time_model(
    columns: list[str],
    types: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    if columns != EXPECTED_MODEL_COLUMNS:
        raise ValueError(f"time model columns must be {EXPECTED_MODEL_COLUMNS}, got {columns}")
    if types != EXPECTED_MODEL_TYPES:
        raise ValueError(f"time model types must be {EXPECTED_MODEL_TYPES}, got {types}")

    order_id_at = columns.index("order_id")
    if len(rows) != 12 or len({row[order_id_at] for row in rows}) != len(rows):
        raise ValueError("time model must preserve twelve unique order_id rows")

    status_at = columns.index("timestamp_status")
    statuses = [row[status_at] for row in rows]
    if statuses.count("valid") != 11 or statuses.count("missing") != 1:
        raise ValueError("reference data must contain eleven valid and one missing timestamp")

    instant_at = columns.index("ordered_at_instant")
    local_at = columns.index("business_local_time")
    date_at = columns.index("business_date")
    month_at = columns.index("business_month")
    for row in rows:
        temporal_values = (row[instant_at], row[local_at], row[date_at], row[month_at])
        if row[status_at] == "valid" and any(value is None for value in temporal_values):
            raise ValueError("valid timestamps must produce every typed temporal field")
        if row[status_at] != "valid" and any(value is not None for value in temporal_values):
            raise ValueError("missing or invalid timestamps must keep temporal fields NULL")


def main() -> None:
    connection = duckdb.connect()
    try:
        connection.execute("SET TimeZone = 'UTC'")
        prepare_orders_source(connection)
        validate_source(connection)
        columns, types, rows = execute_time_model(connection)
        validate_time_model(columns, types, rows)
        experiment_columns, experiment_types, experiment_rows = execute_temporal_experiment(
            connection
        )
    finally:
        connection.close()

    report = {
        "model": {
            "columns": columns,
            "types": types,
            "rows": [dict(zip(columns, row, strict=True)) for row in rows],
        },
        "duration_vs_calendar": {
            "columns": experiment_columns,
            "types": experiment_types,
            "row": dict(zip(experiment_columns, experiment_rows[0], strict=True)),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
