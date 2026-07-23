from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
QUERY_PATH = ROOT / "outputs" / "paid_rub_orders.sql"
CONTRACT_PATH = ROOT / "outputs" / "select_result_contract.json"
DATA_PATH = ROOT.parent / "data" / "tiny" / "orders.csv"


MANUAL_EXPECTED = [
    {
        "order_id": "O1005",
        "user_id": "U001",
        "currency": "RUB",
        "amount": "1500.00",
        "amount_with_fee": "1575.00",
        "amount_band": "large",
    },
    {
        "order_id": "O1001",
        "user_id": "U001",
        "currency": "RUB",
        "amount": "1200.00",
        "amount_with_fee": "1260.00",
        "amount_band": "regular",
    },
]


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_orders(
    connection: duckdb.DuckDBPyConnection,
    orders_path: Path = DATA_PATH,
) -> None:
    """Prepare the typed lesson fixture; ingestion itself is not the lesson outcome."""
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


def execute_select(
    connection: duckdb.DuckDBPyConnection,
    query_path: Path = QUERY_PATH,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    relation = connection.execute(query_path.read_text(encoding="utf-8"))
    columns = [item[0] for item in relation.description]
    types = [str(item[1]) for item in relation.description]
    return columns, types, relation.fetchall()


def validate_input(
    connection: duckdb.DuckDBPyConnection,
    contract: dict[str, Any],
) -> None:
    rows = connection.execute(
        "SELECT order_id, status, currency, amount FROM orders"
    ).fetchall()
    order_ids = [row[0] for row in rows]
    if len(order_ids) != len(set(order_ids)):
        raise ValueError("input grain violation for ['order_id']")

    rule = contract["business_rule"]
    target_missing = [
        row[0]
        for row in rows
        if row[1] == rule["status"]
        and row[2] == rule["currency"]
        and row[3] is None
    ]
    if rule["selected_amount_required"] and target_missing:
        raise ValueError(
            "selected paid RUB orders require amount; "
            f"missing for {target_missing}"
        )


def validate_result(
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

    grain_columns = contract["output"]["grain"]
    grain_positions = [columns.index(column) for column in grain_columns]
    grain_values = [tuple(row[position] for position in grain_positions) for row in rows]
    if len(grain_values) != len(set(grain_values)):
        raise ValueError(f"output grain violation for {grain_columns}")

    amount_position = columns.index("amount")
    order_id_position = columns.index("order_id")
    expected_order = sorted(
        rows,
        key=lambda row: (-row[amount_position], row[order_id_position]),
    )
    if rows != expected_order:
        raise ValueError("output order does not match amount DESC, order_id ASC")


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


def run_example(orders_path: Path = DATA_PATH) -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        prepare_orders(connection, orders_path)
        contract = load_contract()
        validate_input(connection, contract)
        columns, types, rows = execute_select(connection)
    finally:
        connection.close()

    validate_result(columns, types, rows, contract)
    actual = rows_as_dicts(columns, rows)
    return {
        "manual_expected": MANUAL_EXPECTED,
        "sql_result": actual,
        "contract": contract["output"],
        "matches_manual": actual == MANUAL_EXPECTED,
    }


def main() -> None:
    print(json.dumps(run_example(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
