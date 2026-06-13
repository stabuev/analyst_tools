from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

RESULT_COLUMNS = [
    "order_id",
    "user_id",
    "currency",
    "amount",
    "amount_with_fee",
    "amount_band",
]


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def run_select(
    orders_path: Path,
    *,
    currency: str = "RUB",
    min_amount: Decimal = Decimal("100"),
    fee_rate: Decimal = Decimal("0.05"),
) -> dict[str, Any]:
    if min_amount < 0:
        raise ValueError("min_amount must be non-negative")
    if fee_rate < 0:
        raise ValueError("fee_rate must be non-negative")

    query = """
        SELECT
            order_id,
            user_id,
            upper(trim(currency)) AS currency,
            amount::DECIMAL(18, 2) AS amount,
            round(amount::DECIMAL(18, 2) * (1 + ?), 2) AS amount_with_fee,
            CASE
                WHEN amount::DECIMAL(18, 2) >= 1000 THEN 'large'
                ELSE 'regular'
            END AS amount_band
        FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        WHERE lower(trim(status)) = 'paid'
          AND upper(trim(currency)) = upper(?)
          AND amount::DECIMAL(18, 2) >= ?
        ORDER BY amount::DECIMAL(18, 2) DESC, order_id
    """
    connection = duckdb.connect()
    try:
        relation = connection.execute(
            query,
            [fee_rate, str(orders_path), currency, min_amount],
        )
        columns = [item[0] for item in relation.description]
        rows = [
            {column: _json_value(value) for column, value in zip(columns, row, strict=True)}
            for row in relation.fetchall()
        ]
    finally:
        connection.close()

    return {
        "contract": {
            "grain": ["order_id"],
            "columns": RESULT_COLUMNS,
            "order_by": ["amount DESC", "order_id"],
        },
        "parameters": {
            "currency": currency.upper(),
            "min_amount": float(min_amount),
            "fee_rate": float(fee_rate),
        },
        "rows": rows,
        "row_count": len(rows),
        "valid": columns == RESULT_COLUMNS and len({row["order_id"] for row in rows}) == len(rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a SELECT with a result contract")
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--currency", default="RUB")
    parser.add_argument("--min-amount", type=Decimal, default=Decimal("100"))
    parser.add_argument("--fee-rate", type=Decimal, default=Decimal("0.05"))
    args = parser.parse_args()
    try:
        report = run_select(
            args.orders,
            currency=args.currency,
            min_amount=args.min_amount,
            fee_rate=args.fee_rate,
        )
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
