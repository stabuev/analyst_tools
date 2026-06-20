from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MONEY_QUANT = Decimal("0.01")
ZERO = Decimal("0")

REQUIRED_USER_COLUMNS = {"user_id", "registered_at", "is_test_user"}
REQUIRED_ORDER_COLUMNS = {"order_id", "user_id", "ordered_at", "status", "currency", "amount_rub"}
REQUIRED_SUBSCRIPTION_COLUMNS = {
    "subscription_id",
    "user_id",
    "started_at",
    "ended_at",
    "status",
    "plan",
    "price_rub",
}
REQUIRED_SPEC_FIELDS = {
    "metric_id",
    "cohort_unit",
    "start_source",
    "revenue_currency",
    "revenue_windows_days",
    "order_paid_statuses",
    "order_refund_statuses",
    "order_pending_statuses",
    "subscription_started_statuses",
    "subscription_cancel_statuses",
    "business_timezone",
    "exclude_test_users",
    "incomplete_window_policy",
    "observation_end_date",
}
SUPPORTED_UNITS = {"user_id"}
SUPPORTED_START_SOURCES = {"registered_at"}
SUPPORTED_INCOMPLETE_POLICIES = {"blank_metrics"}

OUTPUT_COLUMNS = [
    "metric_id",
    "cohort_date",
    "window_days",
    "window_start",
    "window_end",
    "cohort_size",
    "paying_users",
    "paid_orders",
    "refunded_orders",
    "pending_orders",
    "subscriptions_started",
    "cancelled_subscriptions",
    "gross_revenue_rub",
    "refund_amount_rub",
    "realized_revenue_rub",
    "arpu_rub",
    "arppu_rub",
    "ltv_rub",
    "is_complete_window",
]


class MonetizationResult:
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


def parse_timestamp(value: str) -> datetime:
    if not value:
        raise ValueError("empty timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def parse_money(value: str) -> Decimal:
    if not value:
        raise ValueError("empty money value")
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError("money value must be decimal") from error
    if amount < ZERO:
        raise ValueError("money value must be non-negative")
    return amount


def money(value: Decimal) -> str:
    return f"{value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP):.2f}"


def normalize_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("monetization spec must be an object")
    return value


def duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def string_set(spec: dict[str, Any], key: str) -> set[str]:
    values = spec.get(key, [])
    return {value for value in values if isinstance(value, str)}


def validate_status_list(spec: dict[str, Any], key: str, checks: list[dict[str, Any]]) -> None:
    values = spec.get(key)
    if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
        checks.append(failed(f"{key}_valid", values, "non-empty list of status strings"))
        return
    duplicates = duplicate_values(values)
    if duplicates:
        checks.append(failed(f"{key}_valid", duplicates, "unique status strings", duplicates))
    else:
        checks.append(passed(f"{key}_valid", values, "non-empty unique status strings"))


def validate_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        checks.append(failed("monetization_spec_required_fields", missing, "all required monetization spec fields"))
    else:
        checks.append(passed("monetization_spec_required_fields", len(REQUIRED_SPEC_FIELDS), "all required monetization spec fields"))

    try:
        ZoneInfo(str(spec.get("business_timezone", "")))
    except ZoneInfoNotFoundError:
        checks.append(failed("business_timezone_valid", spec.get("business_timezone"), "IANA timezone name"))
    else:
        checks.append(passed("business_timezone_valid", spec.get("business_timezone"), "IANA timezone name"))

    if spec.get("cohort_unit") not in SUPPORTED_UNITS:
        checks.append(failed("cohort_unit_supported", spec.get("cohort_unit"), sorted(SUPPORTED_UNITS)))
    else:
        checks.append(passed("cohort_unit_supported", spec.get("cohort_unit"), sorted(SUPPORTED_UNITS)))

    if spec.get("start_source") not in SUPPORTED_START_SOURCES:
        checks.append(failed("start_source_supported", spec.get("start_source"), sorted(SUPPORTED_START_SOURCES)))
    else:
        checks.append(passed("start_source_supported", spec.get("start_source"), sorted(SUPPORTED_START_SOURCES)))

    windows = spec.get("revenue_windows_days")
    windows_valid = (
        isinstance(windows, list)
        and bool(windows)
        and all(isinstance(value, int) and value >= 0 for value in windows)
        and sorted(windows) == windows
        and len(set(windows)) == len(windows)
        and 0 in windows
    )
    if windows_valid:
        checks.append(passed("revenue_windows_valid", windows, "sorted unique non-negative windows including 0"))
    else:
        checks.append(failed("revenue_windows_valid", windows, "sorted unique non-negative windows including 0"))

    for key in (
        "order_paid_statuses",
        "order_refund_statuses",
        "order_pending_statuses",
        "subscription_started_statuses",
        "subscription_cancel_statuses",
    ):
        validate_status_list(spec, key, checks)

    paid = string_set(spec, "order_paid_statuses")
    refund = string_set(spec, "order_refund_statuses")
    pending = string_set(spec, "order_pending_statuses")
    overlaps = sorted((paid & refund) | (paid & pending) | (refund & pending))
    if overlaps:
        checks.append(failed("order_status_groups_disjoint", overlaps, "paid/refund/pending status groups are disjoint", overlaps))
    else:
        checks.append(passed("order_status_groups_disjoint", len(paid | refund | pending), "paid/refund/pending status groups are disjoint"))

    if spec.get("incomplete_window_policy") not in SUPPORTED_INCOMPLETE_POLICIES:
        checks.append(failed("incomplete_window_policy_supported", spec.get("incomplete_window_policy"), sorted(SUPPORTED_INCOMPLETE_POLICIES)))
    else:
        checks.append(passed("incomplete_window_policy_supported", spec.get("incomplete_window_policy"), sorted(SUPPORTED_INCOMPLETE_POLICIES)))

    observation_end = spec.get("observation_end_date")
    if observation_end != "auto":
        try:
            date.fromisoformat(str(observation_end))
        except ValueError:
            checks.append(failed("observation_end_date_valid", observation_end, "auto or YYYY-MM-DD"))
        else:
            checks.append(passed("observation_end_date_valid", observation_end, "auto or YYYY-MM-DD"))
    else:
        checks.append(passed("observation_end_date_valid", observation_end, "auto or YYYY-MM-DD"))
    return checks


def validate_inputs(
    users: list[dict[str, str]],
    user_columns: list[str],
    orders: list[dict[str, str]],
    order_columns: list[str],
    subscriptions: list[dict[str, str]],
    subscription_columns: list[str],
    spec: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing_user_columns = sorted(REQUIRED_USER_COLUMNS - set(user_columns))
    missing_order_columns = sorted(REQUIRED_ORDER_COLUMNS - set(order_columns))
    missing_subscription_columns = sorted(REQUIRED_SUBSCRIPTION_COLUMNS - set(subscription_columns))
    if missing_user_columns:
        checks.append(failed("user_columns_present", missing_user_columns, "all required user columns"))
    else:
        checks.append(passed("user_columns_present", len(user_columns), "all required user columns"))
    if missing_order_columns:
        checks.append(failed("order_columns_present", missing_order_columns, "all required order columns"))
    else:
        checks.append(passed("order_columns_present", len(order_columns), "all required order columns"))
    if missing_subscription_columns:
        checks.append(failed("subscription_columns_present", missing_subscription_columns, "all required subscription columns"))
    else:
        checks.append(passed("subscription_columns_present", len(subscription_columns), "all required subscription columns"))

    user_ids = [row.get("user_id", "") for row in users if row.get("user_id")]
    duplicate_user_ids = duplicate_values(user_ids)
    if duplicate_user_ids:
        checks.append(failed("user_ids_unique", len(duplicate_user_ids), "0 duplicate user_id values", duplicate_user_ids[:10]))
    else:
        checks.append(passed("user_ids_unique", len(user_ids), "0 duplicate user_id values"))

    order_ids = [row.get("order_id", "") for row in orders if row.get("order_id")]
    duplicate_order_ids = duplicate_values(order_ids)
    if duplicate_order_ids:
        checks.append(failed("order_ids_unique", len(duplicate_order_ids), "0 duplicate order_id values", duplicate_order_ids[:10]))
    else:
        checks.append(passed("order_ids_unique", len(order_ids), "0 duplicate order_id values"))

    subscription_ids = [row.get("subscription_id", "") for row in subscriptions if row.get("subscription_id")]
    duplicate_subscription_ids = duplicate_values(subscription_ids)
    if duplicate_subscription_ids:
        checks.append(failed("subscription_ids_unique", len(duplicate_subscription_ids), "0 duplicate subscription_id values", duplicate_subscription_ids[:10]))
    else:
        checks.append(passed("subscription_ids_unique", len(subscription_ids), "0 duplicate subscription_id values"))

    known_users = set(user_ids)
    registered_errors: list[dict[str, Any]] = []
    for index, row in enumerate(users, start=2):
        try:
            parse_timestamp(row.get("registered_at", ""))
        except ValueError as error:
            registered_errors.append({"row": index, "user_id": row.get("user_id", ""), "error": str(error)})
    if registered_errors:
        checks.append(failed("registered_timestamps_valid", len(registered_errors), "registered_at is timezone-aware", registered_errors[:10]))
    else:
        checks.append(passed("registered_timestamps_valid", len(users), "registered_at is timezone-aware"))

    allowed_order_statuses = string_set(spec, "order_paid_statuses") | string_set(spec, "order_refund_statuses") | string_set(spec, "order_pending_statuses")
    unknown_order_users: list[dict[str, Any]] = []
    order_timestamp_errors: list[dict[str, Any]] = []
    order_amount_errors: list[dict[str, Any]] = []
    currency_errors: list[dict[str, Any]] = []
    status_errors: list[dict[str, Any]] = []
    for index, row in enumerate(orders, start=2):
        user_id = row.get("user_id", "")
        if not user_id or user_id not in known_users:
            unknown_order_users.append({"row": index, "order_id": row.get("order_id", ""), "user_id": user_id})
        try:
            parse_timestamp(row.get("ordered_at", ""))
        except ValueError as error:
            order_timestamp_errors.append({"row": index, "order_id": row.get("order_id", ""), "error": str(error)})
        try:
            parse_money(row.get("amount_rub", ""))
        except ValueError as error:
            order_amount_errors.append({"row": index, "order_id": row.get("order_id", ""), "error": str(error)})
        if row.get("currency") != spec.get("revenue_currency"):
            currency_errors.append({"row": index, "order_id": row.get("order_id", ""), "currency": row.get("currency")})
        if row.get("status") not in allowed_order_statuses:
            status_errors.append({"row": index, "order_id": row.get("order_id", ""), "status": row.get("status")})
    if unknown_order_users:
        checks.append(failed("orders_reference_known_users", len(unknown_order_users), "order user_id exists in users", unknown_order_users[:10]))
    else:
        checks.append(passed("orders_reference_known_users", len(orders), "order user_id exists in users"))
    if order_timestamp_errors:
        checks.append(failed("order_timestamps_valid", len(order_timestamp_errors), "ordered_at is timezone-aware", order_timestamp_errors[:10]))
    else:
        checks.append(passed("order_timestamps_valid", len(orders), "ordered_at is timezone-aware"))
    if order_amount_errors:
        checks.append(failed("order_amounts_nonnegative", len(order_amount_errors), "amount_rub is non-negative Decimal", order_amount_errors[:10]))
    else:
        checks.append(passed("order_amounts_nonnegative", len(orders), "amount_rub is non-negative Decimal"))
    if currency_errors:
        checks.append(failed("order_currency_matches_spec", len(currency_errors), spec.get("revenue_currency"), currency_errors[:10]))
    else:
        checks.append(passed("order_currency_matches_spec", len(orders), spec.get("revenue_currency")))
    if status_errors:
        checks.append(failed("order_statuses_known", len(status_errors), sorted(allowed_order_statuses), status_errors[:10]))
    else:
        checks.append(passed("order_statuses_known", len(orders), sorted(allowed_order_statuses)))

    allowed_subscription_statuses = string_set(spec, "subscription_started_statuses") | string_set(spec, "subscription_cancel_statuses")
    unknown_subscription_users: list[dict[str, Any]] = []
    subscription_timestamp_errors: list[dict[str, Any]] = []
    subscription_amount_errors: list[dict[str, Any]] = []
    subscription_status_errors: list[dict[str, Any]] = []
    ended_before_started: list[dict[str, Any]] = []
    for index, row in enumerate(subscriptions, start=2):
        user_id = row.get("user_id", "")
        if not user_id or user_id not in known_users:
            unknown_subscription_users.append({"row": index, "subscription_id": row.get("subscription_id", ""), "user_id": user_id})
        started_at: datetime | None = None
        try:
            started_at = parse_timestamp(row.get("started_at", ""))
        except ValueError as error:
            subscription_timestamp_errors.append({"row": index, "subscription_id": row.get("subscription_id", ""), "field": "started_at", "error": str(error)})
        ended_at = row.get("ended_at", "")
        if ended_at:
            try:
                parsed_ended = parse_timestamp(ended_at)
            except ValueError as error:
                subscription_timestamp_errors.append({"row": index, "subscription_id": row.get("subscription_id", ""), "field": "ended_at", "error": str(error)})
            else:
                if started_at is not None and parsed_ended < started_at:
                    ended_before_started.append({"row": index, "subscription_id": row.get("subscription_id", "")})
        try:
            parse_money(row.get("price_rub", ""))
        except ValueError as error:
            subscription_amount_errors.append({"row": index, "subscription_id": row.get("subscription_id", ""), "error": str(error)})
        if row.get("status") not in allowed_subscription_statuses:
            subscription_status_errors.append({"row": index, "subscription_id": row.get("subscription_id", ""), "status": row.get("status")})
    if unknown_subscription_users:
        checks.append(failed("subscriptions_reference_known_users", len(unknown_subscription_users), "subscription user_id exists in users", unknown_subscription_users[:10]))
    else:
        checks.append(passed("subscriptions_reference_known_users", len(subscriptions), "subscription user_id exists in users"))
    if subscription_timestamp_errors:
        checks.append(failed("subscription_timestamps_valid", len(subscription_timestamp_errors), "started_at/ended_at are timezone-aware", subscription_timestamp_errors[:10]))
    else:
        checks.append(passed("subscription_timestamps_valid", len(subscriptions), "started_at/ended_at are timezone-aware when present"))
    if ended_before_started:
        checks.append(failed("subscription_end_after_start", len(ended_before_started), "ended_at >= started_at", ended_before_started[:10]))
    else:
        checks.append(passed("subscription_end_after_start", len(subscriptions), "ended_at >= started_at"))
    if subscription_amount_errors:
        checks.append(failed("subscription_prices_nonnegative", len(subscription_amount_errors), "price_rub is non-negative Decimal", subscription_amount_errors[:10]))
    else:
        checks.append(passed("subscription_prices_nonnegative", len(subscriptions), "price_rub is non-negative Decimal"))
    if subscription_status_errors:
        checks.append(failed("subscription_statuses_known", len(subscription_status_errors), sorted(allowed_subscription_statuses), subscription_status_errors[:10]))
    else:
        checks.append(passed("subscription_statuses_known", len(subscriptions), sorted(allowed_subscription_statuses)))
    return checks


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


def cohort_users(users: list[dict[str, str]], exclude_test_users: bool, timezone: ZoneInfo) -> dict[str, date]:
    output: dict[str, date] = {}
    for row in users:
        user_id = row.get("user_id", "")
        if not user_id:
            continue
        if exclude_test_users and parse_bool(row.get("is_test_user", "")):
            continue
        output[user_id] = parse_timestamp(row["registered_at"]).astimezone(timezone).date()
    return output


def resolve_observation_end(
    users: list[dict[str, str]],
    orders: list[dict[str, str]],
    subscriptions: list[dict[str, str]],
    spec: dict[str, Any],
    timezone: ZoneInfo,
) -> date:
    if spec.get("observation_end_date") != "auto":
        return date.fromisoformat(str(spec["observation_end_date"]))
    observed_dates: list[date] = []
    observed_dates.extend(parse_timestamp(row["registered_at"]).astimezone(timezone).date() for row in users if row.get("registered_at"))
    observed_dates.extend(parse_timestamp(row["ordered_at"]).astimezone(timezone).date() for row in orders if row.get("ordered_at"))
    for row in subscriptions:
        if row.get("started_at"):
            observed_dates.append(parse_timestamp(row["started_at"]).astimezone(timezone).date())
        if row.get("ended_at"):
            observed_dates.append(parse_timestamp(row["ended_at"]).astimezone(timezone).date())
    if not observed_dates:
        raise ValueError("cannot infer observation_end_date from empty monetization inputs")
    return max(observed_dates)


def order_age(row: dict[str, str], cohorts: dict[str, date], timezone: ZoneInfo) -> int | None:
    user_id = row.get("user_id", "")
    cohort_date = cohorts.get(user_id)
    if cohort_date is None:
        return None
    return (parse_timestamp(row["ordered_at"]).astimezone(timezone).date() - cohort_date).days


def subscription_start_age(row: dict[str, str], cohorts: dict[str, date], timezone: ZoneInfo) -> int | None:
    user_id = row.get("user_id", "")
    cohort_date = cohorts.get(user_id)
    if cohort_date is None:
        return None
    return (parse_timestamp(row["started_at"]).astimezone(timezone).date() - cohort_date).days


def subscription_cancel_age(row: dict[str, str], cohorts: dict[str, date], timezone: ZoneInfo) -> int | None:
    if not row.get("ended_at"):
        return None
    user_id = row.get("user_id", "")
    cohort_date = cohorts.get(user_id)
    if cohort_date is None:
        return None
    return (parse_timestamp(row["ended_at"]).astimezone(timezone).date() - cohort_date).days


def calculate_table(
    users: list[dict[str, str]],
    orders: list[dict[str, str]],
    subscriptions: list[dict[str, str]],
    spec: dict[str, Any],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    timezone = ZoneInfo(spec["business_timezone"])
    user_cohorts = cohort_users(users, bool(spec.get("exclude_test_users", True)), timezone)
    cohort_members: dict[date, set[str]] = {}
    for user_id, cohort_date in user_cohorts.items():
        cohort_members.setdefault(cohort_date, set()).add(user_id)

    deduped_orders = deduplicate(orders, "order_id")
    deduped_subscriptions = deduplicate(subscriptions, "subscription_id")
    observation_end = resolve_observation_end(users, deduped_orders, deduped_subscriptions, spec, timezone)
    windows = spec["revenue_windows_days"]
    paid_statuses = string_set(spec, "order_paid_statuses")
    refund_statuses = string_set(spec, "order_refund_statuses")
    pending_statuses = string_set(spec, "order_pending_statuses")
    started_statuses = string_set(spec, "subscription_started_statuses")
    cancel_statuses = string_set(spec, "subscription_cancel_statuses")

    table: list[dict[str, str]] = []
    complete_windows = 0
    incomplete_windows = 0
    for cohort_date in sorted(cohort_members):
        cohort_user_ids = cohort_members[cohort_date]
        cohort_size = len(cohort_user_ids)
        for window_days in windows:
            window_start = cohort_date
            window_end = cohort_date + timedelta(days=window_days)
            complete = window_end <= observation_end
            if complete:
                complete_windows += 1
            else:
                incomplete_windows += 1

            if complete:
                window_orders = [
                    row
                    for row in deduped_orders
                    if row.get("user_id") in cohort_user_ids
                    and (age := order_age(row, user_cohorts, timezone)) is not None
                    and 0 <= age <= window_days
                ]
                paid_orders = [row for row in window_orders if row.get("status") in paid_statuses]
                refunded_orders = [row for row in window_orders if row.get("status") in refund_statuses]
                pending_orders = [row for row in window_orders if row.get("status") in pending_statuses]
                paying_users = {row["user_id"] for row in paid_orders}
                gross_revenue = sum((parse_money(row["amount_rub"]) for row in paid_orders + refunded_orders), ZERO)
                refund_amount = sum((parse_money(row["amount_rub"]) for row in refunded_orders), ZERO)
                realized_revenue = gross_revenue - refund_amount

                window_subscriptions = [
                    row
                    for row in deduped_subscriptions
                    if row.get("user_id") in cohort_user_ids
                    and (age := subscription_start_age(row, user_cohorts, timezone)) is not None
                    and 0 <= age <= window_days
                    and row.get("status") in started_statuses
                ]
                cancelled_subscriptions = [
                    row
                    for row in deduped_subscriptions
                    if row.get("user_id") in cohort_user_ids
                    and row.get("status") in cancel_statuses
                    and (age := subscription_cancel_age(row, user_cohorts, timezone)) is not None
                    and 0 <= age <= window_days
                ]
                arpu = realized_revenue / Decimal(cohort_size) if cohort_size else ZERO
                arppu = realized_revenue / Decimal(len(paying_users)) if paying_users else ZERO
                values = {
                    "paying_users": str(len(paying_users)),
                    "paid_orders": str(len(paid_orders)),
                    "refunded_orders": str(len(refunded_orders)),
                    "pending_orders": str(len(pending_orders)),
                    "subscriptions_started": str(len(window_subscriptions)),
                    "cancelled_subscriptions": str(len(cancelled_subscriptions)),
                    "gross_revenue_rub": money(gross_revenue),
                    "refund_amount_rub": money(refund_amount),
                    "realized_revenue_rub": money(realized_revenue),
                    "arpu_rub": money(arpu),
                    "arppu_rub": money(arppu),
                    "ltv_rub": money(arpu),
                }
            else:
                values = {
                    "paying_users": "0",
                    "paid_orders": "0",
                    "refunded_orders": "0",
                    "pending_orders": "0",
                    "subscriptions_started": "0",
                    "cancelled_subscriptions": "0",
                    "gross_revenue_rub": "",
                    "refund_amount_rub": "",
                    "realized_revenue_rub": "",
                    "arpu_rub": "",
                    "arppu_rub": "",
                    "ltv_rub": "",
                }
            table.append({
                "metric_id": spec["metric_id"],
                "cohort_date": cohort_date.isoformat(),
                "window_days": str(window_days),
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "cohort_size": str(cohort_size),
                **values,
                "is_complete_window": "true" if complete else "false",
            })

    summary = {
        "rows": len(table),
        "cohorts": len(cohort_members),
        "eligible_users": len(user_cohorts),
        "excluded_test_users": len(users) - len(user_cohorts),
        "observation_end_date": observation_end.isoformat(),
        "complete_windows": complete_windows,
        "incomplete_windows": incomplete_windows,
        "windows_days": windows,
        "deduplicated_orders": len(deduped_orders),
        "deduplicated_subscriptions": len(deduped_subscriptions),
    }
    return table, summary


def calculate_monetization(
    users: list[dict[str, str]],
    user_columns: list[str],
    orders: list[dict[str, str]],
    order_columns: list[str],
    subscriptions: list[dict[str, str]],
    subscription_columns: list[str],
    spec: dict[str, Any],
) -> MonetizationResult:
    checks = validate_spec(spec)
    checks.extend(validate_inputs(users, user_columns, orders, order_columns, subscriptions, subscription_columns, spec))
    table: list[dict[str, str]] = []
    summary: dict[str, Any] = {
        "rows": 0,
        "cohorts": 0,
        "eligible_users": 0,
        "excluded_test_users": 0,
        "observation_end_date": None,
        "complete_windows": 0,
        "incomplete_windows": 0,
        "windows_days": [],
        "deduplicated_orders": len(deduplicate(orders, "order_id")),
        "deduplicated_subscriptions": len(deduplicate(subscriptions, "subscription_id")),
    }
    allowed_duplicate_checks = {"order_ids_unique", "subscription_ids_unique"}
    can_build = all(check["valid"] for check in checks if check["id"] not in allowed_duplicate_checks)
    if can_build:
        table, summary = calculate_table(users, orders, subscriptions, spec)
        if table:
            checks.append(passed("monetization_rows_present", len(table), "at least one monetization output row"))
        else:
            checks.append(failed("monetization_rows_present", 0, "at least one monetization output row"))
    else:
        checks.append(failed("monetization_rows_present", 0, "valid inputs before calculation"))
    report = {
        "valid": all(check["valid"] for check in checks),
        "checks": checks,
        "summary": summary,
    }
    return MonetizationResult(table=table, report=report)


def write_monetization_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(users_path: Path, orders_path: Path, subscriptions_path: Path, spec_path: Path) -> MonetizationResult:
    users, user_columns = read_csv(users_path)
    orders, order_columns = read_csv(orders_path)
    subscriptions, subscription_columns = read_csv(subscriptions_path)
    spec = normalize_spec(read_json(spec_path))
    return calculate_monetization(users, user_columns, orders, order_columns, subscriptions, subscription_columns, spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calculate realized revenue, ARPU, ARPPU and fixed-window cohort LTV")
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--subscriptions", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run(args.users, args.orders, args.subscriptions, args.spec)
    except (OSError, csv.Error, json.JSONDecodeError, ValueError, ZoneInfoNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 2
    if result.table:
        write_monetization_csv(args.output, result.table)
    rendered_report = json.dumps(result.report, ensure_ascii=False, indent=2) + "\n"
    if args.report is not None:
        args.report.write_text(rendered_report, encoding="utf-8")
    print(rendered_report, end="")
    if result.report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
