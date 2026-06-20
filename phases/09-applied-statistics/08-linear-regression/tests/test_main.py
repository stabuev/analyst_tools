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
ARTIFACT = ROOT / "outputs" / "ols_inference_runner.py"
SPEC_PATH = ROOT / "outputs" / "model_spec.json"
BASELINE_COEFFICIENTS = ROOT / "outputs" / "coefficients.csv"
BASELINE_REPORT = ROOT / "outputs" / "model_report.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("ols_inference_runner", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
RUNNER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(RUNNER)


def run_tiny() -> dict:
    return RUNNER.fit_model(DATA / "sample_observations.csv", SPEC_PATH)


def coefficient(report: dict, term: str) -> dict:
    return next(item for item in report["coefficients"] if item["term"] == term)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class OLSInferenceRunnerTest(unittest.TestCase):
    def test_report_builds_design_matrix_and_coefficients(self) -> None:
        report = run_tiny()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["rows"], 5)
        self.assertEqual(report["summary"]["terms"], 3)
        self.assertEqual(report["summary"]["residual_df"], 2)
        self.assertEqual(report["design_matrix"]["columns"], ["const", "onboarding_seconds_per_100_centered", "activated_7d"])

    def test_manual_coefficients_match_statsmodels(self) -> None:
        report = run_tiny()
        for row in report["coefficients"]:
            self.assertAlmostEqual(row["coefficient"], row["manual_coefficient"], places=6)
        self.assertEqual(check(report, "manual_and_statsmodels_coefficients_match")["observed"], 0.0)

    def test_onboarding_coefficient_has_standard_error_and_interval(self) -> None:
        onboarding = coefficient(run_tiny(), "onboarding_seconds_per_100_centered")
        self.assertIsInstance(onboarding["coefficient"], float)
        self.assertGreater(onboarding["standard_error"], 0)
        self.assertLess(onboarding["ci_lower"], onboarding["coefficient"])
        self.assertGreater(onboarding["ci_upper"], onboarding["coefficient"])
        self.assertEqual(onboarding["covariance_type"], "nonrobust")

    def test_activation_control_is_explicit_term_not_hidden_filter(self) -> None:
        activation = coefficient(run_tiny(), "activated_7d")
        self.assertIsInstance(activation["coefficient"], float)
        self.assertIn(1.0, [row[2] for row in run_tiny()["design_matrix"]["rows"]])
        self.assertIn(0.0, [row[2] for row in run_tiny()["design_matrix"]["rows"]])

    def test_committed_report_matches_runner_output(self) -> None:
        self.assertEqual(json.loads(BASELINE_REPORT.read_text(encoding="utf-8")), run_tiny())

    def test_committed_coefficients_csv_matches_report_terms(self) -> None:
        report = run_tiny()
        expected_terms = [row["term"] for row in report["coefficients"]]
        with BASELINE_COEFFICIENTS.open(encoding="utf-8", newline="") as source:
            terms = [row["term"] for row in csv.DictReader(source)]
        self.assertEqual(terms, expected_terms)

    def test_causal_wording_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["candidate_claim"] = "Long onboarding causes sessions to decrease."
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = RUNNER.fit_model(DATA / "sample_observations.csv", spec_path)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "causal_wording_forbidden")["valid"])

    def test_missing_model_column_is_reported(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["terms"][1]["column"] = "missing_onboarding"
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = RUNNER.fit_model(DATA / "sample_observations.csv", spec_path)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "model_columns_present")["valid"])

    def test_cli_writes_coefficients_and_report(self) -> None:
        with TemporaryDirectory() as directory:
            output_coefficients = Path(directory) / "coefficients.csv"
            output_report = Path(directory) / "model_report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--sample",
                    DATA / "sample_observations.csv",
                    "--spec",
                    SPEC_PATH,
                    "--output-coefficients",
                    output_coefficients,
                    "--output-report",
                    output_report,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_coefficients.exists())
            self.assertTrue(output_report.exists())
            self.assertTrue(json.loads(result.stdout)["valid"])

    def test_code_example_prints_coefficient_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertIn("onboarding_seconds_per_100_centered", payload["coefficients"])
        self.assertEqual(payload["claim_type"], "conditional_association_not_causality")


if __name__ == "__main__":
    unittest.main()
