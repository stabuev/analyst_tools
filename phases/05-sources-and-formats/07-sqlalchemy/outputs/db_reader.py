from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, bindparam, create_engine, inspect, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError


class DatabaseReadError(RuntimeError):
    """Raised when a database slice cannot be read or validated."""


def load_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path)
    if not contract_path.is_file():
        raise DatabaseReadError(f"contract file does not exist: {contract_path}")
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DatabaseReadError(f"invalid contract JSON: {error.msg}") from error
    required = {"result_columns", "grain", "allowed_statuses"}
    missing = required - set(contract)
    if missing:
        raise DatabaseReadError(f"contract misses fields: {sorted(missing)}")
    return contract


def database_url(database: str | Path) -> str | URL:
    value = str(database)
    if "://" in value:
        return value
    path = Path(value).resolve()
    if not path.is_file():
        raise DatabaseReadError(f"database file does not exist: {path}")
    return URL.create("sqlite", database=str(path))


def read_orders(
    database: str | Path,
    contract_path: str | Path,
    *,
    min_amount: float = 0.0,
    status: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    if limit <= 0:
        raise DatabaseReadError("limit must be positive")
    contract = load_contract(contract_path)
    engine = create_engine(database_url(database))
    try:
        metadata = MetaData()
        orders = Table("orders", metadata, autoload_with=engine)
        users = Table("users", metadata, autoload_with=engine)
        statement = (
            select(
                orders.c.order_id,
                orders.c.user_id,
                orders.c.ordered_at,
                orders.c.amount,
                orders.c.status,
                users.c.segment,
            )
            .join(users, orders.c.user_id == users.c.user_id)
            .where(orders.c.amount >= bindparam("min_amount"))
            .order_by(orders.c.order_id)
            .limit(bindparam("row_limit"))
        )
        params: dict[str, Any] = {"min_amount": min_amount, "row_limit": limit}
        if status is not None:
            statement = statement.where(orders.c.status == bindparam("status"))
            params["status"] = status
        compiled = statement.compile(engine)
        with engine.connect() as connection:
            rows = [dict(row) for row in connection.execute(statement, params).mappings()]
        schema = {
            table: [
                {
                    "name": column["name"],
                    "type": str(column["type"]),
                    "nullable": column["nullable"],
                }
                for column in inspect(engine).get_columns(table)
            ]
            for table in ("orders", "users")
        }
    except SQLAlchemyError as error:
        raise DatabaseReadError(f"database query failed: {error}") from error
    finally:
        engine.dispose()

    columns = list(rows[0]) if rows else contract["result_columns"]
    ids = [row["order_id"] for row in rows]
    checks = {
        "columns_match": columns == contract["result_columns"],
        "grain_unique": len(ids) == len(set(ids)),
        "statuses_allowed": all(row["status"] in contract["allowed_statuses"] for row in rows),
        "row_limit_respected": len(rows) <= limit,
    }
    return {
        "query": {
            "sql": str(compiled),
            "bind_names": sorted(params),
            "literal_values_embedded": any(
                str(value) in str(compiled) for value in params.values()
            ),
        },
        "parameters": params,
        "schema": schema,
        "result": {"grain": contract["grain"], "columns": columns, "rows": rows},
        "checks": checks,
        "summary": {
            "valid": all(checks.values())
            and not any(str(value) in str(compiled) for value in params.values()),
            "row_count": len(rows),
        },
    }


def json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"cannot serialize {type(value).__name__}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read a parameterized order slice")
    parser.add_argument("--database", required=True)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "db_contract.json",
    )
    parser.add_argument("--min-amount", type=float, default=0.0)
    parser.add_argument("--status")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    try:
        result = read_orders(
            args.database,
            args.contract,
            min_amount=args.min_amount,
            status=args.status,
            limit=args.limit,
        )
    except DatabaseReadError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, default=json_default)
    sys.stdout.write("\n")
    if not result["summary"]["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
