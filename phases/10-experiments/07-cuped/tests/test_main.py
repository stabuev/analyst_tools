from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "experiment_cuped_adjuster.py"
CUPED_SPEC = ROOT / "outputs" / "cuped_spec.json"
CUPED_EFFECTS = ROOT / "outputs" / "cuped_effects.csv"
ADJUSTED_OBSERVATIONS = ROOT / "outputs" / "adjusted_observations.csv"
REPORT = ROOT / "outputs" / "variance_reduction_report.json"
MANIFEST = ROOT / "outputs" / "cuped_manifest.json"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
OBSERVATIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "metric_observations.csv"
PRE_EXPERIMENT = PHASE_ROOT / "data" / "tiny" / "pre_experiment_metrics.csv"
EFFECTS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "effect_results.csv"
ASSUMPTIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "assumption_checks.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("experiment_cuped_adjuster", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
ADJUSTER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(ADJUSTER)


def load_examples() -> tuple[dict, dict, list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict]:
    return (
        ADJUSTER.read_json(PROTOCOL),
        ADJUSTER.read_json(CUPED_SPEC),
        ADJUSTER.read_csv(OBSERVATIONS),
        ADJUSTER.read_csv(PRE_EXPERIMENT),
        ADJUSTER.read_csv(EFFECTS),
        ADJUSTER.read_json(ASSUMPTIONS),
    )


def effect_by_metric(effects: list[dict], metric_id: str) -> dict:
    return next(row for row in effects if row["metric_id"] == metric_id)


class ExperimentCupedAdjusterTest(unittest.TestCase):
    def setUp(self) -> None:
        (
            self.protocol,
            self.cuped_spec,
            self.observations,
            self.pre_experiment,
            self.effects,
            self.assumptions,
        ) = load_examples()

    def build(
        self,
        spec: dict | None = None,
        pre_experiment: list[dict[str, str]] | None = None,
        assumptions: dict | None = None,
    ) -> tuple[dict, list[dict], list[dict], dict]:
        return ADJUSTER.build_report(
            self.protocol,
            self.cuped_spec if spec is None else spec,
            self.observations,
            self.pre_experiment if pre_experiment is None else pre_experiment,
            self.effects,
            self.assumptions if assumptions is None else assumptions,
        )

    def test_committed_outputs_match_calculated_report(self) -> None:
        report, effects, adjusted_rows, manifest = self.build()
        self.assertEqual(report, json.loads(REPORT.read_text(encoding="utf-8")))
        self.assertEqual(manifest, json.loads(MANIFEST.read_text(encoding="utf-8")))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            effects_path = root / "cuped_effects.csv"
            adjusted_path = root / "adjusted_observations.csv"
            ADJUSTER.write_csv(effects_path, effects, ADJUSTER.CUPED_EFFECT_FIELDS)
            ADJUSTER.write_csv(adjusted_path, adjusted_rows, ADJUSTER.ADJUSTED_OBSERVATION_FIELDS)
            self.assertEqual(effects_path.read_text(encoding="utf-8"), CUPED_EFFECTS.read_text(encoding="utf-8"))
            self.assertEqual(
                adjusted_path.read_text(encoding="utf-8"),
                ADJUSTED_OBSERVATIONS.read_text(encoding="utf-8"),
            )
        self.assertTrue(report["valid"])
        self.assertFalse(report["ready_for_decision"])
        self.assertEqual(report["summary"]["metrics_analyzed"], 4)

    def test_primary_adjustment_uses_declared_pre_treatment_covariate(self) -> None:
        report, effects, adjusted_rows, _ = self.build()
        primary = effect_by_metric(effects, "activation_rate_7d")
        primary_adjusted = [row for row in adjusted_rows if row["metric_id"] == "activation_rate_7d"]
        self.assertEqual(primary["covariate"], "sessions_7d_pre")
        self.assertEqual(primary["raw_absolute_lift"], -0.666667)
        self.assertEqual(primary["effect_table_absolute_lift"], -0.666667)
        self.assertEqual(primary["theta"], -0.1)
        self.assertEqual(primary["correlation"], -0.288675)
        self.assertEqual(primary["variance_reduction"], 0.083333)
        self.assertEqual(primary["adjusted_absolute_lift"], -0.416667)
        self.assertEqual(primary["ci_low"], -2.033823)
        self.assertEqual(primary["ci_high"], 1.20049)
        self.assertEqual(report["summary"]["primary_adjusted_absolute_lift"], -0.416667)
        self.assertEqual(len(primary_adjusted), 5)
        self.assertEqual(primary_adjusted[1]["adjusted_value"], 0.2)

    def test_secondary_revenue_signal_shrinks_after_adjustment(self) -> None:
        _, effects, _, _ = self.build()
        trial = effect_by_metric(effects, "paywall_to_trial_conversion_7d")
        revenue = effect_by_metric(effects, "realized_revenue_per_user_7d")
        self.assertFalse(trial["apply_to_decision"])
        self.assertEqual(trial["raw_absolute_lift"], 1.0)
        self.assertEqual(trial["adjusted_absolute_lift"], 0.25)
        self.assertEqual(trial["variance_reduction"], 0.75)
        self.assertFalse(revenue["apply_to_decision"])
        self.assertEqual(revenue["raw_absolute_lift"], 199.0)
        self.assertEqual(revenue["adjusted_absolute_lift"], 37.25)
        self.assertEqual(revenue["variance_reduction"], 0.797029)
        self.assertEqual(revenue["p_value"], 0.219915)

    def test_ratio_and_sparse_guardrails_are_explicitly_skipped(self) -> None:
        report, _, _, manifest = self.build()
        self.assertEqual(
            report["summary"]["skipped_metrics"],
            ["subscription_cancel_rate_14d", "refund_rate_7d"],
        )
        self.assertEqual(
            [row["reason"] for row in report["skipped_metrics"]],
            [
                "conditional subscription denominator is sparse in the tiny profile",
                "ratio metrics require paired numerator/denominator augmentation beyond this simple CUPED artifact",
            ],
        )
        self.assertEqual(manifest["skipped_metrics"], ["subscription_cancel_rate_14d", "refund_rate_7d"])

    def test_post_treatment_covariate_blocks_adjustment(self) -> None:
        spec = json.loads(json.dumps(self.cuped_spec))
        spec["covariates"][0]["timing"] = "post_treatment"
        report, effects, _, _ = self.build(spec=spec)
        self.assertFalse(report["valid"])
        self.assertIn("activation_rate_7d:covariate_is_pre_treatment", report["summary"]["blocking_failures"])
        self.assertIn(
            "paywall_to_trial_conversion_7d:covariate_is_pre_treatment",
            report["summary"]["blocking_failures"],
        )
        self.assertEqual([row["metric_id"] for row in effects], ["support_ticket_rate_7d"])

    def test_covariate_must_be_declared_in_protocol_cuped_policy(self) -> None:
        spec = json.loads(json.dumps(self.cuped_spec))
        spec["covariates"].append(
            {
                "name": "support_tickets_7d_pre",
                "source_table": "pre_experiment_metrics",
                "timing": "pre_treatment",
            }
        )
        spec["metrics"][0]["covariate"] = "support_tickets_7d_pre"
        report, _, _, _ = self.build(spec=spec)
        self.assertFalse(report["valid"])
        self.assertIn("activation_rate_7d:covariate_declared_in_protocol", report["summary"]["blocking_failures"])

    def test_missing_covariate_for_analyzed_user_blocks_report(self) -> None:
        pre_experiment = [row for row in self.pre_experiment if row["user_id"] != "U005"]
        report, effects, adjusted_rows, _ = self.build(pre_experiment=pre_experiment)
        self.assertFalse(report["valid"])
        self.assertEqual(effects, [])
        self.assertEqual(adjusted_rows, [])
        self.assertIn("activation_rate_7d:covariate_complete_for_analysis_units", report["summary"]["blocking_failures"])
        self.assertIn("realized_revenue_per_user_7d:covariate_complete_for_analysis_units", report["summary"]["blocking_failures"])

    def test_invalid_upstream_effect_analysis_blocks_cuped(self) -> None:
        assumptions = json.loads(json.dumps(self.assumptions))
        assumptions["valid"] = False
        assumptions["summary"]["blocking_failures"] = ["activation_rate_7d:positive_denominators"]
        report, effects, adjusted_rows, manifest = self.build(assumptions=assumptions)
        self.assertFalse(report["valid"])
        self.assertEqual(effects, [])
        self.assertEqual(adjusted_rows, [])
        self.assertIn("upstream_effect_analysis_not_valid", report["summary"]["blocking_failures"])
        self.assertFalse(manifest["valid"])

    def test_code_example_prints_cuped_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertFalse(payload["ready_for_decision"])
        self.assertEqual(payload["metrics_analyzed"], 4)
        self.assertEqual(payload["adjusted_observation_rows"], 20)
        self.assertEqual(payload["primary_raw_lift"], -0.666667)
        self.assertEqual(payload["primary_adjusted_lift"], -0.416667)
        self.assertEqual(payload["trial_variance_reduction"], 0.75)
        self.assertEqual(payload["skipped_metrics"], ["subscription_cancel_rate_14d", "refund_rate_7d"])

    def test_cli_writes_effects_adjusted_observations_report_and_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            effects_path = root / "cuped_effects.csv"
            adjusted_path = root / "adjusted_observations.csv"
            report_path = root / "variance_reduction_report.json"
            manifest_path = root / "cuped_manifest.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--protocol",
                    PROTOCOL,
                    "--cuped-spec",
                    CUPED_SPEC,
                    "--observations",
                    OBSERVATIONS,
                    "--pre-experiment-metrics",
                    PRE_EXPERIMENT,
                    "--effect-results",
                    EFFECTS,
                    "--assumption-checks",
                    ASSUMPTIONS,
                    "--output-effects",
                    effects_path,
                    "--output-adjusted-observations",
                    adjusted_path,
                    "--output-report",
                    report_path,
                    "--output-manifest",
                    manifest_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text(encoding="utf-8")))
            self.assertEqual(effects_path.read_text(encoding="utf-8"), CUPED_EFFECTS.read_text(encoding="utf-8"))
            self.assertEqual(adjusted_path.read_text(encoding="utf-8"), ADJUSTED_OBSERVATIONS.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["scipy_version"], "1.17.1")


if __name__ == "__main__":
    unittest.main()
