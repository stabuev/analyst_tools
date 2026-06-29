from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
DATA_DIR = PHASE_ROOT / "data" / "tiny"
SPEC = ROOT / "outputs" / "sensitivity_spec.json"
REPORT = ROOT / "outputs" / "sensitivity_report.json"
ARTIFACT = ROOT / "outputs" / "sensitivity_refutation_suite.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("sensitivity_refutation_suite", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SUITE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = SUITE
MODULE_SPEC.loader.exec_module(SUITE)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def falsification(report: dict, check_id: str) -> dict:
    return next(item for item in report["falsification_checks"] if item["check_id"] == check_id)


def estimate(report: dict, estimate_id: str) -> dict:
    return next(
        item
        for item in report["estimate_comparison"]["rows"]
        if item["estimate_id"] == estimate_id
    )


def claim(report: dict, claim_id: str) -> dict:
    return next(item for item in report["candidate_claims"] if item["claim_id"] == claim_id)


class SensitivityRefutationSuiteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = read_json(SPEC)

    def audit(
        self,
        *,
        data_dir: Path | None = None,
        spec: dict | None = None,
    ) -> dict:
        return SUITE.audit_sensitivity(
            DATA_DIR if data_dir is None else data_dir,
            self.spec if spec is None else spec,
        )

    def test_valid_report_runs_but_blocks_strong_effect_claim(self) -> None:
        report = self.audit()
        summary = report["summary"]
        self.assertTrue(report["valid"])
        self.assertEqual(summary["cohort_n"], 10)
        self.assertAlmostEqual(summary["primary_effect"], -0.3868752937879506)
        self.assertEqual(
            summary["falsification_failures"],
            [
                "placebo_outcome_pre_activation",
                "negative_control_outcome_app_crashes",
            ],
        )
        self.assertFalse(summary["allowed_effect_claim"])
        self.assertEqual(summary["blocking_checks"], [])
        self.assertIn("falsification_checks_failed", summary["claim_blocking_reasons"])
        self.assertIn("different_estimands_not_poolable", summary["claim_blocking_reasons"])

    def test_code_example_prints_transferable_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["sensitivity_valid"])
        self.assertEqual(payload["cohort_n"], 10)
        self.assertEqual(payload["primary_effect"], -0.386875)
        self.assertEqual(payload["first_nulling_bias"], 0.4)
        self.assertEqual(payload["design_estimate_range"], 1.5)
        self.assertFalse(payload["allowed_effect_claim"])

    def test_placebo_treatment_passes_but_placebo_outcome_fails(self) -> None:
        report = self.audit()
        placebo_treatment = falsification(report, "placebo_treatment_even_user_id")
        placebo_outcome = falsification(report, "placebo_outcome_pre_activation")
        self.assertTrue(placebo_treatment["passes"])
        self.assertAlmostEqual(placebo_treatment["effect"], 0.2)
        self.assertFalse(placebo_outcome["passes"])
        self.assertAlmostEqual(placebo_outcome["effect"], -0.5833333333333334)
        self.assertFalse(check(report, "placebo_outcome_pre_activation")["valid"])

    def test_negative_control_outcome_exposes_baseline_imbalance(self) -> None:
        report = self.audit()
        negative = falsification(report, "negative_control_outcome_app_crashes")
        self.assertFalse(negative["passes"])
        self.assertAlmostEqual(negative["treated_mean"], 2.1666666666666665)
        self.assertAlmostEqual(negative["control_mean"], 1.0)
        self.assertAlmostEqual(negative["effect"], 1.1666666666666665)
        self.assertFalse(check(report, "negative_control_outcome_app_crashes")["valid"])

    def test_upstream_did_placebo_is_carried_into_suite(self) -> None:
        report = self.audit()
        did = falsification(report, "did_fake_rollout_placebo")
        self.assertTrue(did["passes"])
        self.assertEqual(did["source_check"], "placebo_fake_rollout_in_pre_period_within_threshold")
        self.assertAlmostEqual(did["effect"], 0.0)

    def test_omitted_confounding_grid_names_nulling_strength(self) -> None:
        report = self.audit()
        sensitivity = report["omitted_confounding_sensitivity"]
        self.assertAlmostEqual(sensitivity["required_bias_to_reach_null"], 0.3868752937879506)
        first = sensitivity["first_nulling_scenario"]
        self.assertEqual(first["control_minus_treated_prevalence"], 0.4)
        self.assertEqual(first["outcome_risk_difference"], 1.0)
        self.assertAlmostEqual(first["bias_toward_zero"], 0.4)
        self.assertTrue(first["crosses_null"])

    def test_cross_design_estimates_are_compared_but_not_pooled(self) -> None:
        report = self.audit()
        self.assertAlmostEqual(estimate(report, "aipw_ate")["estimate"], -0.3868752937879506)
        self.assertAlmostEqual(estimate(report, "did_estimate")["estimate"], 0.08)
        self.assertAlmostEqual(estimate(report, "iv_wald_late")["estimate"], 0.5)
        comparison = report["estimate_comparison"]["comparison"]
        self.assertEqual(comparison["signs"], [-1, 1])
        self.assertAlmostEqual(comparison["range"], 1.5)
        self.assertFalse(comparison["pooling_allowed"])
        self.assertTrue(check(report, "design_estimates_are_not_poolable")["valid"])
        self.assertFalse(check(report, "design_estimates_show_directional_disagreement")["valid"])

    def test_candidate_claim_statuses_match_policy(self) -> None:
        report = self.audit()
        self.assertTrue(check(report, "candidate_claim_statuses_match_policy")["valid"])
        self.assertEqual(
            claim(report, "observational_aipw_strong_claim")["calculated_status"],
            "blocked_by_falsification",
        )
        self.assertEqual(
            claim(report, "did_limited_rollout_claim")["calculated_status"],
            "limited_design_specific_with_warnings",
        )
        self.assertEqual(
            claim(report, "iv_late_claim")["calculated_status"],
            "limited_late_with_unverifiable_assumptions",
        )
        self.assertEqual(
            claim(report, "pooled_average_effect_claim")["calculated_status"],
            "invalid_mixed_estimands",
        )

    def test_candidate_claim_declared_status_must_match_policy(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["candidate_claims"][3]["declared_status"] = "claimable_with_assumptions"
        report = self.audit(spec=spec)
        status = check(report, "candidate_claim_statuses_match_policy")
        self.assertFalse(report["valid"])
        self.assertFalse(status["valid"])
        self.assertEqual(status["sample"][0]["claim_id"], "pooled_average_effect_claim")

    def test_relaxed_placebo_outcome_threshold_removes_one_failure(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["falsification_checks"][1]["max_abs_effect"] = 0.7
        report = self.audit(spec=spec)
        self.assertTrue(falsification(report, "placebo_outcome_pre_activation")["passes"])
        self.assertEqual(
            report["summary"]["falsification_failures"],
            ["negative_control_outcome_app_crashes"],
        )

    def test_duplicate_source_grain_blocks_suite_validity(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            outcomes = pd.read_csv(tmp / "outcomes.csv")
            outcomes = pd.concat([outcomes, outcomes.iloc[[0]]], ignore_index=True)
            outcomes.to_csv(tmp / "outcomes.csv", index=False)
            report = self.audit(data_dir=tmp)
            grain = check(report, "source_tables_preserve_declared_grain")
            self.assertFalse(report["valid"])
            self.assertFalse(grain["valid"])
            self.assertEqual(grain["sample"][0]["table"], "outcomes")

    def test_empty_target_population_blocks_suite_validity(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["target_population"]["minimum_friction_score"] = 999
        report = self.audit(spec=spec)
        target = check(report, "target_population_is_non_empty")
        self.assertFalse(report["valid"])
        self.assertFalse(target["valid"])
        self.assertEqual(target["sample"]["cohort_n"], 0)

    def test_missing_upstream_report_is_structured_failure(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["upstream_reports"]["did"] = "13-causal-analysis/missing/did_report.json"
        report = self.audit(spec=spec)
        upstream = check(report, "upstream_reports_are_available")
        self.assertFalse(report["valid"])
        self.assertFalse(upstream["valid"])
        self.assertEqual(upstream["sample"][0]["report_id"], "did")

    def test_cli_fail_on_invalid_exits_nonzero_for_missing_upstream(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            spec = copy.deepcopy(self.spec)
            spec["upstream_reports"]["did"] = "13-causal-analysis/missing/did_report.json"
            spec_path = tmp / "invalid_sensitivity_spec.json"
            output_path = tmp / "sensitivity_report.json"
            write_json(spec_path, spec)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--spec",
                    spec_path,
                    "--output",
                    output_path,
                    "--fail-on-invalid",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            payload = read_json(output_path)
            self.assertFalse(payload["valid"])
            self.assertIn("upstream_reports_are_available", payload["summary"]["blocking_checks"])

    def test_committed_report_exists_and_matches_artifact_summary(self) -> None:
        report = read_json(REPORT)
        fresh = self.audit()
        self.assertEqual(report["summary"], fresh["summary"])
        self.assertEqual(report["falsification_checks"], fresh["falsification_checks"])
        self.assertEqual(report["candidate_claims"], fresh["candidate_claims"])


if __name__ == "__main__":
    unittest.main()
