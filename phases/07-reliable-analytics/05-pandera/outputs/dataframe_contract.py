from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import pandera.pandas as pa

CONTRACT_VERSION = "1.0.0"
STATUSES = {"paid", "refunded", "cancelled", "pending"}
PLANS = {"trial", "basic", "premium"}


def valid_money(value: Any) -> bool:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return False
    return amount.is_finite() and amount >= 0 and amount.as_tuple().exponent >= -2


def positive_integer(value: Any) -> bool:
    try:
        return int(str(value)) > 0 and str(value).strip() == str(int(str(value)))
    except ValueError:
        return False


def timezone_aware_iso(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


USERS_SCHEMA = pa.DataFrameSchema(
    {
        "user_id": pa.Column(str, nullable=False, unique=True),
        "registered_at": pa.Column(
            str, nullable=False, checks=pa.Check(timezone_aware_iso, element_wise=True)
        ),
        "country": pa.Column(str, nullable=False, checks=pa.Check.str_length(2, 2)),
        "plan": pa.Column(str, nullable=False, checks=pa.Check.isin(PLANS)),
    },
    strict=True,
    coerce=True,
    name="users",
)

ORDERS_SCHEMA = pa.DataFrameSchema(
    {
        "order_id": pa.Column(str, nullable=False, unique=True),
        "user_id": pa.Column(str, nullable=False),
        "ordered_at": pa.Column(
            str, nullable=False, checks=pa.Check(timezone_aware_iso, element_wise=True)
        ),
        "status": pa.Column(str, nullable=False, checks=pa.Check.isin(STATUSES)),
        "currency": pa.Column(str, nullable=False, checks=pa.Check.eq("RUB")),
        "amount_rub": pa.Column(
            str, nullable=False, checks=pa.Check(valid_money, element_wise=True)
        ),
    },
    strict=True,
    coerce=True,
    name="orders",
)

ITEMS_SCHEMA = pa.DataFrameSchema(
    {
        "order_id": pa.Column(str, nullable=False),
        "line_number": pa.Column(
            str, nullable=False, checks=pa.Check(positive_integer, element_wise=True)
        ),
        "product_id": pa.Column(str, nullable=False),
        "quantity": pa.Column(
            str, nullable=False, checks=pa.Check(positive_integer, element_wise=True)
        ),
        "unit_price_rub": pa.Column(
            str, nullable=False, checks=pa.Check(valid_money, element_wise=True)
        ),
    },
    checks=pa.Check(
        lambda frame: ~frame[["order_id", "line_number"]].duplicated(),
        error="order_id,line_number must be unique",
    ),
    strict=True,
    coerce=True,
    name="order_items",
)

SCHEMAS = {"users": USERS_SCHEMA, "orders": ORDERS_SCHEMA, "order_items": ITEMS_SCHEMA}


def normalize_failure_cases(error: pa.errors.SchemaErrors) -> list[dict[str, Any]]:
    columns = ["schema_context", "column", "check", "failure_case", "index"]
    records: list[dict[str, Any]] = []
    for raw in error.failure_cases.to_dict(orient="records"):
        records.append(
            {
                column: None if pd.isna(raw.get(column)) else str(raw.get(column))
                for column in columns
            }
        )
    return records


def relation_checks(frames: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    users = frames["users"]
    orders = frames["orders"]
    items = frames["order_items"]
    checks: list[dict[str, Any]] = []
    if {"user_id"}.issubset(users) and {"user_id"}.issubset(orders):
        unknown_users = sorted(set(orders["user_id"].dropna()) - set(users["user_id"].dropna()))
        checks.append(
            {
                "id": "orders.user_fk",
                "passed": not unknown_users,
                "failure_cases": unknown_users,
            }
        )
    if {"order_id"}.issubset(orders) and {"order_id"}.issubset(items):
        unknown_orders = sorted(set(items["order_id"].dropna()) - set(orders["order_id"].dropna()))
        checks.append(
            {
                "id": "order_items.order_fk",
                "passed": not unknown_orders,
                "failure_cases": unknown_orders,
            }
        )
    required_orders = {"order_id", "amount_rub"}
    required_items = {"order_id", "quantity", "unit_price_rub"}
    if required_orders.issubset(orders) and required_items.issubset(items):
        try:
            totals: dict[str, Decimal] = {}
            for row in items.to_dict(orient="records"):
                totals.setdefault(str(row["order_id"]), Decimal("0"))
                totals[str(row["order_id"])] += Decimal(str(row["quantity"])) * Decimal(
                    str(row["unit_price_rub"])
                )
            mismatches = [
                str(row["order_id"])
                for row in orders.to_dict(orient="records")
                if valid_money(row["amount_rub"])
                and totals.get(str(row["order_id"]), Decimal("0"))
                != Decimal(str(row["amount_rub"]))
            ]
        except (InvalidOperation, ValueError):
            mismatches = ["unparseable item total"]
        checks.append(
            {
                "id": "orders.items_reconcile",
                "passed": not mismatches,
                "failure_cases": mismatches,
            }
        )
    return checks


def validate_frames(frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    schema_results: list[dict[str, Any]] = []
    validated: dict[str, pd.DataFrame] = {}
    for name, schema in SCHEMAS.items():
        try:
            validated[name] = schema.validate(frames[name], lazy=True)
        except pa.errors.SchemaErrors as error:
            schema_results.append(
                {
                    "id": f"schema.{name}",
                    "passed": False,
                    "failure_cases": normalize_failure_cases(error),
                }
            )
            validated[name] = frames[name]
        else:
            schema_results.append({"id": f"schema.{name}", "passed": True, "failure_cases": []})
    relations = relation_checks(validated)
    checks = schema_results + relations
    return {
        "contract_version": CONTRACT_VERSION,
        "valid": all(check["passed"] for check in checks),
        "checks": checks,
        "row_counts": {name: len(frame) for name, frame in frames.items()},
    }


def load_frames(data_dir: str | Path) -> dict[str, pd.DataFrame]:
    root = Path(data_dir)
    return {
        name: pd.read_csv(root / f"{name}.csv", dtype=str)
        for name in ("users", "orders", "order_items")
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate versioned DataFrame contracts")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = validate_frames(load_frames(args.data_dir))
    except (OSError, KeyError) as error:
        report = {"contract_version": CONTRACT_VERSION, "valid": False, "error": str(error)}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
