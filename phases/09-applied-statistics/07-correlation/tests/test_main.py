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
ARTIFACT = ROOT / "outputs" / "correlation_auditor.py"
SPEC_PATH = ROOT / "outputs" / "correlation_spec.json"
BASELINE_REPORT = ROOT / "outputs" / "correlation_audit.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("correlation_auditor", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(AUDITOR)


def run_tiny() -> dict:
    return AUDITOR.run(DATA / "sample_observations.csv", SPEC_PATH)


def association(report: dict, association_id: str) -> dict:
    return next(item for item in report["associations"] if item["association_id"] == association_id)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class CorrelationAuditorTest(unittest.TestCase):
    def test_report_builds_two_association_audits(self) -> None:
        report = run_tiny()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["associations"], 2)
        self.assertEqual(report["summary"]["n_shuffles"], 1000)
        self.assertEqual(report["summary"]["warning_count"], 1)

    def test_sessions_activation_has_strong_aggregate_association(self) -> None:
        sessions = association(run_tiny(), "sessions_activation")
        self.assertEqual(sessions["aggregate"]["pearson"]["statistic"], 0.884652)
        self.assertEqual(sessions["aggregate"]["spearman"]["statistic"], 0.725476)
        self.assertLess(sessions["aggregate"]["pearson"]["shuffled_control"]["extreme_rate"], 0.2)
        self.assertEqual(sessions["allowed_claim_type"], "association_only")

    def test_stratified_reversal_is_visible_for_onboarding_activation(self) -> None:
        onboarding = association(run_tiny(), "onboarding_activation_by_device_tier")
        self.assertIn("stratified_sign_reversal", onboarding["diagnostic_warning_ids"])
        high = next(item for item in onboarding["strata"] if item["level"] == "high")
        mid = next(item for item in onboarding["strata"] if item["level"] == "mid")
        self.assertLess(high["pearson"], 0)
        self.assertIn("constant_or_too_small_input", mid["warning_ids"])
        self.assertFalse(check(run_tiny(), "onboarding_activation_by_device_tier_stratified_sign_reversal")["valid"])

    def test_committed_report_matches_runner_output(self) -> None:
        self.assertEqual(json.loads(BASELINE_REPORT.read_text(encoding="utf-8")), run_tiny())

    def test_causal_wording_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["associations"][0]["candidate_claim"] = "Long onboarding causes activation to increase."
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = AUDITOR.run(DATA / "sample_observations.csv", spec_path)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "onboarding_activation_by_device_tier_causal_wording_forbidden")["valid"])

    def test_unknown_correlation_method_is_rejected_before_numbers(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["associations"][0]["methods"].append("magic")
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = AUDITOR.run(DATA / "sample_observations.csv", spec_path)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "correlation_methods_supported")["valid"])

    def test_missing_column_blocks_association(self) -> None:
        with TemporaryDirectory() as directory:
            spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
            spec["associations"][1]["x_column"] = "missing_sessions"
            spec_path = Path(directory) / "spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
            report = AUDITOR.run(DATA / "sample_observations.csv", spec_path)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "sessions_activation_columns_present")["valid"])

    def test_cli_writes_correlation_audit_report(self) -> None:
        with TemporaryDirectory() as directory:
            output_report = Path(directory) / "correlation_audit.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--sample",
                    DATA / "sample_observations.csv",
                    "--spec",
                    SPEC_PATH,
                    "--output-report",
                    output_report,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_report.exists())
            self.assertTrue(json.loads(result.stdout)["valid"])

    def test_code_example_prints_correlation_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertIn("sessions_activation", payload["associations"])


if __name__ == "__main__":
    unittest.main()
