from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
SUPPORT_TICKETS = ROOT.parent / "data" / "tiny" / "support_tickets.csv"
SUBSCRIPTIONS = ROOT.parent / "data" / "tiny" / "subscriptions.csv"
ORDERS = ROOT.parent / "data" / "tiny" / "orders.csv"
METRIC_SPECS = ROOT.parent / "01-metric-tree" / "outputs" / "metric_specs.json"
SPEC = ROOT / "outputs" / "guardrail_spec.json"
ARTIFACT = ROOT / "outputs" / "guardrail_calculator.py"


def load_calculator():
    spec = importlib.util.spec_from_file_location("guardrail_calculator", ARTIFACT)
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


def manual_support_ticket_rate(
    users: list[dict[str, str]],
    support_tickets: list[dict[str, str]],
    timezone: ZoneInfo,
    start: str,
    end: str,
) -> dict[str, str]:
    period_users = [
        row
        for row in users
        if row["is_test_user"].lower() != "true"
        and start <= parse_timestamp(row["registered_at"]).astimezone(timezone).date().isoformat() <= end
    ]
    ticket_dates_by_user: dict[str, list[datetime.date]] = {}
    for row in support_tickets:
        ticket_dates_by_user.setdefault(row["user_id"], []).append(parse_timestamp(row["created_at"]).astimezone(timezone).date())

    numerator = 0
    for user in period_users:
        cohort_date = parse_timestamp(user["registered_at"]).astimezone(timezone).date()
        window_end = cohort_date + timedelta(days=7)
        if any(cohort_date <= ticket_date <= window_end for ticket_date in ticket_dates_by_user.get(user["user_id"], [])):
            numerator += 1
    denominator = len(period_users)
    return {
        "denominator": str(denominator),
        "numerator": str(numerator),
        "support_ticket_rate_7d": f"{numerator / denominator:.6f}" if denominator else "",
    }


def assessment_for(rows: list[dict[str, str]], metric_id: str) -> dict[str, str]:
    return next(row for row in rows if row["row_type"] == "assessment" and row["metric_id"] == metric_id)


def main() -> None:
    calculator = load_calculator()
    users, user_columns = calculator.read_csv(USERS)
    support_tickets, ticket_columns = calculator.read_csv(SUPPORT_TICKETS)
    subscriptions, subscription_columns = calculator.read_csv(SUBSCRIPTIONS)
    orders, order_columns = calculator.read_csv(ORDERS)
    metric_specs = calculator.normalize_metric_specs(calculator.read_json(METRIC_SPECS))
    guardrail_spec = calculator.normalize_spec(calculator.read_json(SPEC))
    result = calculator.calculate_guardrails(
        users,
        user_columns,
        support_tickets,
        ticket_columns,
        subscriptions,
        subscription_columns,
        orders,
        order_columns,
        metric_specs,
        guardrail_spec,
    )
    timezone = ZoneInfo(guardrail_spec["business_timezone"])
    summary = {
        "manual_support_baseline": manual_support_ticket_rate(users, support_tickets, timezone, "2026-06-01", "2026-06-03"),
        "manual_support_comparison": manual_support_ticket_rate(users, support_tickets, timezone, "2026-06-04", "2026-06-08"),
        "calculator_summary": result.report["summary"],
        "support_assessment": assessment_for(result.table, "support_ticket_rate_7d"),
        "cancel_assessment": assessment_for(result.table, "subscription_cancel_rate_14d"),
        "refund_assessment": assessment_for(result.table, "refund_rate_7d"),
        "valid": result.report["valid"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
