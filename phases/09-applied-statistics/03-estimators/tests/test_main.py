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
ARTIFACT = ROOT / "outputs" / "estimator_runner.py"
SPEC_PATH = ROOT / "outputs" / "estimator_spec.json"
SAMPLING_AUDIT = ROOT / "outputs" / "upstream_sampling_audit.json"
DISTRIBUTION_CARDS = PHASE / "02-distributions" / "outputs" / "distribution_cards.json"
POINT_ESTIMATES = ROOT / "outputs" / "point_estimates.csv"
ESTIMATOR_REPORT = ROOT / "outputs" / "estimator_report.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("estimator_runner", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
RUNNER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(RUNNER)


def run_tiny() -> dict:
    return RUNNER.run(
        DATA / "sample_observations.csv",
        SPEC_PATH,
        SAMPLING_AUDIT,
        DISTRIBUTION_CARDS,
    )


def estimate(report: dict, estimator_id: str) -> dict:
    return next(item for item in report["estimates"] if item["estimator_id"] == estimator_id)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def copy_csv_with_mutation(source: Path, target: Path, mutate) -> None:
    rows = RUNNER.read_csv(source)
    mutate(rows)
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class EstimatorRunnerTest(unittest.TestCase):
    def test_tiny_report_builds_five_point_estimates(self) -> None:
        report = run_tiny()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["respondent_rows"], 5)
        self.assertEqual(report["summary"]["estimates"], 5)
        self.assertEqual(report["summary"]["warning_count"], 1)
        self.assertFalse(check(report, "sampling_audit_warnings_carried")["valid"])

    def test_every_estimate_keeps_parameter_statistic_estimator_and_estimate(self) -> None:
        report = run_tiny()
        for item in report["estimates"]:
            self.assertTrue(item["parameter"])
            self.assertTrue(item["statistic"])
            self.assertTrue(item["estimator"])
            self.assertIsInstance(item["estimate"], float)
            self.assertTrue(item["distribution_card_metric_id"])

    def test_naive_activation_proportion_matches_manual_control(self) -> None:
        activation = estimate(run_tiny(), "activation_rate_naive")
        self.assertEqual(activation["estimate"], 0.8)
        self.assertEqual(activation["standard_error"], 0.178885)
        self.assertEqual(activation["n"], 5)
        self.assertIsNone(activation["sum_weights"])
        self.assertIn("unequal_inclusion_probabilities_declared", activation["upstream_warning_ids"])

    def test_weighted_activation_uses_inverse_probability_weights(self) -> None:
        activation = estimate(run_tiny(), "activation_rate_weighted")
        self.assertEqual(activation["estimate"], 0.84375)
        self.assertEqual(activation["sum_weights"], 10.666667)
        self.assertEqual(activation["effective_n"], 4.887828)
        self.assertLess(activation["effective_n"], activation["n"])

    def test_weighted_revenue_mean_includes_zero_amount_as_business_mass(self) -> None:
        revenue = estimate(run_tiny(), "first_order_amount_rub_weighted_mean")
        self.assertEqual(revenue["estimate"], 767.34374)
        self.assertEqual(revenue["metric_column"], "first_order_amount_rub")
        self.assertEqual(revenue["distribution_card_metric_id"], "first_order_amount_rub_positive")
        self.assertIn("Includes zero revenue as real business mass.", revenue["limitations"])

    def test_quantile_estimator_defers_standard_error_to_bootstrap(self) -> None:
        onboarding = estimate(run_tiny(), "onboarding_seconds_median")
        self.assertEqual(onboarding["estimate"], 520.0)
        self.assertIsNone(onboarding["standard_error"])
        self.assertEqual(onboarding["standard_error_method"], "not_computed_until_bootstrap")

    def test_weighted_support_ticket_rate_has_explicit_denominator_unit(self) -> None:
        support = estimate(run_tiny(), "support_tickets_per_user_weighted_rate")
        self.assertEqual(support["estimate"], 0.46875)
        self.assertEqual(support["estimator"], "inverse_probability_weighted_rate")
        self.assertEqual(support["metric_column"], "support_tickets_7d")

    def test_committed_estimator_report_matches_runner_output(self) -> None:
        self.assertEqual(json.loads(ESTIMATOR_REPORT.read_text(encoding="utf-8")), run_tiny())

    def test_committed_point_estimates_csv_has_same_estimates(self) -> None:
        report = run_tiny()
        with POINT_ESTIMATES.open(encoding="utf-8", newline="") as source:
            rows = {row["estimator_id"]: row for row in csv.DictReader(source)}
        self.assertEqual(set(rows), {item["estimator_id"] for item in report["estimates"]})
        self.assertEqual(rows["activation_rate_weighted"]["estimate"], "0.84375")
        self.assertIn("frame_segment_coverage", rows["activation_rate_weighted"]["upstream_warning_ids"])

    def test_missing_distribution_card_blocks_estimator_contract(self) -> None:
        with TemporaryDirectory() as directory:
            cards = json.loads(DISTRIBUTION_CARDS.read_text(encoding="utf-8"))
            cards["cards"] = [
                item for item in cards["cards"] if item["metric_id"] != "support_tickets_7d"
            ]
            cards_path = Path(directory) / "distribution_cards.json"
            cards_path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
            report = RUNNER.run(
                DATA / "sample_observations.csv",
                SPEC_PATH,
                SAMPLING_AUDIT,
                cards_path,
            )
            self.assertFalse(report["valid"])
            self.assertFalse(
                check(report, "support_tickets_per_user_weighted_rate_distribution_card_resolves")[
                    "valid"
                ]
            )

    def test_zero_weight_blocks_weighted_estimator(self) -> None:
        with TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.csv"

            def mutate(rows: list[dict[str, str]]) -> None:
                rows[0]["sample_weight"] = "0"

            copy_csv_with_mutation(DATA / "sample_observations.csv", sample_path, mutate)
            report = RUNNER.run(sample_path, SPEC_PATH, SAMPLING_AUDIT, DISTRIBUTION_CARDS)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "activation_rate_weighted_weights_positive")["valid"])

    def test_unknown_estimator_type_is_rejected_before_numbers_are_trusted(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["estimators"][0]["estimator"] = "magic_average"
            spec_path = Path(directory) / "estimator_spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = RUNNER.run(
                DATA / "sample_observations.csv",
                spec_path,
                SAMPLING_AUDIT,
                DISTRIBUTION_CARDS,
            )
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "estimators_supported")["valid"])

    def test_missing_metric_column_is_reported_from_estimator_spec(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["estimators"][0]["metric_column"] = "missing_activation"
            spec_path = Path(directory) / "estimator_spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = RUNNER.run(
                DATA / "sample_observations.csv",
                spec_path,
                SAMPLING_AUDIT,
                DISTRIBUTION_CARDS,
            )
            self.assertFalse(report["valid"])
            self.assertEqual(
                check(report, "activation_rate_naive_metric_column_present")["observed"],
                "missing_activation",
            )

    def test_sampling_audit_blocking_error_stops_estimates(self) -> None:
        with TemporaryDirectory() as directory:
            audit = json.loads(SAMPLING_AUDIT.read_text(encoding="utf-8"))
            audit["valid"] = False
            audit["summary"]["error_count"] = 1
            audit_path = Path(directory) / "sampling_audit.json"
            audit_path.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
            report = RUNNER.run(
                DATA / "sample_observations.csv",
                SPEC_PATH,
                audit_path,
                DISTRIBUTION_CARDS,
            )
            self.assertFalse(report["valid"])
            self.assertEqual(report["summary"]["estimates"], 0)
            self.assertFalse(check(report, "sampling_audit_has_no_blocking_errors")["valid"])

    def test_cli_writes_point_estimates_and_report(self) -> None:
        with TemporaryDirectory() as directory:
            estimates_path = Path(directory) / "point_estimates.csv"
            report_path = Path(directory) / "estimator_report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--sample",
                    DATA / "sample_observations.csv",
                    "--spec",
                    SPEC_PATH,
                    "--sampling-audit",
                    SAMPLING_AUDIT,
                    "--distribution-cards",
                    DISTRIBUTION_CARDS,
                    "--output-estimates",
                    estimates_path,
                    "--output-report",
                    report_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text()))
            self.assertTrue(estimates_path.read_text(encoding="utf-8").startswith("estimator_id,"))

    def test_cli_returns_one_for_invalid_estimator_spec(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["estimators"][0]["distribution_card_metric_id"] = "missing_card"
            spec_path = Path(directory) / "estimator_spec.json"
            estimates_path = Path(directory) / "point_estimates.csv"
            report_path = Path(directory) / "estimator_report.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--sample",
                    DATA / "sample_observations.csv",
                    "--spec",
                    spec_path,
                    "--sampling-audit",
                    SAMPLING_AUDIT,
                    "--distribution-cards",
                    DISTRIBUTION_CARDS,
                    "--output-estimates",
                    estimates_path,
                    "--output-report",
                    report_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            self.assertFalse(json.loads(report_path.read_text(encoding="utf-8"))["valid"])

    def test_code_example_prints_estimate_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["respondent_rows"], 5)
        self.assertEqual(payload["estimates"]["activation_rate_naive"], 0.8)
        self.assertEqual(payload["estimates"]["support_tickets_per_user_weighted_rate"], 0.46875)


if __name__ == "__main__":
    unittest.main()
