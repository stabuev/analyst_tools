from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
QUERY_PATH = ROOT / "outputs" / "currency_aggregate_audit.sql"
CONTRACT_PATH = ROOT / "outputs" / "currency_aggregate_contract.json"
DATA_PATH = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_orders(
    connection: duckdb.DuckDBPyConnection,
    orders_path: Path = DATA_PATH,
) -> None:
    """Prepare the typed fixture; ingestion and Python DB API are not lesson outcomes."""
    connection.execute("DROP TABLE IF EXISTS orders")
    connection.execute(
        """
        CREATE TABLE orders AS
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


def validate_input(
    connection: duckdb.DuckDBPyConnection,
    contract: dict[str, Any],
) -> None:
    schema = {
        row[0]: str(row[1])
        for row in connection.execute("DESCRIBE orders").fetchall()
    }
    for column in contract["input"]["required_columns"]:
        name = column["name"]
        if name not in schema:
            raise ValueError(f"required input column is missing: {name}")
        if schema[name] != column["type"]:
            raise ValueError(
                f"input type mismatch for {name}: "
                f"expected {column['type']}, got {schema[name]}"
            )

    missing_or_blank = connection.execute(
        """
        SELECT count(*)
        FROM orders
        WHERE order_id IS NULL OR trim(order_id) = ''
        """
    ).fetchone()[0]
    if missing_or_blank:
        raise ValueError("input grain order_id contains NULL or blank values")

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
        raise ValueError(f"input grain violation for order_id: {duplicate[0]}")


def execute_audit(
    connection: duckdb.DuckDBPyConnection,
    query_path: Path = QUERY_PATH,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    relation = connection.execute(query_path.read_text(encoding="utf-8"))
    columns = [item[0] for item in relation.description]
    types = [str(item[1]) for item in relation.description]
    return columns, types, relation.fetchall()


def _row_positions(columns: list[str]) -> dict[str, int]:
    return {column: position for position, column in enumerate(columns)}


def validate_result(
    connection: duckdb.DuckDBPyConnection,
    columns: list[str],
    types: list[str],
    rows: list[tuple[Any, ...]],
    contract: dict[str, Any],
) -> None:
    expected_columns = [item["name"] for item in contract["output"]["columns"]]
    expected_types = [item["type"] for item in contract["output"]["columns"]]
    if columns != expected_columns:
        raise ValueError(
            f"output columns do not match contract: expected {expected_columns}, got {columns}"
        )
    if types != expected_types:
        raise ValueError(
            f"output types do not match contract: expected {expected_types}, got {types}"
        )

    positions = _row_positions(columns)
    grain = contract["output"]["grain"]
    grain_values = [
        tuple(row[positions[column]] for column in grain)
        for row in rows
    ]
    if len(grain_values) != len(set(grain_values)):
        raise ValueError(f"output grain violation for {grain}")

    currency_position = positions["currency"]
    expected_order = sorted(
        rows,
        key=lambda row: (
            row[currency_position] is None,
            "" if row[currency_position] is None else row[currency_position],
        ),
    )
    if rows != expected_order:
        raise ValueError("output order does not match currency ASC NULLS LAST")

    source_counts = connection.execute(
        """
        SELECT
            count(*) AS order_rows,
            count(amount) AS known_amount_rows,
            count(*) FILTER (WHERE status = 'paid') AS paid_order_rows,
            count(amount) FILTER (WHERE status = 'paid') AS paid_known_amount_rows
        FROM orders
        """
    ).fetchone()
    grouped_counts = (
        sum(row[positions["order_rows"]] for row in rows),
        sum(row[positions["known_amount_rows"]] for row in rows),
        sum(row[positions["paid_order_rows"]] for row in rows),
        sum(row[positions["paid_known_amount_rows"]] for row in rows),
    )
    if grouped_counts != source_counts:
        raise ValueError(
            "grouped denominators do not reconcile to the typed source: "
            f"expected {source_counts}, got {grouped_counts}"
        )

    for row in rows:
        paid_rows = row[positions["paid_order_rows"]]
        paid_known = row[positions["paid_known_amount_rows"]]
        paid_missing = row[positions["paid_missing_amount_rows"]]
        complete = row[positions["paid_amount_complete"]]
        revenue = row[positions["known_paid_revenue"]]
        average = row[positions["average_known_paid_amount"]]

        if paid_missing != paid_rows - paid_known:
            raise ValueError("paid missing-amount denominator is inconsistent")
        if complete is not (paid_missing == 0):
            raise ValueError("paid_amount_complete does not match its denominator")

        if paid_known == 0:
            if revenue is not None or average is not None:
                raise ValueError(
                    "an aggregate without known paid amounts must keep SUM and AVG NULL"
                )
            continue

        if not isinstance(revenue, Decimal):
            raise ValueError("known_paid_revenue must remain an exact DECIMAL")
        if average is None or not math.isclose(
            float(revenue),
            average * paid_known,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            raise ValueError("AVG does not reconcile to its sum and denominator")

    if contract["policies"]["money"]["cross_currency_sum_allowed"]:
        raise ValueError("the lesson contract must forbid summing different currencies")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return round(value, 6)
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


def run_example(orders_path: Path = DATA_PATH) -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        contract = load_contract()
        prepare_orders(connection, orders_path)
        validate_input(connection, contract)
        columns, types, rows = execute_audit(connection)
        validate_result(connection, columns, types, rows, contract)

        result_rows = rows_as_dicts(columns, rows)
        expected_rows = contract["expected_on_tiny"]
        if result_rows != expected_rows:
            raise ValueError(
                "SQL result does not match the independently recorded manual table"
            )

        source_counts = connection.execute(
            """
            SELECT
                count(*),
                count(amount),
                count(*) FILTER (WHERE status = 'paid'),
                count(amount) FILTER (WHERE status = 'paid')
            FROM orders
            """
        ).fetchone()
        positions = _row_positions(columns)
        grouped_counts = (
            sum(row[positions["order_rows"]] for row in rows),
            sum(row[positions["known_amount_rows"]] for row in rows),
            sum(row[positions["paid_order_rows"]] for row in rows),
            sum(row[positions["paid_known_amount_rows"]] for row in rows),
        )
    finally:
        connection.close()

    return {
        "input_grain": contract["input"]["grain"],
        "output_grain": contract["output"]["grain"],
        "rows": result_rows,
        "checks": {
            "matches_manual_table": True,
            "source_order_rows": source_counts[0],
            "grouped_order_rows": grouped_counts[0],
            "source_known_amount_rows": source_counts[1],
            "grouped_known_amount_rows": grouped_counts[1],
            "source_paid_order_rows": source_counts[2],
            "grouped_paid_order_rows": grouped_counts[2],
            "source_paid_known_amount_rows": source_counts[3],
            "grouped_paid_known_amount_rows": grouped_counts[3],
            "cross_currency_money_total_published": False,
        },
    }


def main() -> None:
    print(json.dumps(run_example(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
