from __future__ import annotations

import copy
import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "monetization_calculator.py"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
ORDERS = ROOT.parent / "data" / "tiny" / "orders.csv"
SUBSCRIPTIONS = ROOT.parent / "data" / "tiny" / "subscriptions.csv"
SPEC_PATH = ROOT / "outputs" / "monetization_spec.json"
SAMPLE_MONETIZATION = ROOT / "outputs" / "monetization.csv"
MODULE_SPEC = importlib.util.spec_from_file_location("monetization_calculator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CALCULATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CALCULATOR)


def load_inputs() -> tuple[list[dict[str, str]], list[str], list[dict[str, str]], list[str], list[dict[str, str]], list[str], dict]:
    users, user_columns = CALCULATOR.read_csv(USERS)
    orders, order_columns = CALCULATOR.read_csv(ORDERS)
    subscriptions, subscription_columns = CALCULATOR.read_csv(SUBSCRIPTIONS)
    monetization_spec = CALCULATOR.normalize_spec(CALCULATOR.read_json(SPEC_PATH))
    return users, user_columns, orders, order_columns, subscriptions, subscription_columns, monetization_spec


def calculate(
    users: list[dict[str, str]] | None = None,
    orders: list[dict[str, str]] | None = None,
    subscriptions: list[dict[str, str]] | None = None,
    monetization_spec: dict | None = None,
) -> object:
    base_users, user_columns, base_orders, order_columns, base_subscriptions, subscription_columns, base_spec = load_inputs()
    return CALCULATOR.calculate_monetization(
        base_users if users is None else users,
        user_columns,
        base_orders if orders is None else orders,
        order_columns,
        base_subscriptions if subscriptions is None else subscriptions,
        subscription_columns,
        base_spec if monetization_spec is None else monetization_spec,
    )


def table_row(rows: list[dict[str, str]], cohort_date: str, window_days: int) -> dict[str, str]:
    return next(row for row in rows if row["cohort_date"] == cohort_date and row["window_days"] == str(window_days))


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def add_user(users: list[dict[str, str]], user_id: str, registered_at: str) -> list[dict[str, str]]:
    updated = copy.deepcopy(users)
    user = copy.deepcopy(updated[0])
    user.update({
        "user_id": user_id,
        "registered_at": registered_at,
        "country": "RU",
        "acquisition_channel": "organic",
        "platform": "web",
        "is_test_user": "false",
    })
    updated.append(user)
    return updated


def add_order(
    orders: list[dict[str, str]],
    order_id: str,
    user_id: str,
    ordered_at: str,
    amount_rub: str,
    status: str = "paid",
) -> list[dict[str, str]]:
    updated = copy.deepcopy(orders)
    order = copy.deepcopy(updated[0])
    order.update({
        "order_id": order_id,
        "user_id": user_id,
        "ordered_at": ordered_at,
        "status": status,
        "currency": "RUB",
        "amount_rub": amount_rub,
    })
    updated.append(order)
    return updated


def add_subscription(
    subscriptions: list[dict[str, str]],
    subscription_id: str,
    user_id: str,
    started_at: str,
    status: str = "active",
    ended_at: str = "",
    price_rub: str = "990.00",
) -> list[dict[str, str]]:
    updated = copy.deepcopy(subscriptions)
    subscription = copy.deepcopy(updated[0])
    subscription.update({
        "subscription_id": subscription_id,
        "user_id": user_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "status": status,
        "plan": "basic",
        "price_rub": price_rub,
    })
    updated.append(subscription)
    return updated


class MonetizationCalculatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.users, self.user_columns, self.orders, self.order_columns, self.subscriptions, self.subscription_columns, self.spec = load_inputs()

    def test_valid_tiny_monetization_has_expected_grid_and_day_zero_revenue(self) -> None:
        result = calculate()
        self.assertTrue(result.report["valid"])
        self.assertEqual(result.report["summary"]["rows"], 12)
        self.assertEqual(result.report["summary"]["cohorts"], 6)
        self.assertEqual(result.report["summary"]["eligible_users"], 7)
        self.assertEqual(result.report["summary"]["complete_windows"], 8)
        self.assertEqual(result.report["summary"]["incomplete_windows"], 4)
        first = table_row(result.table, "2026-06-01", 0)
        self.assertEqual(first["cohort_size"], "2")
        self.assertEqual(first["paying_users"], "2")
        self.assertEqual(first["paid_orders"], "2")
        self.assertEqual(first["realized_revenue_rub"], "2480.00")
        self.assertEqual(first["arpu_rub"], "1240.00")
        self.assertEqual(first["arppu_rub"], "1240.00")
        self.assertEqual(first["ltv_rub"], "1240.00")

    def test_sample_monetization_csv_matches_calculated_table(self) -> None:
        result = calculate()
        with SAMPLE_MONETIZATION.open(encoding="utf-8", newline="") as source:
            expected = list(csv.DictReader(source))
        self.assertEqual(result.table, expected)

    def test_refunded_order_is_visible_but_not_realized_revenue(self) -> None:
        result = calculate()
        row = table_row(result.table, "2026-06-04", 0)
        self.assertEqual(row["refunded_orders"], "1")
        self.assertEqual(row["gross_revenue_rub"], "1490.00")
        self.assertEqual(row["refund_amount_rub"], "1490.00")
        self.assertEqual(row["realized_revenue_rub"], "0.00")
        self.assertEqual(row["paying_users"], "0")

    def test_pending_order_is_not_revenue(self) -> None:
        result = calculate()
        row = table_row(result.table, "2026-06-08", 0)
        self.assertEqual(row["pending_orders"], "1")
        self.assertEqual(row["subscriptions_started"], "1")
        self.assertEqual(row["realized_revenue_rub"], "0.00")
        self.assertEqual(row["arpu_rub"], "0.00")

    def test_incomplete_ltv_window_has_blank_money_metrics(self) -> None:
        result = calculate()
        row = table_row(result.table, "2026-06-03", 7)
        self.assertEqual(row["is_complete_window"], "false")
        self.assertEqual(row["realized_revenue_rub"], "")
        self.assertEqual(row["arpu_rub"], "")
        self.assertEqual(row["ltv_rub"], "")

    def test_cancelled_subscription_is_counted_only_when_window_is_complete(self) -> None:
        monetization_spec = copy.deepcopy(self.spec)
        monetization_spec["observation_end_date"] = "2026-06-12"
        result = calculate(monetization_spec=monetization_spec)
        row = table_row(result.table, "2026-06-04", 7)
        self.assertEqual(row["is_complete_window"], "true")
        self.assertEqual(row["refunded_orders"], "1")
        self.assertEqual(row["cancelled_subscriptions"], "1")
        self.assertEqual(row["realized_revenue_rub"], "0.00")

    def test_duplicate_order_is_reported_and_deduplicated(self) -> None:
        orders = copy.deepcopy(self.orders)
        orders.append(copy.deepcopy(next(row for row in orders if row["order_id"] == "O004")))
        result = calculate(orders=orders)
        self.assertFalse(result.report["valid"])
        self.assertEqual(check(result.report, "order_ids_unique")["sample"], ["O004"])
        row = table_row(result.table, "2026-06-05", 0)
        self.assertEqual(row["paid_orders"], "1")
        self.assertEqual(row["realized_revenue_rub"], "450.00")

    def test_duplicate_subscription_is_reported_and_deduplicated(self) -> None:
        subscriptions = copy.deepcopy(self.subscriptions)
        subscriptions.append(copy.deepcopy(next(row for row in subscriptions if row["subscription_id"] == "SUB003")))
        monetization_spec = copy.deepcopy(self.spec)
        monetization_spec["observation_end_date"] = "2026-06-12"
        result = calculate(subscriptions=subscriptions, monetization_spec=monetization_spec)
        self.assertFalse(result.report["valid"])
        self.assertEqual(check(result.report, "subscription_ids_unique")["sample"], ["SUB003"])
        row = table_row(result.table, "2026-06-04", 7)
        self.assertEqual(row["subscriptions_started"], "1")
        self.assertEqual(row["cancelled_subscriptions"], "1")

    def test_order_user_must_exist(self) -> None:
        orders = add_order(self.orders, "O900", "U404", "2026-06-03T09:00:00+03:00", "100.00")
        result = calculate(orders=orders)
        self.assertFalse(check(result.report, "orders_reference_known_users")["valid"])
        self.assertEqual(check(result.report, "orders_reference_known_users")["sample"][0]["order_id"], "O900")

    def test_order_currency_must_match_spec(self) -> None:
        orders = copy.deepcopy(self.orders)
        orders[0]["currency"] = "USD"
        result = calculate(orders=orders)
        self.assertFalse(check(result.report, "order_currency_matches_spec")["valid"])

    def test_order_amount_must_be_nonnegative_decimal(self) -> None:
        orders = copy.deepcopy(self.orders)
        orders[0]["amount_rub"] = "-10.00"
        result = calculate(orders=orders)
        self.assertFalse(check(result.report, "order_amounts_nonnegative")["valid"])

    def test_revenue_windows_must_include_zero_and_be_sorted(self) -> None:
        monetization_spec = copy.deepcopy(self.spec)
        monetization_spec["revenue_windows_days"] = [7, 0]
        result = calculate(monetization_spec=monetization_spec)
        self.assertFalse(check(result.report, "revenue_windows_valid")["valid"])
        monetization_spec["revenue_windows_days"] = [1, 7]
        result = calculate(monetization_spec=monetization_spec)
        self.assertFalse(check(result.report, "revenue_windows_valid")["valid"])

    def test_business_timezone_controls_cohort_and_revenue_window(self) -> None:
        users = add_user(self.users, "U008", "2026-06-01T22:30:00+00:00")
        orders = add_order(self.orders, "O900", "U008", "2026-06-02T01:00:00+03:00", "100.00")
        result = calculate(users=users, orders=orders)
        row = table_row(result.table, "2026-06-02", 0)
        self.assertEqual(row["cohort_size"], "2")
        self.assertEqual(row["paying_users"], "1")
        self.assertEqual(row["realized_revenue_rub"], "100.00")
        self.assertEqual(row["arpu_rub"], "50.00")

    def test_extra_subscriptions_do_not_multiply_order_revenue(self) -> None:
        subscriptions = add_subscription(self.subscriptions, "SUB900", "U001", "2026-06-01T09:25:00+03:00")
        result = calculate(subscriptions=subscriptions)
        row = table_row(result.table, "2026-06-01", 0)
        self.assertEqual(row["subscriptions_started"], "3")
        self.assertEqual(row["paid_orders"], "2")
        self.assertEqual(row["realized_revenue_rub"], "2480.00")

    def test_cli_writes_monetization_csv_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "monetization.csv"
            report_path = root / "monetization-report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--users",
                    USERS,
                    "--orders",
                    ORDERS,
                    "--subscriptions",
                    SUBSCRIPTIONS,
                    "--spec",
                    SPEC_PATH,
                    "--output",
                    output_path,
                    "--report",
                    report_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["valid"])
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text()))
            with output_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 12)

            invalid_spec = copy.deepcopy(self.spec)
            invalid_spec["order_paid_statuses"] = ["paid", "refunded"]
            invalid_spec_path = root / "bad_monetization_spec.json"
            invalid_spec_path.write_text(json.dumps(invalid_spec, ensure_ascii=False, indent=2), encoding="utf-8")
            invalid_result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--users",
                    USERS,
                    "--orders",
                    ORDERS,
                    "--subscriptions",
                    SUBSCRIPTIONS,
                    "--spec",
                    invalid_spec_path,
                    "--output",
                    root / "bad-monetization.csv",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(invalid_result.returncode, 1, invalid_result.stderr)
            self.assertFalse(json.loads(invalid_result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
