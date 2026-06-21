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
ARTIFACT = ROOT / "outputs" / "multiple_testing_policy_checker.py"
POLICY_SPEC = ROOT / "outputs" / "multiple_testing_policy.json"
REPORT = ROOT / "outputs" / "multiple_testing_report.json"
ADJUSTED_RESULTS = ROOT / "outputs" / "adjusted_results.csv"
MANIFEST = ROOT / "outputs" / "multiple_testing_manifest.json"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
EFFECTS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "effect_results.csv"
ASSUMPTIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "assumption_checks.json"
BOOTSTRAP = PHASE_ROOT / "06-bootstrap" / "outputs" / "bootstrap_intervals.json"
CUPED_REPORT = PHASE_ROOT / "07-cuped" / "outputs" / "variance_reduction_report.json"
CUPED_EFFECTS = PHASE_ROOT / "07-cuped" / "outputs" / "cuped_effects.csv"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("multiple_testing_policy_checker", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CHECKER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CHECKER)


def load_examples() -> tuple[dict, dict, list[dict[str, str]], dict, dict, list[dict[str, str]], dict]:
    return (
        CHECKER.read_json(PROTOCOL),
        CHECKER.read_json(POLICY_SPEC),
        CHECKER.read_csv(EFFECTS),
        CHECKER.read_json(BOOTSTRAP),
        CHECKER.read_json(CUPED_REPORT),
        CHECKER.read_csv(CUPED_EFFECTS),
        CHECKER.read_json(ASSUMPTIONS),
    )


def result_by_hypothesis(rows: list[dict], hypothesis_id: str) -> dict:
    return next(row for row in rows if row["hypothesis_id"] == hypothesis_id)


class MultipleTestingPolicyCheckerTest(unittest.TestCase):
    def setUp(self) -> None:
        (
            self.protocol,
            self.policy_spec,
            self.effects,
            self.bootstrap_report,
            self.cuped_report,
            self.cuped_effects,
            self.assumptions,
        ) = load_examples()

    def build(
        self,
        policy_spec: dict | None = None,
        bootstrap_report: dict | None = None,
        cuped_report: dict | None = None,
        assumptions: dict | None = None,
    ) -> tuple[dict, list[dict], dict]:
        return CHECKER.build_report(
            self.protocol,
            self.policy_spec if policy_spec is None else policy_spec,
            self.effects,
            self.bootstrap_report if bootstrap_report is None else bootstrap_report,
            self.cuped_report if cuped_report is None else cuped_report,
            self.cuped_effects,
            self.assumptions if assumptions is None else assumptions,
        )

    def test_committed_outputs_match_calculated_report(self) -> None:
        report, adjusted_rows, manifest = self.build()
        self.assertEqual(report, json.loads(REPORT.read_text(encoding="utf-8")))
        self.assertEqual(manifest, json.loads(MANIFEST.read_text(encoding="utf-8")))
        with TemporaryDirectory() as directory:
            adjusted_path = Path(directory) / "adjusted_results.csv"
            CHECKER.write_csv(adjusted_path, adjusted_rows, CHECKER.ADJUSTED_RESULT_FIELDS)
            self.assertEqual(adjusted_path.read_text(encoding="utf-8"), ADJUSTED_RESULTS.read_text(encoding="utf-8"))
        self.assertTrue(report["valid"])
        self.assertFalse(report["ready_for_decision"])
        self.assertEqual(report["summary"]["hypotheses_evaluated"], 8)

    def test_primary_gate_fails_even_with_cuped_sensitivity(self) -> None:
        report, rows, _ = self.build()
        primary = result_by_hypothesis(rows, "activation_rate_7d")
        self.assertEqual(primary["raw_p_value"], 0.931981)
        self.assertEqual(primary["adjusted_p_value"], 0.931981)
        self.assertEqual(primary["effect_source"], "cuped_sensitivity")
        self.assertEqual(primary["effect_estimate"], -0.416667)
        self.assertEqual(primary["gate_status"], "failed")
        self.assertFalse(primary["decision_eligible"])
        self.assertFalse(report["summary"]["primary_gate_passed"])
        self.assertEqual(report["summary"]["primary_practical_status"], {"activation_rate_7d": "missed_primary_direction"})

    def test_secondary_fdr_signal_is_blocked_by_primary_gate(self) -> None:
        report, rows, _ = self.build()
        trial = result_by_hypothesis(rows, "paywall_to_trial_conversion_7d")
        revenue = result_by_hypothesis(rows, "realized_revenue_per_user_7d")
        self.assertEqual(trial["method"], "fdr_bh")
        self.assertEqual(trial["raw_p_value"], 0.012674)
        self.assertEqual(trial["adjusted_p_value"], 0.025348)
        self.assertTrue(trial["reject_adjusted"])
        self.assertEqual(trial["gate_status"], "blocked_by_primary")
        self.assertFalse(trial["decision_eligible"])
        self.assertIn("adjusted_secondary_signal_blocked_by_primary_gate", trial["diagnostics"])
        self.assertEqual(revenue["adjusted_p_value"], 0.078355)
        self.assertFalse(revenue["reject_adjusted"])
        self.assertEqual(report["summary"]["secondary_adjusted_signals"], ["paywall_to_trial_conversion_7d"])

    def test_guardrail_family_uses_holm_and_remains_watch_not_cleared(self) -> None:
        report, rows, _ = self.build()
        guardrails = [row for row in rows if row["family"] == "guardrail"]
        self.assertEqual({row["method"] for row in guardrails}, {"holm"})
        self.assertEqual([row["adjusted_p_value"] for row in guardrails], [1.0, 1.0, 1.0])
        self.assertFalse(any(row["reject_adjusted"] for row in guardrails))
        self.assertFalse(report["summary"]["guardrail_gate_clear"])
        self.assertEqual(
            report["summary"]["guardrail_watch_metrics"],
            ["support_ticket_rate_7d", "subscription_cancel_rate_14d", "refund_rate_7d"],
        )

    def test_exploratory_segments_are_adjusted_but_never_decision_eligible(self) -> None:
        report, rows, _ = self.build()
        paid_search = result_by_hypothesis(rows, "activation_rate_7d_by_acquisition_channel_paid_search")
        country = result_by_hypothesis(rows, "activation_rate_7d_by_country_ru")
        self.assertEqual(paid_search["adjusted_p_value"], 0.021)
        self.assertEqual(country["adjusted_p_value"], 0.008)
        self.assertTrue(paid_search["reject_adjusted"])
        self.assertTrue(country["reject_adjusted"])
        self.assertFalse(paid_search["decision_eligible"])
        self.assertFalse(country["decision_eligible"])
        self.assertIn("post_hoc_candidate", country["diagnostics"])
        self.assertIn("segment_dimension_not_predeclared", country["diagnostics"])
        self.assertIn("activation_rate_7d_by_country_ru:segment_dimension_predeclared", report["summary"]["warning_checks"])

    def test_manual_adjustments_match_statsmodels_and_scipy_checks(self) -> None:
        report, _, _ = self.build()
        check_ids = {check["id"]: check for check in report["checks"]}
        self.assertTrue(check_ids["guardrail:statsmodels_adjustment_matches_manual"]["valid"])
        self.assertEqual(check_ids["secondary:statsmodels_adjustment_matches_manual"]["observed"], [0.025348, 0.078355])
        self.assertTrue(check_ids["secondary:scipy_fdr_matches_manual"]["valid"])
        self.assertTrue(check_ids["exploratory:scipy_fdr_matches_manual"]["valid"])

    def test_family_declaration_must_match_protocol(self) -> None:
        policy = json.loads(json.dumps(self.policy_spec))
        policy["families"][2]["hypotheses"].append("activation_rate_7d_by_country_ru")
        report, _, _ = self.build(policy_spec=policy)
        self.assertFalse(report["valid"])
        self.assertIn("secondary_family_matches_protocol", report["summary"]["blocking_failures"])
        self.assertIn("secondary_family_effect_results_exist", report["summary"]["blocking_failures"])

    def test_decision_metric_cannot_belong_to_multiple_families(self) -> None:
        policy = json.loads(json.dumps(self.policy_spec))
        policy["families"][2]["hypotheses"].append("activation_rate_7d")
        report, _, _ = self.build(policy_spec=policy)
        self.assertFalse(report["valid"])
        self.assertIn("decision_metric_belongs_to_one_family", report["summary"]["blocking_failures"])

    def test_post_hoc_candidate_cannot_be_marked_as_launch_gate(self) -> None:
        policy = json.loads(json.dumps(self.policy_spec))
        policy["exploratory_candidates"][1]["decision_use"] = "launch_gate"
        report, _, _ = self.build(policy_spec=policy)
        self.assertFalse(report["valid"])
        self.assertIn(
            "activation_rate_7d_by_country_ru:excluded_from_launch_decision",
            report["summary"]["blocking_failures"],
        )

    def test_invalid_upstream_reports_block_policy_validity(self) -> None:
        bootstrap = json.loads(json.dumps(self.bootstrap_report))
        bootstrap["valid"] = False
        cuped = json.loads(json.dumps(self.cuped_report))
        cuped["valid"] = False
        assumptions = json.loads(json.dumps(self.assumptions))
        assumptions["valid"] = False
        report, _, manifest = self.build(bootstrap_report=bootstrap, cuped_report=cuped, assumptions=assumptions)
        self.assertFalse(report["valid"])
        self.assertIn("upstream_effect_analysis_valid", report["summary"]["blocking_failures"])
        self.assertIn("upstream_bootstrap_valid", report["summary"]["blocking_failures"])
        self.assertIn("upstream_cuped_valid", report["summary"]["blocking_failures"])
        self.assertFalse(manifest["valid"])

    def test_code_example_prints_policy_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["ready_for_decision"])
        self.assertEqual(payload["hypotheses_evaluated"], 8)
        self.assertFalse(payload["primary_gate_passed"])
        self.assertEqual(payload["secondary_adjusted_signals"], ["paywall_to_trial_conversion_7d"])
        self.assertEqual(
            payload["secondary_adjusted_p_values"],
            {
                "paywall_to_trial_conversion_7d": 0.025348,
                "realized_revenue_per_user_7d": 0.078355,
            },
        )
        self.assertFalse(payload["launch_allowed_by_multiple_testing"])
        self.assertEqual(payload["manifest_families"], ["primary", "guardrail", "secondary", "exploratory"])

    def test_cli_writes_report_adjusted_results_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "multiple_testing_report.json"
            adjusted_path = root / "adjusted_results.csv"
            manifest_path = root / "multiple_testing_manifest.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--protocol",
                    PROTOCOL,
                    "--policy-spec",
                    POLICY_SPEC,
                    "--effect-results",
                    EFFECTS,
                    "--bootstrap-report",
                    BOOTSTRAP,
                    "--cuped-report",
                    CUPED_REPORT,
                    "--cuped-effects",
                    CUPED_EFFECTS,
                    "--assumption-checks",
                    ASSUMPTIONS,
                    "--output-report",
                    report_path,
                    "--output-adjusted-results",
                    adjusted_path,
                    "--output-manifest",
                    manifest_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text(encoding="utf-8")))
            self.assertEqual(adjusted_path.read_text(encoding="utf-8"), ADJUSTED_RESULTS.read_text(encoding="utf-8"))
            with adjusted_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 8)
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["statsmodels_version"], "0.14.6")


if __name__ == "__main__":
    unittest.main()
