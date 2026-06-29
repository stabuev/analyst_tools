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
TARGET_TRIAL = PHASE_ROOT / "01-causal-question-and-estimand" / "outputs" / "target_trial_spec.json"
ESTIMAND = PHASE_ROOT / "01-causal-question-and-estimand" / "outputs" / "estimand.json"
ADJUSTMENT_GATE = PHASE_ROOT / "04-colliders" / "outputs" / "bad_control_selection_audit.json"
MODEL_SPEC = ROOT / "outputs" / "g_formula_spec.json"
REPORT = ROOT / "outputs" / "g_formula_estimate_report.json"
ARTIFACT = ROOT / "outputs" / "g_computation_estimator.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("g_computation_estimator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
ESTIMATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(ESTIMATOR)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def candidate(report: dict, model_id: str) -> dict:
    return next(
        item
        for item in report["policy_context"]["candidate_model_audits"]
        if item["model_id"] == model_id
    )


def candidate_spec(spec: dict, model_id: str) -> dict:
    return next(item for item in spec["candidate_model_variants"] if item["model_id"] == model_id)


class GComputationEstimatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.target_trial = read_json(TARGET_TRIAL)
        self.estimand = read_json(ESTIMAND)
        self.adjustment_gate = read_json(ADJUSTMENT_GATE)
        self.model_spec = read_json(MODEL_SPEC)

    def estimate(
        self,
        *,
        data_dir: Path | None = None,
        target_trial: dict | None = None,
        estimand: dict | None = None,
        adjustment_gate: dict | None = None,
        model_spec: dict | None = None,
    ) -> dict:
        return ESTIMATOR.estimate_g_formula(
            DATA_DIR if data_dir is None else data_dir,
            self.target_trial if target_trial is None else target_trial,
            self.estimand if estimand is None else estimand,
            self.adjustment_gate if adjustment_gate is None else adjustment_gate,
            self.model_spec if model_spec is None else model_spec,
        )

    def test_valid_report_matches_expected_tiny_g_formula_numbers(self) -> None:
        report = self.estimate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["cohort_n"], 10)
        self.assertEqual(report["summary"]["treated_n"], 6)
        self.assertEqual(report["summary"]["comparator_n"], 4)
        self.assertAlmostEqual(report["summary"]["naive_risk_difference"], -1 / 12)
        self.assertAlmostEqual(report["summary"]["manual_ate"], -0.39978100191623295)
        self.assertAlmostEqual(report["summary"]["manual_att"], -0.39978100191623295)
        self.assertAlmostEqual(report["summary"]["mean_y_if_treated"], 0.5400875992335064)
        self.assertAlmostEqual(report["summary"]["mean_y_if_comparator"], 0.9398686011497391)
        self.assertEqual(report["summary"]["blocking_checks"], [])

    def test_code_example_prints_transferable_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["estimate_valid"])
        self.assertEqual(payload["cohort_n"], 10)
        self.assertEqual(payload["treated_n"], 6)
        self.assertEqual(payload["comparator_n"], 4)
        self.assertEqual(payload["naive_risk_difference"], -0.083333)
        self.assertEqual(payload["standardized_ate"], -0.399781)
        self.assertFalse(payload["effect_claim_allowed"])
        self.assertIn(
            "counterfactual_predictions_stay_within_observed_support",
            payload["warning_checks"],
        )

    def test_manual_ols_coefficients_match_statsmodels_ols(self) -> None:
        report = self.estimate()
        self.assertTrue(check(report, "manual_ols_matches_statsmodels_ols")["valid"])
        manual = report["manual_ols"]["coefficients"]
        statsmodels = report["statsmodels_ols"]["coefficients"]
        self.assertEqual(set(manual), set(statsmodels))
        for term in manual:
            self.assertAlmostEqual(manual[term], statsmodels[term], places=12)
        self.assertLess(report["summary"]["manual_statsmodels_max_effect_diff"], 1e-12)

    def test_standardization_predicts_both_potential_outcomes_for_same_rows(self) -> None:
        report = self.estimate()
        rows = report["standardization"]["manual"]["standardized_rows"]
        self.assertEqual(len(rows), report["summary"]["cohort_n"])
        self.assertEqual({row["user_id"] for row in rows}, set(report["cohort"]["user_ids"]))
        u001 = next(row for row in rows if row["user_id"] == "U001")
        self.assertAlmostEqual(u001["predicted_y_if_treated"], 1.0007938680536537)
        self.assertAlmostEqual(u001["predicted_y_if_comparator"], 1.4005748699698866)
        self.assertAlmostEqual(u001["individual_contrast"], report["summary"]["manual_ate"])

    def test_lpm_probability_bounds_are_warning_not_silent_success(self) -> None:
        report = self.estimate()
        bounds = check(report, "linear_probability_predictions_within_probability_bounds")
        self.assertFalse(bounds["valid"])
        self.assertEqual(bounds["severity"], "warning")
        self.assertIn(bounds["id"], report["summary"]["warning_checks"])
        self.assertEqual(bounds["sample"][0]["user_id"], "U001")

    def test_counterfactual_support_extrapolation_is_reported(self) -> None:
        report = self.estimate()
        support = check(report, "counterfactual_predictions_stay_within_observed_support")
        self.assertFalse(support["valid"])
        self.assertEqual(support["severity"], "warning")
        sample = support["sample"]
        self.assertTrue(
            any(
                item["user_id"] == "U001" and item["counterfactual_treatment"] == 0
                for item in sample
            )
        )
        self.assertTrue(
            any(
                item["user_id"] == "U005" and item["counterfactual_treatment"] == 1
                for item in sample
            )
        )

    def test_model_basis_uses_all_allowed_sources_without_bad_controls(self) -> None:
        report = self.estimate()
        self.assertTrue(check(report, "model_uses_only_allowed_baseline_sources")["valid"])
        self.assertTrue(
            check(report, "model_source_basis_covers_allowed_adjustment_sources")["valid"]
        )
        primary = candidate(report, "lpm_g_computation_baseline_risk_v1")
        self.assertEqual(primary["calculated_status"], "estimable_with_warnings")
        self.assertEqual(primary["bad_control_variables"], [])
        self.assertEqual(primary["omitted_allowed_sources"], [])

    def test_too_narrow_model_variant_is_rejected_for_omitted_adjustment_sources(self) -> None:
        report = self.estimate()
        narrow = candidate(report, "too_narrow_friction_capacity_model")
        self.assertEqual(
            narrow["calculated_status"],
            "invalid_omits_required_adjustment_sources",
        )
        self.assertIn("region_id", narrow["omitted_allowed_sources"])
        self.assertIn("network_quality", narrow["omitted_allowed_sources"])

    def test_mediator_and_complete_case_variants_are_rejected_as_bad_controls(self) -> None:
        report = self.estimate()
        mediator = candidate(report, "mediator_leakage_outcome_model")
        complete_case = candidate(report, "complete_case_lpm")
        self.assertEqual(mediator["calculated_status"], "invalid_bad_control")
        self.assertEqual(mediator["bad_control_variables"], ["onboarding_completed_48h"])
        self.assertEqual(complete_case["calculated_status"], "invalid_bad_control")
        self.assertEqual(complete_case["bad_control_variables"], ["telemetry_complete_30d"])

    def test_candidate_variant_declared_status_must_match_policy(self) -> None:
        spec = copy.deepcopy(self.model_spec)
        candidate_spec(spec, "mediator_leakage_outcome_model")["declared_status"] = (
            "estimable_with_warnings"
        )
        report = self.estimate(model_spec=spec)
        status = check(report, "candidate_model_statuses_match_policy")
        self.assertFalse(report["valid"])
        self.assertFalse(status["valid"])
        self.assertEqual(status["sample"][0]["model_id"], "mediator_leakage_outcome_model")

    def test_effect_claim_cannot_be_enabled_with_unmeasured_backdoor_path(self) -> None:
        spec = copy.deepcopy(self.model_spec)
        spec["claim_policy"]["allowed_effect_claim"] = True
        report = self.estimate(model_spec=spec)
        claim = check(report, "claim_policy_respects_unmeasured_confounding_limitation")
        self.assertFalse(report["valid"])
        self.assertFalse(claim["valid"])
        self.assertEqual(claim["sample"][0]["field"], "allowed_effect_claim")

    def test_adjustment_gate_must_allow_handoff_action(self) -> None:
        gate = copy.deepcopy(self.adjustment_gate)
        primary = next(
            item
            for item in gate["candidate_action_audits"]
            if item["action_id"] == "recommended_pre_treatment_set"
        )
        primary["allowed_for_estimation"] = False
        report = self.estimate(adjustment_gate=gate)
        gate_check = check(report, "adjustment_gate_allows_estimator_handoff")
        self.assertFalse(report["valid"])
        self.assertFalse(gate_check["valid"])

    def test_duplicate_source_grain_blocks_cohort_build(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            users = pd.read_csv(tmp / "users.csv")
            users = pd.concat([users, users.iloc[[0]]], ignore_index=True)
            users.to_csv(tmp / "users.csv", index=False)
            report = self.estimate(data_dir=tmp)
            grain = check(report, "source_tables_preserve_declared_grain")
            self.assertFalse(report["valid"])
            self.assertFalse(grain["valid"])
            self.assertEqual(grain["sample"][0]["table"], "users")

    def test_treatment_timing_outside_grace_period_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            assistance = pd.read_csv(tmp / "onboarding_assistance.csv")
            assistance.loc[assistance["user_id"] == "U001", "started_at"] = (
                "2026-07-03T14:00:00+03:00"
            )
            assistance.to_csv(tmp / "onboarding_assistance.csv", index=False)
            report = self.estimate(data_dir=tmp)
            timing = check(report, "treatment_timing_respects_grace_period")
            self.assertFalse(report["valid"])
            self.assertFalse(timing["valid"])
            self.assertEqual(timing["sample"][0]["user_id"], "U001")

    def test_model_source_bad_control_is_blocked(self) -> None:
        spec = copy.deepcopy(self.model_spec)
        spec["estimator"]["direct_numeric_terms"].append("onboarding_completed_48h")
        spec["estimator"]["terms"].append("onboarding_completed_48h")
        report = self.estimate(model_spec=spec)
        sources = check(report, "model_uses_only_allowed_baseline_sources")
        self.assertFalse(report["valid"])
        self.assertFalse(sources["valid"])
        self.assertIn("onboarding_completed_48h", sources["sample"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            invalid = copy.deepcopy(self.model_spec)
            invalid["claim_policy"]["allowed_effect_claim"] = True
            spec_path = tmp / "g_formula_spec.json"
            output_path = tmp / "report.json"
            write_json(spec_path, invalid)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--data-dir",
                    DATA_DIR,
                    "--target-trial",
                    TARGET_TRIAL,
                    "--estimand",
                    ESTIMAND,
                    "--adjustment-gate",
                    ADJUSTMENT_GATE,
                    "--model-spec",
                    spec_path,
                    "--output",
                    output_path,
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            written = read_json(output_path)
            self.assertFalse(written["valid"])
            self.assertIn(
                "claim_policy_respects_unmeasured_confounding_limitation",
                written["summary"]["blocking_checks"],
            )


if __name__ == "__main__":
    unittest.main()
