from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
QUERY_PATH = ROOT / "outputs" / "null_policy_audit.sql"
CONTRACT_PATH = ROOT / "outputs" / "null_policy_contract.json"
DATA_PATH = ROOT.parent / "data" / "tiny" / "orders.csv"


MANUAL_EXPECTED = [
    {
        "order_id": "O1001",
        "amount": "1200.00",
        "amount_above_threshold": True,
        "amount_not_above_threshold": False,
        "amount_is_missing": False,
        "amount_state": "above_threshold",
    },
    {
        "order_id": "O1002",
        "amount": "800.00",
        "amount_above_threshold": True,
        "amount_not_above_threshold": False,
        "amount_is_missing": False,
        "amount_state": "above_threshold",
    },
    {
        "order_id": "O1003",
        "amount": "75.00",
        "amount_above_threshold": False,
        "amount_not_above_threshold": True,
        "amount_is_missing": False,
        "amount_state": "at_or_below_threshold",
    },
    {
        "order_id": "O1004",
        "amount": None,
        "amount_above_threshold": None,
        "amount_not_above_threshold": None,
        "amount_is_missing": True,
        "amount_state": "missing",
    },
    {
        "order_id": "O1005",
        "amount": "1500.00",
        "amount_above_threshold": True,
        "amount_not_above_threshold": False,
        "amount_is_missing": False,
        "amount_state": "above_threshold",
    },
    {
        "order_id": "O1006",
        "amount": "25.00",
        "amount_above_threshold": False,
        "amount_not_above_threshold": True,
        "amount_is_missing": False,
        "amount_state": "at_or_below_threshold",
    },
    {
        "order_id": "O1007",
        "amount": "500.00",
        "amount_above_threshold": True,
        "amount_not_above_threshold": False,
        "amount_is_missing": False,
        "amount_state": "above_threshold",
    },
    {
        "order_id": "O1008",
        "amount": None,
        "amount_above_threshold": None,
        "amount_not_above_threshold": None,
        "amount_is_missing": True,
        "amount_state": "missing",
    },
    {
        "order_id": "O1009",
        "amount": "900.00",
        "amount_above_threshold": True,
        "amount_not_above_threshold": False,
        "amount_is_missing": False,
        "amount_state": "above_threshold",
    },
    {
        "order_id": "O1010",
        "amount": "60.00",
        "amount_above_threshold": False,
        "amount_not_above_threshold": True,
        "amount_is_missing": False,
        "amount_state": "at_or_below_threshold",
    },
    {
        "order_id": "O1011",
        "amount": "45.00",
        "amount_above_threshold": False,
        "amount_not_above_threshold": True,
        "amount_is_missing": False,
        "amount_state": "at_or_below_threshold",
    },
    {
        "order_id": "O1012",
        "amount": "700.00",
        "amount_above_threshold": True,
        "amount_not_above_threshold": False,
        "amount_is_missing": False,
        "amount_state": "above_threshold",
    },
]


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_orders(
    connection: duckdb.DuckDBPyConnection,
    orders_path: Path = DATA_PATH,
) -> None:
    """Prepare the typed fixture; CSV ingestion and Python DB API are not lesson outcomes."""
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
    grain = contract["input"]["grain"]
    rows = connection.execute("SELECT order_id FROM orders").fetchall()
    order_ids = [row[0] for row in rows]
    if any(order_id is None for order_id in order_ids):
        raise ValueError(f"input grain {grain} contains NULL")
    if len(order_ids) != len(set(order_ids)):
        raise ValueError(f"input grain violation for {grain}")


def execute_audit(
    connection: duckdb.DuckDBPyConnection,
    query_path: Path = QUERY_PATH,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    relation = connection.execute(query_path.read_text(encoding="utf-8"))
    columns = [item[0] for item in relation.description]
    types = [str(item[1]) for item in relation.description]
    return columns, types, relation.fetchall()


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

    grain = contract["output"]["grain"]
    grain_positions = [columns.index(column) for column in grain]
    grain_values = [tuple(row[position] for position in grain_positions) for row in rows]
    if len(grain_values) != len(set(grain_values)):
        raise ValueError(f"output grain violation for {grain}")

    order_id_position = columns.index("order_id")
    if rows != sorted(rows, key=lambda row: row[order_id_position]):
        raise ValueError("output order does not match order_id ASC")

    threshold = Decimal(contract["policy"]["threshold"])
    states = contract["policy"]["states"]
    positions = {column: columns.index(column) for column in columns}
    for row in rows:
        amount = row[positions["amount"]]
        above = row[positions["amount_above_threshold"]]
        not_above = row[positions["amount_not_above_threshold"]]
        is_missing = row[positions["amount_is_missing"]]
        state = row[positions["amount_state"]]

        if amount is None:
            if (above, not_above, is_missing, state) != (
                None,
                None,
                True,
                states["missing"],
            ):
                raise ValueError("missing amount lost UNKNOWN or explicit missing state")
            continue

        expected_above = amount > threshold
        expected_state = states["above"] if expected_above else states["not_above"]
        if (above, not_above, is_missing, state) != (
            expected_above,
            not expected_above,
            False,
            expected_state,
        ):
            raise ValueError("known amount does not match threshold policy")


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


def state_order_ids(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    states = sorted({str(row["amount_state"]) for row in rows})
    return {
        state: [
            str(row["order_id"])
            for row in rows
            if row["amount_state"] == state
        ]
        for state in states
    }


def run_example(orders_path: Path = DATA_PATH) -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        prepare_orders(connection, orders_path)
        contract = load_contract()
        validate_input(connection, contract)
        columns, types, rows = execute_audit(connection)
    finally:
        connection.close()

    validate_result(columns, types, rows, contract)
    actual = rows_as_dicts(columns, rows)
    return {
        "manual_expected": MANUAL_EXPECTED,
        "sql_result": actual,
        "state_order_ids": state_order_ids(actual),
        "contract": contract["output"],
        "matches_manual": actual == MANUAL_EXPECTED,
    }


def main() -> None:
    print(json.dumps(run_example(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
