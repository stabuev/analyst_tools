from __future__ import annotations

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
ARTIFACT = ROOT / "outputs" / "bootstrap_interval_builder.py"
SPEC_PATH = ROOT / "outputs" / "bootstrap_spec.json"
DISTRIBUTION_CARDS = PHASE / "02-distributions" / "outputs" / "distribution_cards.json"
BASELINE_INTERVALS = ROOT / "outputs" / "bootstrap_intervals.json"
BASELINE_REPORT = ROOT / "outputs" / "bootstrap_report.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("bootstrap_interval_builder", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(BUILDER)


def run_tiny() -> dict:
    return BUILDER.run(DATA / "sample_observations.csv", SPEC_PATH, DISTRIBUTION_CARDS)


def interval(report: dict, statistic_id: str) -> dict:
    return next(item for item in report["intervals"] if item["statistic_id"] == statistic_id)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class BootstrapIntervalBuilderTest(unittest.TestCase):
    def test_report_records_resampling_manifest(self) -> None:
        report = run_tiny()
        self.assertTrue(report["valid"])
        self.assertEqual(report["resampling_manifest"]["sampling_unit"], "user_id")
        self.assertEqual(report["resampling_manifest"]["resampling_unit"], "user_id")
        self.assertTrue(report["resampling_manifest"]["paired"])
        self.assertEqual(report["resampling_manifest"]["n_resamples"], 2000)

    def test_percentile_activation_interval_contains_observed_statistic(self) -> None:
        activation = interval(run_tiny(), "activation_rate_percentile")
        self.assertEqual(activation["method"], "percentile")
        self.assertEqual(activation["observed_statistic"], 0.8)
        self.assertLessEqual(activation["lower"], 0.8)
        self.assertGreaterEqual(activation["upper"], 0.8)
        self.assertEqual(activation["n"], 5)

    def test_basic_median_interval_uses_median_statistic(self) -> None:
        onboarding = interval(run_tiny(), "onboarding_seconds_median_basic")
        self.assertEqual(onboarding["method"], "basic")
        self.assertEqual(onboarding["observed_statistic"], 520.0)
        self.assertLessEqual(onboarding["lower"], onboarding["observed_statistic"])
        self.assertGreaterEqual(onboarding["upper"], onboarding["observed_statistic"])
        self.assertGreater(onboarding["distribution_summary"]["unique_values"], 1)

    def test_bca_interval_is_computed_by_scipy_path(self) -> None:
        revenue = interval(run_tiny(), "first_order_amount_mean_bca")
        self.assertEqual(revenue["method"], "bca")
        self.assertEqual(revenue["observed_statistic"], 784.0)
        self.assertLessEqual(revenue["lower"], revenue["observed_statistic"])
        self.assertGreaterEqual(revenue["upper"], revenue["observed_statistic"])

    def test_committed_report_matches_runner_output(self) -> None:
        self.assertEqual(json.loads(BASELINE_REPORT.read_text(encoding="utf-8")), run_tiny())

    def test_committed_intervals_file_is_projection_of_report(self) -> None:
        report = run_tiny()
        projected = json.loads(BASELINE_INTERVALS.read_text(encoding="utf-8"))
        self.assertEqual(projected, {"intervals": report["intervals"]})

    def test_degenerate_data_returns_warning_not_fake_precision(self) -> None:
        rows = [{"activated_7d": "true", "user_id": f"U{i}"} for i in range(5)]
        stat = {
            "statistic_id": "all_active",
            "parameter_id": "activation_rate",
            "metric_column": "activated_7d",
            "value_type": "boolean",
            "statistic": "mean",
            "method": "percentile",
            "known_limitations": [],
        }
        interval, checks = BUILDER.build_interval(rows, stat, 0.95, 100, 123)
        self.assertEqual(interval["status"], "warning")
        self.assertEqual(interval["lower"], 1.0)
        self.assertEqual(interval["upper"], 1.0)
        self.assertFalse(next(item for item in checks if item["id"] == "all_active_bootstrap_distribution_non_degenerate")["valid"])

    def test_unknown_bootstrap_method_is_rejected_before_resampling(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["statistics"][0]["method"] = "magic_bootstrap"
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = BUILDER.run(DATA / "sample_observations.csv", spec_path, DISTRIBUTION_CARDS)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "bootstrap_methods_supported")["valid"])

    def test_missing_distribution_card_blocks_statistic(self) -> None:
        with TemporaryDirectory() as directory:
            cards = json.loads(DISTRIBUTION_CARDS.read_text(encoding="utf-8"))
            cards["cards"] = [card for card in cards["cards"] if card["metric_id"] != "activation_7d"]
            cards_path = Path(directory) / "cards.json"
            cards_path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
            report = BUILDER.run(DATA / "sample_observations.csv", SPEC_PATH, cards_path)
            self.assertFalse(check(report, "activation_rate_percentile_distribution_card_resolves")["valid"])

    def test_cli_writes_intervals_and_report(self) -> None:
        with TemporaryDirectory() as directory:
            output_intervals = Path(directory) / "bootstrap_intervals.json"
            output_report = Path(directory) / "bootstrap_report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--sample",
                    DATA / "sample_observations.csv",
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

    def test_code_example_prints_bootstrap_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertIn("activation_rate_percentile", payload["intervals"])


if __name__ == "__main__":
    unittest.main()
