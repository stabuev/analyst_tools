from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT.parent / "data" / "tiny" / "orders.csv"
FRAMES_SQL_PATH = ROOT / "outputs" / "order_amount_frames.sql"
EXPERIMENT_SQL_PATH = ROOT / "outputs" / "frame_semantics_experiment.sql"
CANONICAL_ORDER_STATUSES = ("cancelled", "paid", "pending", "refunded")

EXPECTED_FRAME_COLUMNS = [
    "order_id",
    "user_id",
    "ordered_at",
    "currency",
    "amount",
    "currency_total_known_amount",
    "currency_running_known_amount",
    "currency_running_order_rows",
    "currency_running_known_amounts",
    "recent_3_order_rows",
    "recent_3_known_amounts",
    "recent_3_known_amount_avg",
    "prior_3_order_rows",
    "prior_3_known_amounts",
    "prior_3_known_amount_avg",
]
EXPECTED_FRAME_TYPES = [
    "VARCHAR",
    "VARCHAR",
    "TIMESTAMP WITH TIME ZONE",
    "VARCHAR",
    "DECIMAL(18,2)",
    "DECIMAL(38,2)",
    "DECIMAL(38,2)",
    "BIGINT",
    "BIGINT",
    "BIGINT",
    "BIGINT",
    "DOUBLE",
    "BIGINT",
    "BIGINT",
    "DOUBLE",
]


def prepare_orders(
    connection: duckdb.DuckDBPyConnection,
    orders_path: Path = DATA_PATH,
) -> None:
    """Prepare a typed fixture; file loading is infrastructure, not the SQL artifact."""
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
    return {row[0]: str(row[1]) for row in connection.execute(f"DESCRIBE {relation}").fetchall()}


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
        raise ValueError(f"orders.{column} contains {missing} NULL or blank values where {where}")


def validate_input(connection: duckdb.DuckDBPyConnection) -> None:
    expected_schema = {
        "order_id": "VARCHAR",
        "user_id": "VARCHAR",
        "ordered_at": "TIMESTAMP WITH TIME ZONE",
        "status": "VARCHAR",
        "currency": "VARCHAR",
        "amount": "DECIMAL(18,2)",
    }
    actual_schema = _schema(connection, "orders")
    for column, expected_type in expected_schema.items():
        actual_type = actual_schema.get(column)
        if actual_type is None:
            raise ValueError(f"orders is missing required column {column}")
        if actual_type != expected_type:
            raise ValueError(f"orders.{column} must be {expected_type}, got {actual_type}")

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
        raise ValueError("paid orders require ordered_at before an ordered frame can be built")


def execute_sql(
    connection: duckdb.DuckDBPyConnection,
    query_path: Path,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    relation = connection.execute(query_path.read_text(encoding="utf-8"))
    columns = [description[0] for description in relation.description]
    types = [str(description[1]) for description in relation.description]
    return columns, types, relation.fetchall()


def execute_frames(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    return execute_sql(connection, FRAMES_SQL_PATH)


def execute_experiment(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    return execute_sql(connection, EXPERIMENT_SQL_PATH)


def validate_frames(
    columns: list[str],
    types: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    if columns != EXPECTED_FRAME_COLUMNS:
        raise ValueError(f"frame columns must be {EXPECTED_FRAME_COLUMNS}, got {columns}")
    if types != EXPECTED_FRAME_TYPES:
        raise ValueError(f"frame types must be {EXPECTED_FRAME_TYPES}, got {types}")

    order_id_at = columns.index("order_id")
    if len(rows) != 9 or len({row[order_id_at] for row in rows}) != len(rows):
        raise ValueError("window aggregates must preserve nine unique paid order_id rows")

    total_at = columns.index("currency_total_known_amount")
    currency_at = columns.index("currency")
    totals_by_currency: dict[str, set[Decimal | None]] = {}
    for row in rows:
        totals_by_currency.setdefault(row[currency_at], set()).add(row[total_at])
    if any(len(totals) != 1 for totals in totals_by_currency.values()):
        raise ValueError("partition total must be constant inside each currency")

    for row in rows:
        recent_rows = row[columns.index("recent_3_order_rows")]
        recent_known = row[columns.index("recent_3_known_amounts")]
        recent_avg = row[columns.index("recent_3_known_amount_avg")]
        prior_rows = row[columns.index("prior_3_order_rows")]
        prior_known = row[columns.index("prior_3_known_amounts")]
        prior_avg = row[columns.index("prior_3_known_amount_avg")]

        if not 1 <= recent_rows <= 3 or not 0 <= recent_known <= recent_rows:
            raise ValueError("recent frame row and known-value counts are inconsistent")
        if not 0 <= prior_rows <= 3 or not 0 <= prior_known <= prior_rows:
            raise ValueError("prior frame row and known-value counts are inconsistent")
        if (recent_avg is None) != (recent_known == 0):
            raise ValueError("recent average must expose an empty known-value denominator")
        if (prior_avg is None) != (prior_known == 0):
            raise ValueError("prior average must expose an empty known-value denominator")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _records(
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> list[dict[str, Any]]:
    return [
        {column: _json_value(value) for column, value in zip(columns, row, strict=True)}
        for row in rows
    ]


def run_example() -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        prepare_orders(connection)
        validate_input(connection)
        frame_columns, frame_types, frame_rows = execute_frames(connection)
        validate_frames(frame_columns, frame_types, frame_rows)
        experiment_columns, _, experiment_rows = execute_experiment(connection)
    finally:
        connection.close()

    return {
        "grain": ["order_id"],
        "rows": _records(frame_columns, frame_rows),
        "frame_experiment": _records(experiment_columns, experiment_rows),
        "checks": {
            "paid_order_rows": len(frame_rows),
            "order_id_unique": True,
            "ordered_aggregates_use_explicit_frames": True,
        },
    }


def main() -> None:
    print(json.dumps(run_example(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
