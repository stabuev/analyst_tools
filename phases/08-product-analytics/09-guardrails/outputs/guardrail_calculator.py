from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REQUIRED_USER_COLUMNS = {"user_id", "registered_at", "is_test_user"}
REQUIRED_TICKET_COLUMNS = {"ticket_id", "user_id", "created_at", "category", "status"}
REQUIRED_SUBSCRIPTION_COLUMNS = {"subscription_id", "user_id", "started_at", "ended_at", "status", "plan", "price_rub"}
REQUIRED_ORDER_COLUMNS = {"order_id", "user_id", "ordered_at", "status", "currency", "amount_rub"}
REQUIRED_SPEC_FIELDS = {
    "version",
    "analysis_periods",
    "business_timezone",
    "observation_end_date",
    "exclude_test_users",
    "complete_window_policy",
    "overall_decision_rules",
    "guardrails",
}
SUPPORTED_POLICY = {"blank_metric"}
SUPPORTED_RISK_DIRECTIONS = {"up_is_bad"}
SUPPORTED_GUARDRAILS = {
    ("support_tickets", "user_id"),
    ("subscriptions", "subscription_id"),
    ("orders", "order_id"),
}
OUTPUT_COLUMNS = [
    "metric_id",
    "row_type",
    "period",
    "period_start",
    "period_end",
    "source",
    "unit",
    "window_days",
    "risk_direction",
    "denominator",
    "numerator",
    "metric_value",
    "baseline_value",
    "comparison_value",
    "absolute_delta",
    "max_rate",
    "max_delta",
    "threshold_breached",
    "decision_status",
    "is_complete_window",
    "excluded_incomplete_units",
]


class GuardrailResult:
    def __init__(self, table: list[dict[str, str]], report: dict[str, Any]) -> None:
        self.table = table
        self.report = report


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"id": check_id, "valid": True, "observed": observed, "expected": expected, "sample": []}


def failed(check_id: str, observed: Any, expected: Any, sample: list[Any] | None = None) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def normalize_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("guardrail spec must be an object")
    return value


def normalize_metric_specs(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("metrics"), list):
        raise ValueError("metric specs must be an object with a metrics list")
    return value


def parse_timestamp(value: str) -> datetime:
    if not value:
        raise ValueError("empty timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def deduplicate(rows: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        value = row.get(key, "")
        if value and value in seen:
            continue
        if value:
            seen.add(value)
        deduped.append(row)
    return deduped


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def metric_specs_by_id(metric_specs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        metric["metric_id"]: metric
        for metric in metric_specs.get("metrics", [])
        if isinstance(metric, dict) and isinstance(metric.get("metric_id"), str)
    }


def validate_periods(spec: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    periods = spec.get("analysis_periods")
    if not isinstance(periods, list) or len(periods) != 2:
        checks.append(failed("analysis_periods_valid", periods, "exactly two periods: baseline and comparison"))
        return
    period_ids = [period.get("period_id") for period in periods if isinstance(period, dict)]
    if period_ids != ["baseline", "comparison"]:
        checks.append(failed("analysis_periods_valid", period_ids, ["baseline", "comparison"]))
        return
    errors: list[dict[str, Any]] = []
    for period in periods:
        try:
            start = date.fromisoformat(str(period.get("date_from", "")))
            end = date.fromisoformat(str(period.get("date_to", "")))
        except ValueError as error:
            errors.append({"period_id": period.get("period_id"), "error": str(error)})
            continue
        if start > end:
            errors.append({"period_id": period.get("period_id"), "error": "date_from after date_to"})
    if errors:
        checks.append(failed("analysis_periods_valid", len(errors), "valid YYYY-MM-DD ranges", errors))
    else:
        checks.append(passed("analysis_periods_valid", period_ids, "baseline and comparison ranges"))


def validate_guardrails(spec: dict[str, Any], metric_specs: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    guardrails = spec.get("guardrails")
    if not isinstance(guardrails, list) or not guardrails:
        checks.append(failed("guardrails_valid", guardrails, "non-empty guardrail list"))
        return
    known_metric_specs = metric_specs_by_id(metric_specs)
    errors: list[dict[str, Any]] = []
    metric_ids: list[str] = []
    for item in guardrails:
        if not isinstance(item, dict):
            errors.append({"guardrail": item, "error": "guardrail must be object"})
            continue
        metric_id = item.get("metric_id")
        source = item.get("source")
        unit = item.get("unit")
        metric_ids.append(str(metric_id))
        if (source, unit) not in SUPPORTED_GUARDRAILS:
            errors.append({"metric_id": metric_id, "error": "unsupported source/unit pair"})
        if item.get("risk_direction") not in SUPPORTED_RISK_DIRECTIONS:
            errors.append({"metric_id": metric_id, "error": "risk_direction must be up_is_bad"})
        if not isinstance(item.get("window_days"), int) or item["window_days"] < 0:
            errors.append({"metric_id": metric_id, "error": "window_days must be a non-negative integer"})
        for threshold_field in ("max_rate", "max_delta"):
            value = item.get(threshold_field)
            if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
                errors.append({"metric_id": metric_id, "error": f"{threshold_field} must be a number between 0 and 1"})
        if item.get("metric_spec_required") is True:
            metric_spec = known_metric_specs.get(str(metric_id))
            if metric_spec is None:
                errors.append({"metric_id": metric_id, "error": "metric spec is required"})
            else:
                if metric_spec.get("role") != "guardrail":
                    errors.append({"metric_id": metric_id, "error": "metric spec role must be guardrail"})
                if metric_spec.get("expected_direction") != item.get("risk_direction"):
                    errors.append({"metric_id": metric_id, "error": "risk_direction differs from metric spec"})
    for metric_id in duplicate_values(metric_ids):
        errors.append({"metric_id": metric_id, "error": "duplicate guardrail metric_id"})
    if errors:
        checks.append(failed("guardrails_valid", len(errors), "supported guardrails with thresholds and metric spec links", errors[:10]))
    else:
        checks.append(passed("guardrails_valid", metric_ids, "supported guardrails with thresholds and metric spec links"))


def validate_spec(spec: dict[str, Any], metric_specs: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        checks.append(failed("guardrail_spec_required_fields", missing, "all required guardrail spec fields"))
    else:
        checks.append(passed("guardrail_spec_required_fields", len(REQUIRED_SPEC_FIELDS), "all required guardrail spec fields"))

    try:
        ZoneInfo(str(spec.get("business_timezone", "")))
    except ZoneInfoNotFoundError:
        checks.append(failed("business_timezone_valid", spec.get("business_timezone"), "IANA timezone name"))
    else:
        checks.append(passed("business_timezone_valid", spec.get("business_timezone"), "IANA timezone name"))

    observation_end = spec.get("observation_end_date")
    try:
        date.fromisoformat(str(observation_end))
    except ValueError:
        checks.append(failed("observation_end_date_valid", observation_end, "YYYY-MM-DD"))
    else:
        checks.append(passed("observation_end_date_valid", observation_end, "YYYY-MM-DD"))

    if spec.get("complete_window_policy") not in SUPPORTED_POLICY:
        checks.append(failed("complete_window_policy_supported", spec.get("complete_window_policy"), sorted(SUPPORTED_POLICY)))
    else:
        checks.append(passed("complete_window_policy_supported", spec.get("complete_window_policy"), sorted(SUPPORTED_POLICY)))

    validate_periods(spec, checks)
    validate_guardrails(spec, metric_specs, checks)
    return checks


def validate_columns(columns: list[str], required: set[str], check_id: str) -> dict[str, Any]:
    missing = sorted(required - set(columns))
    if missing:
        return failed(check_id, missing, "all required columns")
    return passed(check_id, len(columns), "all required columns")


def validate_timestamps(rows: list[dict[str, str]], field: str, key: str, check_id: str, required: bool = True) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):
        value = row.get(field, "")
        if not value and not required:
            continue
        try:
            parse_timestamp(value)
        except ValueError as error:
            errors.append({"row": index, key: row.get(key, ""), "field": field, "error": str(error)})
    if errors:
        return failed(check_id, len(errors), f"{field} is timezone-aware", errors[:10])
    return passed(check_id, len(rows), f"{field} is timezone-aware")


def validate_inputs(
    users: list[dict[str, str]],
    user_columns: list[str],
    support_tickets: list[dict[str, str]],
    ticket_columns: list[str],
    subscriptions: list[dict[str, str]],
    subscription_columns: list[str],
    orders: list[dict[str, str]],
    order_columns: list[str],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = [
        validate_columns(user_columns, REQUIRED_USER_COLUMNS, "user_columns_present"),
        validate_columns(ticket_columns, REQUIRED_TICKET_COLUMNS, "support_ticket_columns_present"),
        validate_columns(subscription_columns, REQUIRED_SUBSCRIPTION_COLUMNS, "subscription_columns_present"),
        validate_columns(order_columns, REQUIRED_ORDER_COLUMNS, "order_columns_present"),
    ]

    user_ids = [row.get("user_id", "") for row in users if row.get("user_id")]
    ticket_ids = [row.get("ticket_id", "") for row in support_tickets if row.get("ticket_id")]
    subscription_ids = [row.get("subscription_id", "") for row in subscriptions if row.get("subscription_id")]
    order_ids = [row.get("order_id", "") for row in orders if row.get("order_id")]
    for check_id, values, key in (
        ("user_ids_unique", user_ids, "user_id"),
        ("ticket_ids_unique", ticket_ids, "ticket_id"),
        ("subscription_ids_unique", subscription_ids, "subscription_id"),
        ("order_ids_unique", order_ids, "order_id"),
    ):
        duplicates = duplicate_values(values)
        if duplicates:
            checks.append(failed(check_id, len(duplicates), f"0 duplicate {key} values", duplicates[:10]))
        else:
            checks.append(passed(check_id, len(values), f"0 duplicate {key} values"))

    checks.append(validate_timestamps(users, "registered_at", "user_id", "registered_timestamps_valid"))
    checks.append(validate_timestamps(support_tickets, "created_at", "ticket_id", "support_ticket_timestamps_valid"))
    checks.append(validate_timestamps(subscriptions, "started_at", "subscription_id", "subscription_started_timestamps_valid"))
    checks.append(validate_timestamps(subscriptions, "ended_at", "subscription_id", "subscription_ended_timestamps_valid", required=False))
    checks.append(validate_timestamps(orders, "ordered_at", "order_id", "order_timestamps_valid"))

    known_users = set(user_ids)
    for check_id, rows, key in (
        ("support_tickets_reference_known_users", support_tickets, "ticket_id"),
        ("subscriptions_reference_known_users", subscriptions, "subscription_id"),
        ("orders_reference_known_users", orders, "order_id"),
    ):
        unknown = [
            {"row": index, key: row.get(key, ""), "user_id": row.get("user_id", "")}
            for index, row in enumerate(rows, start=2)
            if row.get("user_id", "") not in known_users
        ]
        if unknown:
            checks.append(failed(check_id, len(unknown), "user_id exists in users", unknown[:10]))
        else:
            checks.append(passed(check_id, len(rows), "user_id exists in users"))

    cancelled_errors: list[dict[str, Any]] = []
    for index, row in enumerate(subscriptions, start=2):
        if row.get("status") == "cancelled" and not row.get("ended_at"):
            cancelled_errors.append({"row": index, "subscription_id": row.get("subscription_id", ""), "error": "cancelled subscription needs ended_at"})
            continue
        if row.get("ended_at"):
            try:
                started_at = parse_timestamp(row["started_at"])
                ended_at = parse_timestamp(row["ended_at"])
            except ValueError:
                continue
            if ended_at < started_at:
                cancelled_errors.append({"row": index, "subscription_id": row.get("subscription_id", ""), "error": "ended_at before started_at"})
    if cancelled_errors:
        checks.append(failed("subscription_lifecycle_valid", len(cancelled_errors), "cancelled subscriptions have valid ended_at", cancelled_errors[:10]))
    else:
        checks.append(passed("subscription_lifecycle_valid", len(subscriptions), "cancelled subscriptions have valid ended_at"))

    refund_guardrail = next((item for item in spec.get("guardrails", []) if isinstance(item, dict) and item.get("source") == "orders"), {})
    expected_currency = refund_guardrail.get("expected_currency")
    allowed_statuses = set(refund_guardrail.get("denominator_statuses", [])) | set(refund_guardrail.get("refund_statuses", [])) | {"pending"}
    order_errors: list[dict[str, Any]] = []
    for index, row in enumerate(orders, start=2):
        if expected_currency and row.get("currency") != expected_currency:
            order_errors.append({"row": index, "order_id": row.get("order_id", ""), "error": "unexpected currency"})
        if row.get("status") not in allowed_statuses:
            order_errors.append({"row": index, "order_id": row.get("order_id", ""), "error": "unexpected status"})
        try:
            if Decimal(row.get("amount_rub", "")) < Decimal("0"):
                order_errors.append({"row": index, "order_id": row.get("order_id", ""), "error": "negative amount"})
        except (InvalidOperation, ValueError):
            order_errors.append({"row": index, "order_id": row.get("order_id", ""), "error": "invalid amount"})
    if order_errors:
        checks.append(failed("orders_refund_domain_valid", len(order_errors), "currency/status/amount match refund guardrail", order_errors[:10]))
    else:
        checks.append(passed("orders_refund_domain_valid", len(orders), "currency/status/amount match refund guardrail"))
    return checks


def periods_by_id(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {period["period_id"]: period for period in spec["analysis_periods"]}


def period_for(start_date: date, spec: dict[str, Any]) -> str | None:
    for period in spec["analysis_periods"]:
        date_from = date.fromisoformat(period["date_from"])
        date_to = date.fromisoformat(period["date_to"])
        if date_from <= start_date <= date_to:
            return period["period_id"]
    return None


def non_test_users(users: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {
        row["user_id"]: row
        for row in users
        if row.get("user_id") and not (spec.get("exclude_test_users", True) and parse_bool(row.get("is_test_user", "")))
    }


def build_period_row(
    guardrail: dict[str, Any],
    period: dict[str, str],
    denominator: int,
    numerator: int,
    value: float | None,
    is_complete: bool,
    excluded_incomplete: int,
) -> dict[str, str]:
    return {
        "metric_id": guardrail["metric_id"],
        "row_type": "metric",
        "period": period["period_id"],
        "period_start": period["date_from"],
        "period_end": period["date_to"],
        "source": guardrail["source"],
        "unit": guardrail["unit"],
        "window_days": str(guardrail["window_days"]),
        "risk_direction": guardrail["risk_direction"],
        "denominator": str(denominator),
        "numerator": str(numerator),
        "metric_value": fmt(value) if is_complete else "",
        "baseline_value": "",
        "comparison_value": "",
        "absolute_delta": "",
        "max_rate": fmt(float(guardrail["max_rate"])),
        "max_delta": fmt(float(guardrail["max_delta"])),
        "threshold_breached": "",
        "decision_status": "",
        "is_complete_window": "true" if is_complete else "false",
        "excluded_incomplete_units": str(excluded_incomplete),
    }


def calculate_support_guardrail(
    guardrail: dict[str, Any],
    users: list[dict[str, str]],
    support_tickets: list[dict[str, str]],
    spec: dict[str, Any],
    timezone: ZoneInfo,
    observation_end: date,
) -> dict[str, dict[str, Any]]:
    users_by_id = non_test_users(users, spec)
    tickets_by_user: dict[str, list[date]] = {}
    for row in deduplicate(support_tickets, "ticket_id"):
        if row.get("user_id") in users_by_id:
            tickets_by_user.setdefault(row["user_id"], []).append(parse_timestamp(row["created_at"]).astimezone(timezone).date())
    results: dict[str, dict[str, Any]] = {}
    for period_id in ("baseline", "comparison"):
        denominator = numerator = excluded = 0
        for user in users_by_id.values():
            start_date = parse_timestamp(user["registered_at"]).astimezone(timezone).date()
            if period_for(start_date, spec) != period_id:
                continue
            if start_date + timedelta(days=int(guardrail["window_days"])) > observation_end:
                excluded += 1
                continue
            denominator += 1
            end_date = start_date + timedelta(days=int(guardrail["window_days"]))
            if any(start_date <= ticket_date <= end_date for ticket_date in tickets_by_user.get(user["user_id"], [])):
                numerator += 1
        results[period_id] = {
            "denominator": denominator,
            "numerator": numerator,
            "value": ratio(numerator, denominator),
            "excluded_incomplete": excluded,
            "is_complete": excluded == 0,
        }
    return results


def calculate_subscription_guardrail(
    guardrail: dict[str, Any],
    users: list[dict[str, str]],
    subscriptions: list[dict[str, str]],
    spec: dict[str, Any],
    timezone: ZoneInfo,
    observation_end: date,
) -> dict[str, dict[str, Any]]:
    users_by_id = non_test_users(users, spec)
    results: dict[str, dict[str, Any]] = {}
    for period_id in ("baseline", "comparison"):
        denominator = numerator = excluded = 0
        for row in deduplicate(subscriptions, "subscription_id"):
            if row.get("user_id") not in users_by_id:
                continue
            start_date = parse_timestamp(row["started_at"]).astimezone(timezone).date()
            if period_for(start_date, spec) != period_id:
                continue
            if start_date + timedelta(days=int(guardrail["window_days"])) > observation_end:
                excluded += 1
                continue
            denominator += 1
            if row.get("status") == "cancelled" and row.get("ended_at"):
                ended_date = parse_timestamp(row["ended_at"]).astimezone(timezone).date()
                if start_date <= ended_date <= start_date + timedelta(days=int(guardrail["window_days"])):
                    numerator += 1
        results[period_id] = {
            "denominator": denominator,
            "numerator": numerator,
            "value": ratio(numerator, denominator),
            "excluded_incomplete": excluded,
            "is_complete": excluded == 0,
        }
    return results


def calculate_refund_guardrail(
    guardrail: dict[str, Any],
    users: list[dict[str, str]],
    orders: list[dict[str, str]],
    spec: dict[str, Any],
    timezone: ZoneInfo,
    observation_end: date,
) -> dict[str, dict[str, Any]]:
    users_by_id = non_test_users(users, spec)
    denominator_statuses = set(guardrail.get("denominator_statuses", []))
    refund_statuses = set(guardrail.get("refund_statuses", []))
    results: dict[str, dict[str, Any]] = {}
    for period_id in ("baseline", "comparison"):
        denominator = numerator = excluded = 0
        for row in deduplicate(orders, "order_id"):
            if row.get("user_id") not in users_by_id or row.get("status") not in denominator_statuses:
                continue
            start_date = parse_timestamp(row["ordered_at"]).astimezone(timezone).date()
            if period_for(start_date, spec) != period_id:
                continue
            if start_date + timedelta(days=int(guardrail["window_days"])) > observation_end:
                excluded += 1
                continue
            denominator += 1
            if row.get("status") in refund_statuses:
                numerator += 1
        results[period_id] = {
            "denominator": denominator,
            "numerator": numerator,
            "value": ratio(numerator, denominator),
            "excluded_incomplete": excluded,
            "is_complete": excluded == 0,
        }
    return results


def decision_for(guardrail: dict[str, Any], baseline: float | None, comparison: float | None, complete: bool) -> tuple[str, bool, float | None]:
    if not complete or baseline is None or comparison is None:
        return "incomplete", False, None
    delta = comparison - baseline
    breached = comparison > float(guardrail["max_rate"]) or delta > float(guardrail["max_delta"])
    if breached:
        return "breached", True, delta
    if delta > 0:
        return "watch", False, delta
    return "ok", False, delta


def build_assessment_row(guardrail: dict[str, Any], period_results: dict[str, dict[str, Any]]) -> dict[str, str]:
    baseline = period_results["baseline"]["value"]
    comparison = period_results["comparison"]["value"]
    complete = bool(period_results["baseline"]["is_complete"] and period_results["comparison"]["is_complete"])
    decision_status, breached, delta = decision_for(guardrail, baseline, comparison, complete)
    return {
        "metric_id": guardrail["metric_id"],
        "row_type": "assessment",
        "period": "",
        "period_start": "",
        "period_end": "",
        "source": guardrail["source"],
        "unit": guardrail["unit"],
        "window_days": str(guardrail["window_days"]),
        "risk_direction": guardrail["risk_direction"],
        "denominator": f"{period_results['baseline']['denominator']}->{period_results['comparison']['denominator']}",
        "numerator": f"{period_results['baseline']['numerator']}->{period_results['comparison']['numerator']}",
        "metric_value": "",
        "baseline_value": fmt(baseline),
        "comparison_value": fmt(comparison),
        "absolute_delta": fmt(delta),
        "max_rate": fmt(float(guardrail["max_rate"])),
        "max_delta": fmt(float(guardrail["max_delta"])),
        "threshold_breached": "true" if breached else "false",
        "decision_status": decision_status,
        "is_complete_window": "true" if complete else "false",
        "excluded_incomplete_units": f"{period_results['baseline']['excluded_incomplete']}->{period_results['comparison']['excluded_incomplete']}",
    }


def calculate_table(
    users: list[dict[str, str]],
    support_tickets: list[dict[str, str]],
    subscriptions: list[dict[str, str]],
    orders: list[dict[str, str]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    timezone = ZoneInfo(spec["business_timezone"])
    observation_end = date.fromisoformat(str(spec["observation_end_date"]))
    periods = periods_by_id(spec)
    table: list[dict[str, str]] = []
    assessments: list[dict[str, str]] = []
    for guardrail in spec["guardrails"]:
        if guardrail["source"] == "support_tickets":
            results = calculate_support_guardrail(guardrail, users, support_tickets, spec, timezone, observation_end)
        elif guardrail["source"] == "subscriptions":
            results = calculate_subscription_guardrail(guardrail, users, subscriptions, spec, timezone, observation_end)
        elif guardrail["source"] == "orders":
            results = calculate_refund_guardrail(guardrail, users, orders, spec, timezone, observation_end)
        else:
            raise ValueError(f"unsupported guardrail source: {guardrail['source']}")
        for period_id in ("baseline", "comparison"):
            result = results[period_id]
            table.append(
                build_period_row(
                    guardrail,
                    periods[period_id],
                    int(result["denominator"]),
                    int(result["numerator"]),
                    result["value"],
                    bool(result["is_complete"]),
                    int(result["excluded_incomplete"]),
                )
            )
        assessment = build_assessment_row(guardrail, results)
        assessments.append(assessment)
        table.append(assessment)

    decision_statuses = [row["decision_status"] for row in assessments]
    if "breached" in decision_statuses:
        overall_decision = spec["overall_decision_rules"]["any_breached"]
    elif "watch" in decision_statuses:
        overall_decision = spec["overall_decision_rules"]["any_watch"]
    elif all(status == "ok" for status in decision_statuses):
        overall_decision = spec["overall_decision_rules"]["all_ok"]
    else:
        overall_decision = "wait_for_complete_windows"

    summary = {
        "rows": len(table),
        "guardrails": len(spec["guardrails"]),
        "metric_rows": sum(1 for row in table if row["row_type"] == "metric"),
        "assessment_rows": sum(1 for row in table if row["row_type"] == "assessment"),
        "breached_guardrails": sum(1 for row in assessments if row["decision_status"] == "breached"),
        "watch_guardrails": sum(1 for row in assessments if row["decision_status"] == "watch"),
        "ok_guardrails": sum(1 for row in assessments if row["decision_status"] == "ok"),
        "incomplete_guardrails": sum(1 for row in assessments if row["decision_status"] == "incomplete"),
        "overall_decision": overall_decision,
        "observation_end_date": observation_end.isoformat(),
        "deduplicated_tickets": len(deduplicate(support_tickets, "ticket_id")),
        "deduplicated_subscriptions": len(deduplicate(subscriptions, "subscription_id")),
        "deduplicated_orders": len(deduplicate(orders, "order_id")),
    }
    return table, summary


def calculate_guardrails(
    users: list[dict[str, str]],
    user_columns: list[str],
    support_tickets: list[dict[str, str]],
    ticket_columns: list[str],
    subscriptions: list[dict[str, str]],
    subscription_columns: list[str],
    orders: list[dict[str, str]],
    order_columns: list[str],
    metric_specs: dict[str, Any],
    spec: dict[str, Any],
) -> GuardrailResult:
    checks = validate_spec(spec, metric_specs)
    checks.extend(
        validate_inputs(
            users,
            user_columns,
            support_tickets,
            ticket_columns,
            subscriptions,
            subscription_columns,
            orders,
            order_columns,
            spec,
        )
    )
    table: list[dict[str, str]] = []
    summary: dict[str, Any] = {
        "rows": 0,
        "guardrails": len(spec.get("guardrails", [])) if isinstance(spec.get("guardrails"), list) else 0,
        "metric_rows": 0,
        "assessment_rows": 0,
        "breached_guardrails": 0,
        "watch_guardrails": 0,
        "ok_guardrails": 0,
        "incomplete_guardrails": 0,
        "overall_decision": None,
        "observation_end_date": spec.get("observation_end_date"),
        "deduplicated_tickets": len(deduplicate(support_tickets, "ticket_id")),
        "deduplicated_subscriptions": len(deduplicate(subscriptions, "subscription_id")),
        "deduplicated_orders": len(deduplicate(orders, "order_id")),
    }
    duplicate_check_ids = {"ticket_ids_unique", "subscription_ids_unique", "order_ids_unique"}
    can_build = all(check["valid"] for check in checks if check["id"] not in duplicate_check_ids)
    if can_build:
        table, summary = calculate_table(users, support_tickets, subscriptions, orders, spec)
        if table:
            checks.append(passed("guardrail_rows_present", len(table), "at least one guardrail output row"))
        else:
            checks.append(failed("guardrail_rows_present", 0, "at least one guardrail output row"))
    else:
        checks.append(failed("guardrail_rows_present", 0, "valid inputs before calculation"))
    report = {
        "valid": all(check["valid"] for check in checks),
        "checks": checks,
        "summary": summary,
    }
    return GuardrailResult(table=table, report=report)


def write_guardrails_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(
    users_path: Path,
    support_tickets_path: Path,
    subscriptions_path: Path,
    orders_path: Path,
    metric_specs_path: Path,
    spec_path: Path,
) -> GuardrailResult:
    users, user_columns = read_csv(users_path)
    support_tickets, ticket_columns = read_csv(support_tickets_path)
    subscriptions, subscription_columns = read_csv(subscriptions_path)
    orders, order_columns = read_csv(orders_path)
    metric_specs = normalize_metric_specs(read_json(metric_specs_path))
    spec = normalize_spec(read_json(spec_path))
    return calculate_guardrails(
        users,
        user_columns,
        support_tickets,
        ticket_columns,
        subscriptions,
        subscription_columns,
        orders,
        order_columns,
        metric_specs,
        spec,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate product guardrail metrics with thresholds and risk direction")
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--support-tickets", type=Path, required=True)
    parser.add_argument("--subscriptions", type=Path, required=True)
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--metric-specs", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args.users, args.support_tickets, args.subscriptions, args.orders, args.metric_specs, args.spec)
    except (OSError, csv.Error, json.JSONDecodeError, ValueError, ZoneInfoNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 2
    if result.table:
        write_guardrails_csv(args.output, result.table)
    rendered_report = json.dumps(result.report, ensure_ascii=False, indent=2) + "\n"
    if args.report is not None:
        args.report.write_text(rendered_report, encoding="utf-8")
    print(rendered_report, end="")
    if result.report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
