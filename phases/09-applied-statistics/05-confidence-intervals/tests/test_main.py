from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
DATA = PHASE / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "confidence_interval_calculator.py"
SPEC_PATH = ROOT / "outputs" / "confidence_interval_spec.json"
DISTRIBUTION_CARDS = PHASE / "02-distributions" / "outputs" / "distribution_cards.json"
BASELINE_CSV = ROOT / "outputs" / "confidence_intervals.csv"
BASELINE_REPORT = ROOT / "outputs" / "confidence_interval_report.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("confidence_interval_calculator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CALCULATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CALCULATOR)


def run_tiny() -> dict:
    return CALCULATOR.run(
        DATA / "sample_observations.csv",
        DATA / "population_users.csv",
        SPEC_PATH,
        DISTRIBUTION_CARDS,
    )


def interval(report: dict, interval_id: str) -> dict:
    return next(item for item in report["intervals"] if item["interval_id"] == interval_id)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class ConfidenceIntervalCalculatorTest(unittest.TestCase):
    def test_report_builds_two_intervals_and_blocks_one(self) -> None:
        report = run_tiny()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["intervals"], 3)
        self.assertEqual(report["summary"]["ok_intervals"], 1)
        self.assertEqual(report["summary"]["warning_intervals"], 1)
        self.assertEqual(report["summary"]["blocked_intervals"], 1)
        self.assertEqual(report["summary"]["warning_count"], 2)

    def test_activation_normal_interval_matches_manual_formula(self) -> None:
        activation = interval(run_tiny(), "activation_rate_normal_95")
        self.assertEqual(activation["estimate"], 0.8)
        self.assertEqual(activation["standard_error"], 0.178885)
        self.assertEqual(activation["lower"], 0.449391)
        self.assertEqual(activation["upper"], 1.0)
        self.assertEqual(activation["status"], "warning")
        self.assertIn("few_failures_for_normal_proportion", activation["assumption_warning_ids"])

    def test_revenue_t_interval_uses_student_t_critical_value(self) -> None:
        revenue = interval(run_tiny(), "first_order_amount_t_95")
        self.assertEqual(revenue["estimate"], 784.0)
        self.assertEqual(revenue["standard_error"], 255.882786)
        self.assertEqual(revenue["lower"], 73.555492)
        self.assertEqual(revenue["upper"], 1494.444508)
        self.assertEqual(revenue["status"], "ok")

    def test_support_ticket_interval_is_blocked_by_minimum_n(self) -> None:
        support = interval(run_tiny(), "support_tickets_normal_95")
        self.assertEqual(support["status"], "blocked")
        self.assertIsNone(support["lower"])
        self.assertFalse(check(run_tiny(), "support_tickets_normal_95_minimum_n")["valid"])

    def test_coverage_rate_is_repeated_sampling_property(self) -> None:
        report = run_tiny()
        activation = interval(report, "activation_rate_normal_95")
        revenue = interval(report, "first_order_amount_t_95")
        self.assertGreaterEqual(activation["coverage_rate"], 0.80)
        self.assertLessEqual(activation["coverage_rate"], 1.0)
        self.assertGreaterEqual(revenue["coverage_rate"], 0.80)
        self.assertLessEqual(revenue["coverage_rate"], 1.0)

    def test_committed_report_matches_runner_output(self) -> None:
        self.assertEqual(json.loads(BASELINE_REPORT.read_text(encoding="utf-8")), run_tiny())

    def test_committed_csv_contains_same_interval_statuses(self) -> None:
        report = run_tiny()
        expected = {item["interval_id"]: item["status"] for item in report["intervals"]}
        with BASELINE_CSV.open(encoding="utf-8", newline="") as source:
            rows = {row["interval_id"]: row["status"] for row in csv.DictReader(source)}
        self.assertEqual(rows, expected)

    def test_missing_distribution_card_blocks_interval(self) -> None:
        with TemporaryDirectory() as directory:
            cards = json.loads(DISTRIBUTION_CARDS.read_text(encoding="utf-8"))
            cards["cards"] = [card for card in cards["cards"] if card["metric_id"] != "activation_7d"]
            cards_path = Path(directory) / "cards.json"
            cards_path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
            report = CALCULATOR.run(
                DATA / "sample_observations.csv",
                DATA / "population_users.csv",
                SPEC_PATH,
                cards_path,
            )
            self.assertFalse(check(report, "activation_rate_normal_95_distribution_card_resolves")["valid"])

    def test_unknown_interval_method_is_rejected_before_numbers(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["intervals"][0]["method"] = "magic_interval"
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = CALCULATOR.run(
                DATA / "sample_observations.csv",
                DATA / "population_users.csv",
                spec_path,
                DISTRIBUTION_CARDS,
            )
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "interval_methods_supported")["valid"])

    def test_cli_writes_interval_csv_and_report(self) -> None:
        with TemporaryDirectory() as directory:
            output_intervals = Path(directory) / "confidence_intervals.csv"
            output_report = Path(directory) / "confidence_interval_report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--sample",
                    DATA / "sample_observations.csv",
                    "--population",
                    DATA / "population_users.csv",
                    "--spec",
                    SPEC_PATH,
                    "--distribution-cards",
                    DISTRIBUTION_CARDS,
                    "--output-intervals",
                    output_intervals,
                    "--output-report",
                    output_report,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_intervals.exists())
            self.assertTrue(output_report.exists())
            self.assertTrue(json.loads(result.stdout)["valid"])

    def test_code_example_prints_interval_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["intervals"]["support_tickets_normal_95"]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
