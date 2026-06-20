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
ARTIFACT = ROOT / "outputs" / "guardrail_calculator.py"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
SUPPORT_TICKETS = ROOT.parent / "data" / "tiny" / "support_tickets.csv"
SUBSCRIPTIONS = ROOT.parent / "data" / "tiny" / "subscriptions.csv"
ORDERS = ROOT.parent / "data" / "tiny" / "orders.csv"
METRIC_SPECS = ROOT.parent / "01-metric-tree" / "outputs" / "metric_specs.json"
SPEC_PATH = ROOT / "outputs" / "guardrail_spec.json"
SAMPLE_GUARDRAILS = ROOT / "outputs" / "guardrails.csv"
MODULE_SPEC = importlib.util.spec_from_file_location("guardrail_calculator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CALCULATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CALCULATOR)


def load_inputs() -> tuple[
    list[dict[str, str]],
    list[str],
    list[dict[str, str]],
    list[str],
    list[dict[str, str]],
    list[str],
    list[dict[str, str]],
    list[str],
    dict,
    dict,
]:
    users, user_columns = CALCULATOR.read_csv(USERS)
    support_tickets, ticket_columns = CALCULATOR.read_csv(SUPPORT_TICKETS)
    subscriptions, subscription_columns = CALCULATOR.read_csv(SUBSCRIPTIONS)
    orders, order_columns = CALCULATOR.read_csv(ORDERS)
    metric_specs = CALCULATOR.normalize_metric_specs(CALCULATOR.read_json(METRIC_SPECS))
    guardrail_spec = CALCULATOR.normalize_spec(CALCULATOR.read_json(SPEC_PATH))
    return users, user_columns, support_tickets, ticket_columns, subscriptions, subscription_columns, orders, order_columns, metric_specs, guardrail_spec


def calculate(
    users: list[dict[str, str]] | None = None,
    support_tickets: list[dict[str, str]] | None = None,
    subscriptions: list[dict[str, str]] | None = None,
    orders: list[dict[str, str]] | None = None,
    metric_specs: dict | None = None,
    guardrail_spec: dict | None = None,
) -> object:
    base_users, user_columns, base_tickets, ticket_columns, base_subscriptions, subscription_columns, base_orders, order_columns, base_metric_specs, base_spec = load_inputs()
    return CALCULATOR.calculate_guardrails(
        base_users if users is None else users,
        user_columns,
        base_tickets if support_tickets is None else support_tickets,
        ticket_columns,
        base_subscriptions if subscriptions is None else subscriptions,
        subscription_columns,
        base_orders if orders is None else orders,
        order_columns,
        base_metric_specs if metric_specs is None else metric_specs,
        base_spec if guardrail_spec is None else guardrail_spec,
    )


def row_for(rows: list[dict[str, str]], metric_id: str, row_type: str, period: str | None = None) -> dict[str, str]:
    return next(
        row
        for row in rows
        if row["metric_id"] == metric_id
        and row["row_type"] == row_type
        and (period is None or row["period"] == period)
    )


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


def add_ticket(support_tickets: list[dict[str, str]], ticket_id: str, user_id: str, created_at: str) -> list[dict[str, str]]:
    updated = copy.deepcopy(support_tickets)
    ticket = copy.deepcopy(updated[0])
    ticket.update({
        "ticket_id": ticket_id,
        "user_id": user_id,
        "created_at": created_at,
        "category": "paywall",
        "status": "open",
    })
    updated.append(ticket)
    return updated


class GuardrailCalculatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.users, self.user_columns, self.tickets, self.ticket_columns, self.subscriptions, self.subscription_columns, self.orders, self.order_columns, self.metric_specs, self.spec = load_inputs()

    def test_valid_tiny_guardrails_block_rollout_when_thresholds_are_breached(self) -> None:
        result = calculate()
        self.assertTrue(result.report["valid"])
        self.assertEqual(result.report["summary"]["rows"], 9)
        self.assertEqual(result.report["summary"]["guardrails"], 3)
        self.assertEqual(result.report["summary"]["breached_guardrails"], 3)
        self.assertEqual(result.report["summary"]["overall_decision"], "block_rollout")

        support = row_for(result.table, "support_ticket_rate_7d", "assessment")
        cancel = row_for(result.table, "subscription_cancel_rate_14d", "assessment")
        refund = row_for(result.table, "refund_rate_7d", "assessment")
        self.assertEqual(support["baseline_value"], "0.250000")
        self.assertEqual(support["comparison_value"], "0.666667")
        self.assertEqual(support["absolute_delta"], "0.416667")
        self.assertEqual(cancel["comparison_value"], "0.500000")
        self.assertEqual(refund["comparison_value"], "0.500000")
        self.assertTrue(all(row["risk_direction"] == "up_is_bad" for row in (support, cancel, refund)))
        self.assertTrue(all(row["decision_status"] == "breached" for row in (support, cancel, refund)))

    def test_sample_guardrails_csv_matches_calculated_table(self) -> None:
        result = calculate()
        with SAMPLE_GUARDRAILS.open(encoding="utf-8", newline="") as source:
            expected = list(csv.DictReader(source))
        self.assertEqual(result.table, expected)

    def test_duplicate_ticket_is_reported_and_deduplicated(self) -> None:
        tickets = copy.deepcopy(self.tickets)
        tickets.append(copy.deepcopy(next(row for row in tickets if row["ticket_id"] == "T002")))
        result = calculate(support_tickets=tickets)
        self.assertFalse(result.report["valid"])
        self.assertEqual(check(result.report, "ticket_ids_unique")["sample"], ["T002"])
        self.assertEqual(result.report["summary"]["deduplicated_tickets"], 3)
        support = row_for(result.table, "support_ticket_rate_7d", "metric", "comparison")
        self.assertEqual(support["numerator"], "2")
        self.assertEqual(support["metric_value"], "0.666667")

    def test_duplicate_subscription_is_reported_and_deduplicated(self) -> None:
        subscriptions = copy.deepcopy(self.subscriptions)
        subscriptions.append(copy.deepcopy(next(row for row in subscriptions if row["subscription_id"] == "SUB003")))
        result = calculate(subscriptions=subscriptions)
        self.assertFalse(result.report["valid"])
        self.assertEqual(check(result.report, "subscription_ids_unique")["sample"], ["SUB003"])
        cancel = row_for(result.table, "subscription_cancel_rate_14d", "metric", "comparison")
        self.assertEqual(cancel["denominator"], "2")
        self.assertEqual(cancel["numerator"], "1")

    def test_duplicate_order_is_reported_and_deduplicated(self) -> None:
        orders = copy.deepcopy(self.orders)
        orders.append(copy.deepcopy(next(row for row in orders if row["order_id"] == "O003")))
        result = calculate(orders=orders)
        self.assertFalse(result.report["valid"])
        self.assertEqual(check(result.report, "order_ids_unique")["sample"], ["O003"])
        refund = row_for(result.table, "refund_rate_7d", "metric", "comparison")
        self.assertEqual(refund["denominator"], "2")
        self.assertEqual(refund["numerator"], "1")

    def test_unknown_support_ticket_user_blocks_calculation(self) -> None:
        tickets = add_ticket(self.tickets, "T900", "U404", "2026-06-08T15:17:00+03:00")
        result = calculate(support_tickets=tickets)
        self.assertFalse(result.report["valid"])
        self.assertFalse(check(result.report, "support_tickets_reference_known_users")["valid"])
        self.assertEqual(result.table, [])

    def test_cancelled_subscription_requires_valid_end_timestamp(self) -> None:
        subscriptions = copy.deepcopy(self.subscriptions)
        subscription = next(row for row in subscriptions if row["subscription_id"] == "SUB003")
        subscription["ended_at"] = ""
        result = calculate(subscriptions=subscriptions)
        self.assertFalse(result.report["valid"])
        self.assertFalse(check(result.report, "subscription_lifecycle_valid")["valid"])
        self.assertEqual(result.table, [])

    def test_refund_orders_must_match_currency_status_and_amount_domain(self) -> None:
        orders = copy.deepcopy(self.orders)
        orders[0]["currency"] = "USD"
        orders[1]["amount_rub"] = "-1.00"
        orders[2]["status"] = "chargeback"
        result = calculate(orders=orders)
        self.assertFalse(result.report["valid"])
        domain_check = check(result.report, "orders_refund_domain_valid")
        self.assertFalse(domain_check["valid"])
        self.assertEqual(domain_check["observed"], 3)

    def test_metric_spec_required_guardrail_must_be_role_guardrail(self) -> None:
        metric_specs = copy.deepcopy(self.metric_specs)
        metric = next(item for item in metric_specs["metrics"] if item["metric_id"] == "support_ticket_rate_7d")
        metric["role"] = "input"
        result = calculate(metric_specs=metric_specs)
        self.assertFalse(result.report["valid"])
        self.assertFalse(check(result.report, "guardrails_valid")["valid"])
        self.assertEqual(result.table, [])

    def test_risk_direction_must_be_up_is_bad(self) -> None:
        guardrail_spec = copy.deepcopy(self.spec)
        guardrail_spec["guardrails"][0]["risk_direction"] = "down_is_bad"
        result = calculate(guardrail_spec=guardrail_spec)
        self.assertFalse(result.report["valid"])
        self.assertFalse(check(result.report, "guardrails_valid")["valid"])
        self.assertEqual(result.table, [])

    def test_incomplete_windows_blank_metric_and_wait_for_more_data(self) -> None:
        guardrail_spec = copy.deepcopy(self.spec)
        guardrail_spec["observation_end_date"] = "2026-06-10"
        result = calculate(guardrail_spec=guardrail_spec)
        self.assertTrue(result.report["valid"])
        self.assertEqual(result.report["summary"]["incomplete_guardrails"], 3)
        self.assertEqual(result.report["summary"]["overall_decision"], "wait_for_complete_windows")
        support = row_for(result.table, "support_ticket_rate_7d", "metric", "comparison")
        self.assertEqual(support["is_complete_window"], "false")
        self.assertEqual(support["metric_value"], "")
        self.assertEqual(support["excluded_incomplete_units"], "3")
        support_assessment = row_for(result.table, "support_ticket_rate_7d", "assessment")
        self.assertEqual(support_assessment["decision_status"], "incomplete")
        self.assertEqual(support_assessment["threshold_breached"], "false")

    def test_high_thresholds_turn_bad_direction_into_watch_not_breach(self) -> None:
        guardrail_spec = copy.deepcopy(self.spec)
        for guardrail in guardrail_spec["guardrails"]:
            guardrail["max_rate"] = 1.0
            guardrail["max_delta"] = 1.0
        result = calculate(guardrail_spec=guardrail_spec)
        self.assertTrue(result.report["valid"])
        self.assertEqual(result.report["summary"]["breached_guardrails"], 0)
        self.assertEqual(result.report["summary"]["watch_guardrails"], 3)
        self.assertEqual(result.report["summary"]["overall_decision"], "investigate")

    def test_business_timezone_controls_guardrail_period_assignment(self) -> None:
        users = add_user(self.users, "U008", "2026-06-03T22:30:00+00:00")
        tickets = add_ticket(self.tickets, "T900", "U008", "2026-06-03T23:00:00+00:00")
        result = calculate(users=users, support_tickets=tickets)
        self.assertTrue(result.report["valid"])
        support = row_for(result.table, "support_ticket_rate_7d", "metric", "comparison")
        self.assertEqual(support["denominator"], "4")
        self.assertEqual(support["numerator"], "3")
        self.assertEqual(support["metric_value"], "0.750000")

    def test_test_users_are_excluded_from_guardrail_denominators(self) -> None:
        tickets = add_ticket(self.tickets, "T900", "U999", "2026-06-08T16:10:00+03:00")
        result = calculate(support_tickets=tickets)
        self.assertTrue(result.report["valid"])
        support = row_for(result.table, "support_ticket_rate_7d", "metric", "comparison")
        self.assertEqual(support["denominator"], "3")
        self.assertEqual(support["numerator"], "2")

    def test_cli_writes_guardrails_csv_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "guardrails.csv"
            report_path = root / "guardrails-report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--users",
                    USERS,
                    "--support-tickets",
                    SUPPORT_TICKETS,
                    "--subscriptions",
                    SUBSCRIPTIONS,
                    "--orders",
                    ORDERS,
                    "--metric-specs",
                    METRIC_SPECS,
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
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text(encoding="utf-8")))
            with output_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 9)

            invalid_spec = copy.deepcopy(self.spec)
            invalid_spec["guardrails"][0]["risk_direction"] = "down_is_bad"
            invalid_spec_path = root / "bad_guardrail_spec.json"
            invalid_spec_path.write_text(json.dumps(invalid_spec, ensure_ascii=False, indent=2), encoding="utf-8")
            invalid_result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--users",
                    USERS,
                    "--support-tickets",
                    SUPPORT_TICKETS,
                    "--subscriptions",
                    SUBSCRIPTIONS,
                    "--orders",
                    ORDERS,
                    "--metric-specs",
                    METRIC_SPECS,
                    "--spec",
                    invalid_spec_path,
                    "--output",
                    root / "bad-guardrails.csv",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(invalid_result.returncode, 1, invalid_result.stderr)
            self.assertFalse(json.loads(invalid_result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
