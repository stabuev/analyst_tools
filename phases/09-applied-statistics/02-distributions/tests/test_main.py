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
DATA = ROOT.parent / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "distribution_card_builder.py"
SPEC_PATH = ROOT / "outputs" / "distribution_spec.json"
CARDS_PATH = ROOT / "outputs" / "distribution_cards.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("distribution_card_builder", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(BUILDER)


def card(report: dict, metric_id: str) -> dict:
    return next(item for item in report["cards"] if item["metric_id"] == metric_id)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def run_tiny() -> dict:
    return BUILDER.run(DATA / "sample_observations.csv", SPEC_PATH)


def copy_csv_with_mutation(source: Path, target: Path, mutate) -> None:
    rows = BUILDER.read_csv(source)
    mutate(rows)
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class DistributionCardBuilderTest(unittest.TestCase):
    def test_tiny_cards_cover_declared_metric_models(self) -> None:
        report = run_tiny()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["respondent_rows"], 5)
        self.assertEqual(report["summary"]["cards"], 4)
        families = {item["metric_id"]: item["distribution"]["family"] for item in report["cards"]}
        self.assertEqual(
            families,
            {
                "activation_7d": "bernoulli",
                "first_order_amount_rub_positive": "lognormal_positive",
                "support_tickets_7d": "poisson",
                "onboarding_seconds": "lognormal_positive",
            },
        )

    def test_activation_card_matches_manual_bernoulli_parameters(self) -> None:
        activation = card(run_tiny(), "activation_7d")
        self.assertEqual(activation["parameters"]["successes"], 4)
        self.assertEqual(activation["parameters"]["failures"], 1)
        self.assertEqual(activation["parameters"]["p_hat"], 0.8)
        self.assertEqual(activation["scipy_summary"]["bernoulli_variance"], 0.16)
        self.assertEqual(activation["scipy_summary"]["binomial_mean_for_n"], 4.0)

    def test_revenue_card_conditions_lognormal_fit_on_positive_amounts(self) -> None:
        report = run_tiny()
        revenue = card(report, "first_order_amount_rub_positive")
        self.assertEqual(revenue["n_observed"], 5)
        self.assertEqual(revenue["n_positive"], 4)
        self.assertEqual(revenue["zero_count"], 1)
        self.assertEqual(revenue["empirical"]["mean_all_observed"], 784.0)
        self.assertEqual(revenue["empirical"]["median_positive"], 990.0)
        self.assertFalse(check(report, "first_order_amount_rub_positive_zero_mass_documented")["valid"])
        self.assertEqual(
            check(report, "first_order_amount_rub_positive_zero_mass_documented")["severity"],
            "warning",
        )

    def test_support_ticket_card_is_poisson_count_diagnostic(self) -> None:
        support = card(run_tiny(), "support_tickets_7d")
        self.assertEqual(support["parameters"]["lambda_hat"], 0.4)
        self.assertEqual(support["empirical"]["zero_rate"], 0.6)
        self.assertEqual(support["empirical"]["max"], 1)
        self.assertEqual(support["scipy_summary"]["model_zero_probability"], 0.67032)

    def test_onboarding_card_keeps_right_tail_as_warning(self) -> None:
        report = run_tiny()
        onboarding = card(report, "onboarding_seconds")
        self.assertEqual(onboarding["empirical"]["median_positive"], 520.0)
        self.assertEqual(onboarding["empirical"]["p90_positive"], 836.0)
        self.assertGreater(onboarding["empirical"]["p90_to_median_ratio"], 1.5)
        tail = check(report, "onboarding_seconds_right_tail_diagnostic")
        self.assertEqual(tail["severity"], "warning")
        self.assertFalse(tail["valid"])

    def test_committed_distribution_cards_match_builder_output(self) -> None:
        expected = run_tiny()
        committed = json.loads(CARDS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(committed, expected)

    def test_invalid_boolean_activation_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.csv"

            def mutate(rows: list[dict[str, str]]) -> None:
                rows[0]["activated_7d"] = "maybe"

            copy_csv_with_mutation(DATA / "sample_observations.csv", sample_path, mutate)
            report = BUILDER.run(sample_path, SPEC_PATH)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "activation_7d_boolean_support")["valid"])

    def test_negative_revenue_breaks_lognormal_support(self) -> None:
        with TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.csv"

            def mutate(rows: list[dict[str, str]]) -> None:
                rows[1]["first_order_amount_rub"] = "-10.00"

            copy_csv_with_mutation(DATA / "sample_observations.csv", sample_path, mutate)
            report = BUILDER.run(sample_path, SPEC_PATH)
            self.assertFalse(report["valid"])
            self.assertFalse(
                check(report, "first_order_amount_rub_positive_nonnegative_support")["valid"]
            )

    def test_fractional_support_ticket_breaks_count_support(self) -> None:
        with TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.csv"

            def mutate(rows: list[dict[str, str]]) -> None:
                rows[2]["support_tickets_7d"] = "1.5"

            copy_csv_with_mutation(DATA / "sample_observations.csv", sample_path, mutate)
            report = BUILDER.run(sample_path, SPEC_PATH)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "support_tickets_7d_count_support")["valid"])

    def test_unknown_metric_column_is_reported_from_spec(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["metrics"][0]["column"] = "missing_activation"
            spec_path = Path(directory) / "distribution_spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = BUILDER.run(DATA / "sample_observations.csv", spec_path)
            self.assertFalse(report["valid"])
            self.assertEqual(check(report, "activation_7d_column_present")["observed"], "missing_activation")

    def test_cli_writes_distribution_cards_json_and_returns_zero(self) -> None:
        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "distribution_cards.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--sample",
                    DATA / "sample_observations.csv",
                    "--spec",
                    SPEC_PATH,
                    "--output",
                    output_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(output_path.read_text()))

    def test_cli_returns_one_for_blocking_error(self) -> None:
        with TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.csv"
            output_path = Path(directory) / "distribution_cards.json"

            def mutate(rows: list[dict[str, str]]) -> None:
                rows[0]["onboarding_seconds"] = "0"

            copy_csv_with_mutation(DATA / "sample_observations.csv", sample_path, mutate)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--sample",
                    sample_path,
                    "--spec",
                    SPEC_PATH,
                    "--output",
                    output_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(payload["valid"])
            self.assertFalse(check(payload, "onboarding_seconds_positive_support")["valid"])

    def test_code_example_prints_metric_families_and_warning_ids(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["metric_families"]["activation_7d"], "bernoulli")
        self.assertIn("onboarding_seconds_right_tail_diagnostic", payload["warning_ids"])


if __name__ == "__main__":
    unittest.main()
