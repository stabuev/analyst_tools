from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
ORDERS = ROOT.parent / "data" / "tiny" / "orders.csv"
SUBSCRIPTIONS = ROOT.parent / "data" / "tiny" / "subscriptions.csv"
SPEC = ROOT / "outputs" / "monetization_spec.json"
ARTIFACT = ROOT / "outputs" / "monetization_calculator.py"


def load_calculator():
    spec = importlib.util.spec_from_file_location("monetization_calculator", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def manual_day_zero_revenue(users: list[dict[str, str]], orders: list[dict[str, str]], timezone: ZoneInfo) -> dict[str, str]:
    cohort_users = {
        row["user_id"]
        for row in users
        if row["is_test_user"].lower() != "true"
        and parse_timestamp(row["registered_at"]).astimezone(timezone).date().isoformat() == "2026-06-01"
    }
    realized = Decimal("0")
    paying_users: set[str] = set()
    for row in orders:
        if row["user_id"] not in cohort_users or row["status"] != "paid":
            continue
        order_date = parse_timestamp(row["ordered_at"]).astimezone(timezone).date().isoformat()
        if order_date == "2026-06-01":
            realized += Decimal(row["amount_rub"])
            paying_users.add(row["user_id"])
    cohort_size = len(cohort_users)
    return {
        "cohort_size": str(cohort_size),
        "paying_users": str(len(paying_users)),
        "realized_revenue_rub": f"{realized:.2f}",
        "arpu_rub": f"{realized / Decimal(cohort_size):.2f}" if cohort_size else "0.00",
    }


def row_for(rows: list[dict[str, str]], cohort_date: str, window_days: int) -> dict[str, str]:
    return next(row for row in rows if row["cohort_date"] == cohort_date and row["window_days"] == str(window_days))


def main() -> None:
    calculator = load_calculator()
    users, user_columns = calculator.read_csv(USERS)
    orders, order_columns = calculator.read_csv(ORDERS)
    subscriptions, subscription_columns = calculator.read_csv(SUBSCRIPTIONS)
    monetization_spec = calculator.normalize_spec(calculator.read_json(SPEC))
    result = calculator.calculate_monetization(
        users,
        user_columns,
        orders,
        order_columns,
        subscriptions,
        subscription_columns,
        monetization_spec,
    )
    timezone = ZoneInfo(monetization_spec["business_timezone"])
    summary = {
        "manual_2026_06_01_day_0": manual_day_zero_revenue(users, orders, timezone),
        "calculator_summary": result.report["summary"],
        "cohort_2026_06_01_day_0": row_for(result.table, "2026-06-01", 0),
        "cohort_2026_06_04_day_0_refund": row_for(result.table, "2026-06-04", 0),
        "cohort_2026_06_03_day_7_incomplete": row_for(result.table, "2026-06-03", 7),
        "valid": result.report["valid"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
