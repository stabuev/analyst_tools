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
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "experiment_bootstrap_analyzer.py"
BOOTSTRAP_SPEC = ROOT / "outputs" / "bootstrap_spec.json"
BOOTSTRAP_REPORT = ROOT / "outputs" / "bootstrap_intervals.json"
BOOTSTRAP_DISTRIBUTION = ROOT / "outputs" / "bootstrap_distribution.csv"
MANIFEST = ROOT / "outputs" / "resampling_manifest.json"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
OBSERVATIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "metric_observations.csv"
EFFECTS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "effect_results.csv"
ASSUMPTIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "assumption_checks.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("experiment_bootstrap_analyzer", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
ANALYZER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(ANALYZER)


def load_examples() -> tuple[dict, dict, list[dict[str, str]], list[dict[str, str]], dict]:
    return (
        ANALYZER.read_json(PROTOCOL),
        ANALYZER.read_json(BOOTSTRAP_SPEC),
        ANALYZER.read_csv(OBSERVATIONS),
        ANALYZER.read_csv(EFFECTS),
        ANALYZER.read_json(ASSUMPTIONS),
    )


def interval_by_metric(report: dict, metric_id: str) -> dict:
    return next(row for row in report["intervals"] if row["metric_id"] == metric_id)


class ExperimentBootstrapAnalyzerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol, self.bootstrap_spec, self.observations, self.effects, self.assumptions = load_examples()

    def build(self, spec: dict | None = None, assumptions: dict | None = None) -> tuple[dict, list[dict], dict]:
        return ANALYZER.build_report(
            self.protocol,
            self.bootstrap_spec if spec is None else spec,
            self.observations,
            self.effects,
            self.assumptions if assumptions is None else assumptions,
        )

    def test_committed_outputs_match_calculated_report(self) -> None:
        report, distribution, manifest = self.build()
        committed_report = json.loads(BOOTSTRAP_REPORT.read_text(encoding="utf-8"))
        committed_manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        with BOOTSTRAP_DISTRIBUTION.open(encoding="utf-8", newline="") as source:
            committed_distribution = list(csv.DictReader(source))
        self.assertEqual(report, committed_report)
        self.assertEqual(manifest, committed_manifest)
        self.assertEqual(len(distribution), len(committed_distribution))
        self.assertTrue(report["valid"])
        self.assertFalse(report["ready_for_decision"])
        self.assertEqual(report["summary"]["metrics_analyzed"], 5)

    def test_primary_bootstrap_interval_is_reproducible_and_matches_effect_table(self) -> None:
        report, distribution, _ = self.build()
        primary = interval_by_metric(report, "activation_rate_7d")
        self.assertEqual(primary["observed_absolute_lift"], -0.666667)
        self.assertEqual(primary["effect_table_absolute_lift"], -0.666667)
        self.assertEqual(primary["ci_low"], -1.0)
        self.assertEqual(primary["ci_high"], 0.0)
        self.assertTrue(primary["interval_contains_zero"])
        self.assertEqual(primary["permutation_p_value"], 0.401198)
        primary_rows = [row for row in distribution if row["metric_id"] == "activation_rate_7d"]
        self.assertEqual(len(primary_rows), 500)
        self.assertEqual(primary_rows[0]["bootstrap_absolute_lift"], -0.666667)

    def test_ratio_metric_keeps_numerator_and_denominator_paired(self) -> None:
        report, _, manifest = self.build()
        refund = interval_by_metric(report, "refund_rate_7d")
        self.assertTrue(refund["paired_denominator"])
        self.assertEqual(refund["control_zero_denominator_units"], 2)
        self.assertEqual(refund["invalid_resamples"], 148)
        self.assertEqual(refund["valid_resamples"], 352)
        self.assertEqual(refund["unique_bootstrap_lifts"], 1)
        self.assertIn("invalid_denominator_resamples", refund["diagnostics"])
        self.assertIn("paired_denominator_contains_zero_units", refund["diagnostics"])
        self.assertEqual(refund["scipy_check"]["method"], "manual_only_for_paired_denominator_ratio")
        self.assertEqual(manifest["paired_denominator_metrics"], ["refund_rate_7d"])

    def test_secondary_signals_remain_sensitivity_not_decision(self) -> None:
        report, _, _ = self.build()
        trial = interval_by_metric(report, "paywall_to_trial_conversion_7d")
        revenue = interval_by_metric(report, "realized_revenue_per_user_7d")
        self.assertEqual(trial["observed_absolute_lift"], 1.0)
        self.assertEqual(trial["ci_low"], 1.0)
        self.assertEqual(trial["ci_high"], 1.0)
        self.assertEqual(trial["permutation_p_value"], 0.095808)
        self.assertIn("degenerate_bootstrap_distribution", trial["diagnostics"])
        self.assertEqual(revenue["observed_absolute_lift"], 199.0)
        self.assertEqual(revenue["ci_low"], 149.0)
        self.assertEqual(revenue["ci_high"], 249.0)
        self.assertEqual(revenue["permutation_p_value"], 0.10978)
        self.assertEqual(revenue["scipy_check"]["ci_low"], 149.0)
        self.assertEqual(revenue["scipy_check"]["ci_high"], 249.0)

    def test_all_metrics_are_warning_because_tiny_sample_is_too_small(self) -> None:
        report, _, _ = self.build()
        self.assertEqual(
            report["summary"]["warning_metrics"],
            [
                "activation_rate_7d",
                "support_ticket_rate_7d",
                "refund_rate_7d",
                "paywall_to_trial_conversion_7d",
                "realized_revenue_per_user_7d",
            ],
        )
        for row in report["intervals"]:
            self.assertEqual(row["status"], "warning")
            self.assertIn("control_sample_below_minimum_units", row["diagnostics"])
            self.assertIn("treatment_sample_below_minimum_units", row["diagnostics"])

    def test_resampling_unit_must_match_protocol_units(self) -> None:
        spec = json.loads(json.dumps(self.bootstrap_spec))
        spec["resampling_unit"] = "session_id"
        report, _, _ = self.build(spec=spec)
        self.assertFalse(report["valid"])
        self.assertIn("resampling_unit_matches_protocol", report["summary"]["blocking_failures"])

    def test_upstream_invalid_effect_analysis_blocks_bootstrap(self) -> None:
        assumptions = json.loads(json.dumps(self.assumptions))
        assumptions["valid"] = False
        assumptions["summary"]["blocking_failures"] = ["activation_rate_7d:positive_denominators"]
        report, distribution, manifest = self.build(assumptions=assumptions)
        self.assertFalse(report["valid"])
        self.assertEqual(distribution, [])
        self.assertEqual(report["intervals"], [])
        self.assertIn("upstream_effect_analysis_not_valid", report["summary"]["blocking_failures"])
        self.assertFalse(manifest["valid"])

    def test_code_example_prints_bootstrap_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["metrics_analyzed"], 5)
        self.assertEqual(payload["distribution_rows"], 2500)
        self.assertEqual(payload["primary_ci"], [-1.0, 0.0])
        self.assertTrue(payload["refund_paired_denominator"])
        self.assertEqual(payload["refund_invalid_resamples"], 148)
        self.assertFalse(payload["revenue_interval_contains_zero"])

    def test_cli_writes_report_distribution_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "bootstrap_intervals.json"
            distribution_path = root / "bootstrap_distribution.csv"
            manifest_path = root / "resampling_manifest.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--protocol",
                    PROTOCOL,
                    "--bootstrap-spec",
                    BOOTSTRAP_SPEC,
                    "--observations",
                    OBSERVATIONS,
                    "--effect-results",
                    EFFECTS,
                    "--assumption-checks",
                    ASSUMPTIONS,
                    "--output-report",
                    report_path,
                    "--output-distribution",
                    distribution_path,
                    "--output-manifest",
                    manifest_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text(encoding="utf-8")))
            with distribution_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 2500)
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["scipy_version"], "1.17.1")


if __name__ == "__main__":
    unittest.main()
