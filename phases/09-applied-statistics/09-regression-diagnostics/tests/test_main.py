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
ARTIFACT = ROOT / "outputs" / "regression_diagnostics_checker.py"
SPEC_PATH = ROOT / "outputs" / "diagnostic_spec.json"
MODEL_REPORT = PHASE / "08-linear-regression" / "outputs" / "model_report.json"
BASELINE_REPORT = ROOT / "outputs" / "diagnostics.json"
BASELINE_FIGURE = ROOT / "outputs" / "regression_diagnostics.png"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("regression_diagnostics_checker", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CHECKER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CHECKER)


def run_tiny() -> dict:
    return CHECKER.run(MODEL_REPORT, SPEC_PATH)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class RegressionDiagnosticsCheckerTest(unittest.TestCase):
    def test_report_builds_machine_readable_diagnostics(self) -> None:
        report = run_tiny()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["rows"], 5)
        self.assertEqual(report["summary"]["terms"], 3)
        self.assertIn("residuals", report["diagnostics"])
        self.assertIn("leverage", report["diagnostics"])
        self.assertIn("cook_distance", report["diagnostics"])

    def test_residual_mean_is_near_zero(self) -> None:
        report = run_tiny()
        self.assertEqual(report["diagnostics"]["residuals"]["mean"], 0.0)
        self.assertTrue(check(report, "residual_mean_near_zero")["valid"])

    def test_tiny_sample_skips_formal_distribution_tests(self) -> None:
        report = run_tiny()
        self.assertIn("too_few_rows_for_residual_normality_test", report["summary"]["warning_flags"])
        self.assertIn("too_few_rows_for_breusch_pagan", report["summary"]["warning_flags"])
        self.assertEqual(report["diagnostics"]["normality"]["status"], "skipped")
        self.assertEqual(report["diagnostics"]["heteroscedasticity"]["status"], "skipped")

    def test_vif_and_condition_number_are_reported(self) -> None:
        report = run_tiny()
        self.assertIsInstance(report["diagnostics"]["condition_number"], float)
        self.assertEqual({item["term"] for item in report["diagnostics"]["vif"]}, {"onboarding_seconds_per_100_centered", "activated_7d"})
        self.assertTrue(check(report, "vif_below_threshold")["valid"])

    def test_influence_thresholds_are_machine_readable(self) -> None:
        report = run_tiny()
        self.assertEqual(len(report["diagnostics"]["leverage"]["values"]), 5)
        self.assertEqual(len(report["diagnostics"]["cook_distance"]["values"]), 5)
        self.assertGreater(report["diagnostics"]["leverage"]["threshold"], 0)
        self.assertGreater(report["diagnostics"]["cook_distance"]["threshold"], 0)

    def test_committed_report_matches_runner_output(self) -> None:
        self.assertEqual(json.loads(BASELINE_REPORT.read_text(encoding="utf-8")), run_tiny())

    def test_cli_writes_report_and_figure(self) -> None:
        with TemporaryDirectory() as directory:
            output_report = Path(directory) / "diagnostics.json"
            output_figure = Path(directory) / "diagnostics.png"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--model-report",
                    MODEL_REPORT,
                    "--spec",
                    SPEC_PATH,
                    "--output-report",
                    output_report,
                    "--output-figure",
                    output_figure,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_report.exists())
            self.assertTrue(output_figure.exists())
            self.assertTrue(json.loads(result.stdout)["valid"])

    def test_committed_figure_exists_and_is_png(self) -> None:
        self.assertTrue(BASELINE_FIGURE.exists())
        self.assertGreater(BASELINE_FIGURE.stat().st_size, 1000)
        self.assertEqual(BASELINE_FIGURE.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_invalid_source_model_report_blocks_diagnostics(self) -> None:
        with TemporaryDirectory() as directory:
            model = json.loads(MODEL_REPORT.read_text(encoding="utf-8"))
            model["valid"] = False
            model_path = Path(directory) / "model_report.json"
            model_path.write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
            report = CHECKER.run(model_path, SPEC_PATH)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "source_model_report_valid")["valid"])

    def test_code_example_prints_diagnostic_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertIn("too_few_rows_for_breusch_pagan", payload["warning_flags"])


if __name__ == "__main__":
    unittest.main()
