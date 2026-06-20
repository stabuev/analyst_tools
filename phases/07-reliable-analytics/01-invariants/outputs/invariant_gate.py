from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = (
    "order_id",
    "user_id",
    "ordered_at",
    "status",
    "currency",
    "amount_rub",
)
ALLOWED_STATUSES = {"paid", "refunded", "cancelled", "pending"}


class InvariantInputError(ValueError):
    """Raised when an order source cannot be read as a table."""


def load_orders(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    source_path = Path(path)
    if not source_path.is_file():
        raise InvariantInputError(f"input file does not exist: {source_path}")
    with source_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise InvariantInputError("input CSV must contain a header")
        return list(reader), list(reader.fieldnames)


def check(
    check_id: str,
    *,
    valid: bool,
    expected: Any,
    observed: Any,
    sample: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": valid,
        "expected": expected,
        "observed": observed,
        "sample": sample or [],
    }


def parse_amount(value: Any) -> Decimal:
    text = str(value).strip()
    try:
        amount = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("not a decimal") from error
    if not amount.is_finite():
        raise ValueError("amount is not finite")
    if amount < 0:
        raise ValueError("amount is negative")
    if amount.as_tuple().exponent < -2:
        raise ValueError("amount has more than two fractional digits")
    return amount


def parse_timestamp(value: Any) -> datetime:
    text = str(value).strip()
    try:
        timestamp = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError("timestamp is not ISO 8601") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp has no timezone offset")
    return timestamp


def money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def production_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(rows)
    frame["amount_kopecks"] = frame["amount"].map(lambda value: int(value * 100))
    paid = frame.loc[frame["status"].eq("paid")]
    status_counts = {
        str(status): int(count)
        for status, count in frame.groupby("status", sort=True).size().items()
    }
    return {
        "order_count": int(len(frame)),
        "paid_order_count": int(len(paid)),
        "total_amount_kopecks": int(frame["amount_kopecks"].sum()),
        "paid_revenue_kopecks": int(paid["amount_kopecks"].sum()),
        "status_counts": status_counts,
    }


def control_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(row["status"] for row in rows)
    total = sum((row["amount"] for row in rows), start=Decimal("0"))
    paid = [row for row in rows if row["status"] == "paid"]
    paid_revenue = sum((row["amount"] for row in paid), start=Decimal("0"))
    return {
        "order_count": len(rows),
        "paid_order_count": len(paid),
        "total_amount_kopecks": int(total * 100),
        "paid_revenue_kopecks": int(paid_revenue * 100),
        "status_counts": dict(sorted(status_counts.items())),
    }


def summary_checks(
    primary: dict[str, Any],
    control: dict[str, Any],
) -> list[dict[str, Any]]:
    order_count = primary["order_count"]
    paid_count = primary["paid_order_count"]
    status_total = sum(primary["status_counts"].values())
    return [
        check(
            "order_count_reconciles",
            valid=order_count == control["order_count"],
            expected=control["order_count"],
            observed=order_count,
        ),
        check(
            "status_partition_reconciles",
            valid=status_total == order_count,
            expected=order_count,
            observed=status_total,
        ),
        check(
            "paid_order_count_bounds",
            valid=0 <= paid_count <= order_count,
            expected=f"0 <= paid_order_count <= {order_count}",
            observed=paid_count,
        ),
        check(
            "total_amount_reconciles",
            valid=primary["total_amount_kopecks"] == control["total_amount_kopecks"],
            expected=control["total_amount_kopecks"],
            observed=primary["total_amount_kopecks"],
        ),
        check(
            "paid_revenue_reconciles",
            valid=primary["paid_revenue_kopecks"] == control["paid_revenue_kopecks"],
            expected=control["paid_revenue_kopecks"],
            observed=primary["paid_revenue_kopecks"],
        ),
    ]


def evaluate_orders(
    rows: list[dict[str, Any]],
    fieldnames: list[str] | None = None,
) -> dict[str, Any]:
    columns = (
        list(fieldnames)
        if fieldnames is not None
        else sorted({str(column) for row in rows for column in row})
    )
    missing_columns = [column for column in REQUIRED_COLUMNS if column not in columns]
    checks = [
        check(
            "required_columns",
            valid=not missing_columns,
            expected=list(REQUIRED_COLUMNS),
            observed=columns,
            sample=missing_columns,
        ),
        check(
            "non_empty_batch",
            valid=bool(rows),
            expected="at least one row",
            observed=len(rows),
        ),
    ]
    if missing_columns or not rows:
        return {
            "valid": False,
            "checks": checks,
            "summary": None,
            "control_summary": None,
        }

    blank_keys: list[int] = []
    invalid_statuses: list[dict[str, Any]] = []
    invalid_currencies: list[dict[str, Any]] = []
    invalid_amounts: list[dict[str, Any]] = []
    invalid_timestamps: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    identifiers: list[str] = []

    for row_number, row in enumerate(rows, start=2):
        order_id = str(row.get("order_id", "")).strip()
        user_id = str(row.get("user_id", "")).strip()
        if not order_id or not user_id:
            blank_keys.append(row_number)
        if order_id:
            identifiers.append(order_id)

        status = str(row.get("status", "")).strip().lower()
        if status not in ALLOWED_STATUSES:
            invalid_statuses.append({"row": row_number, "value": status})

        currency = str(row.get("currency", "")).strip().upper()
        if currency != "RUB":
            invalid_currencies.append({"row": row_number, "value": currency})

        amount: Decimal | None = None
        try:
            amount = parse_amount(row.get("amount_rub", ""))
        except ValueError as error:
            invalid_amounts.append(
                {"row": row_number, "value": str(row.get("amount_rub", "")), "reason": str(error)}
            )

        timestamp: datetime | None = None
        try:
            timestamp = parse_timestamp(row.get("ordered_at", ""))
        except ValueError as error:
            invalid_timestamps.append(
                {"row": row_number, "value": str(row.get("ordered_at", "")), "reason": str(error)}
            )

        if (
            order_id
            and user_id
            and status in ALLOWED_STATUSES
            and currency == "RUB"
            and amount is not None
            and timestamp is not None
        ):
            normalized.append(
                {
                    "order_id": order_id,
                    "user_id": user_id,
                    "ordered_at": timestamp,
                    "status": status,
                    "currency": currency,
                    "amount": amount,
                }
            )

    identifier_counts = Counter(identifiers)
    duplicate_ids = sorted(
        identifier for identifier, count in identifier_counts.items() if count > 1
    )
    checks.extend(
        [
            check(
                "keys_not_blank",
                valid=not blank_keys,
                expected="non-empty order_id and user_id",
                observed=len(blank_keys),
                sample=blank_keys[:5],
            ),
            check(
                "order_id_unique",
                valid=not duplicate_ids,
                expected="one row per order_id",
                observed=len(duplicate_ids),
                sample=duplicate_ids[:5],
            ),
            check(
                "status_domain",
                valid=not invalid_statuses,
                expected=sorted(ALLOWED_STATUSES),
                observed=len(invalid_statuses),
                sample=invalid_statuses[:5],
            ),
            check(
                "currency_domain",
                valid=not invalid_currencies,
                expected=["RUB"],
                observed=len(invalid_currencies),
                sample=invalid_currencies[:5],
            ),
            check(
                "amount_domain",
                valid=not invalid_amounts,
                expected="finite non-negative decimal with at most two fractional digits",
                observed=len(invalid_amounts),
                sample=invalid_amounts[:5],
            ),
            check(
                "timestamp_timezone",
                valid=not invalid_timestamps,
                expected="ISO 8601 timestamp with timezone offset",
                observed=len(invalid_timestamps),
                sample=invalid_timestamps[:5],
            ),
        ]
    )
    if not all(item["valid"] for item in checks):
        return {
            "valid": False,
            "checks": checks,
            "summary": None,
            "control_summary": None,
        }

    primary = production_summary(normalized)
    control = control_summary(normalized)
    checks.extend(summary_checks(primary, control))
    return {
        "valid": all(item["valid"] for item in checks),
        "checks": checks,
        "summary": {
            "order_count": primary["order_count"],
            "paid_order_count": primary["paid_order_count"],
            "total_amount_rub": money(Decimal(primary["total_amount_kopecks"]) / 100),
            "paid_revenue_rub": money(Decimal(primary["paid_revenue_kopecks"]) / 100),
            "status_counts": primary["status_counts"],
        },
        "control_summary": {
            "order_count": control["order_count"],
            "paid_order_count": control["paid_order_count"],
            "total_amount_rub": money(Decimal(control["total_amount_kopecks"]) / 100),
            "paid_revenue_rub": money(Decimal(control["paid_revenue_kopecks"]) / 100),
            "status_counts": control["status_counts"],
        },
    }


def write_report(report: dict[str, Any], output: str | Path | None) -> None:
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output is not None:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    print(text, end="")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check invariants of an order batch")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()
    try:
        rows, fieldnames = load_orders(args.input)
        report = evaluate_orders(rows, fieldnames)
        write_report(report, args.output)
    except InvariantInputError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    if not report["valid"] and not args.allow_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
