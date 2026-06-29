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
ESTIMATOR_SPEC = ROOT / "outputs" / "ipw_aipw_spec.json"
REPORT = ROOT / "outputs" / "ipw_aipw_report.json"
ARTIFACT = ROOT / "outputs" / "ipw_aipw_estimator.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("ipw_aipw_estimator", ARTIFACT)
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


def candidate(report: dict, estimator_id: str) -> dict:
    return next(
        item
        for item in report["policy_context"]["candidate_estimator_audits"]
        if item["estimator_id"] == estimator_id
    )


def unit(report: dict, user_id: str) -> dict:
    return next(
        item for item in report["primary_estimator"]["unit_scores"] if item["user_id"] == user_id
    )


def trim_row(report: dict, threshold: float) -> dict:
    return next(
        item
        for item in report["primary_estimator"]["trimming_sensitivity"]
        if item["threshold"] == threshold
    )


def stress(report: dict, stress_test_id: str) -> dict:
    return next(item for item in report["stress_tests"] if item["stress_test_id"] == stress_test_id)


class IpwAipwEstimatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.target_trial = read_json(TARGET_TRIAL)
        self.estimand = read_json(ESTIMAND)
        self.adjustment_gate = read_json(ADJUSTMENT_GATE)
        self.estimator_spec = read_json(ESTIMATOR_SPEC)

    def estimate(
        self,
        *,
        data_dir: Path | None = None,
        target_trial: dict | None = None,
        estimand: dict | None = None,
        adjustment_gate: dict | None = None,
        estimator_spec: dict | None = None,
    ) -> dict:
        return ESTIMATOR.estimate_ipw_aipw(
            DATA_DIR if data_dir is None else data_dir,
            self.target_trial if target_trial is None else target_trial,
            self.estimand if estimand is None else estimand,
            self.adjustment_gate if adjustment_gate is None else adjustment_gate,
            self.estimator_spec if estimator_spec is None else estimator_spec,
        )

    def test_valid_report_matches_expected_tiny_ipw_aipw_numbers(self) -> None:
        report = self.estimate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["cohort_n"], 10)
        self.assertEqual(report["summary"]["treated_n"], 6)
        self.assertEqual(report["summary"]["comparator_n"], 4)
        self.assertAlmostEqual(report["summary"]["treated_risk"], 2 / 3)
        self.assertAlmostEqual(report["summary"]["comparator_risk"], 0.75)
        self.assertAlmostEqual(report["summary"]["naive_risk_difference"], -1 / 12)
        self.assertAlmostEqual(report["summary"]["ipw_hajek_ate"], -0.08519236630007954)
        self.assertAlmostEqual(report["summary"]["ipw_ht_ate"], 0.07893418528076585)
        self.assertAlmostEqual(report["summary"]["aipw_ate"], -0.3868752937879506)
        self.assertAlmostEqual(report["summary"]["outcome_regression_ate"], -0.399781001916233)
        self.assertEqual(report["summary"]["blocking_checks"], [])

    def test_code_example_prints_transferable_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["estimator_valid"])
        self.assertEqual(payload["cohort_n"], 10)
        self.assertEqual(payload["treated_n"], 6)
        self.assertEqual(payload["comparator_n"], 4)
        self.assertEqual(payload["ipw_hajek_ate"], -0.085192)
        self.assertEqual(payload["aipw_ate"], -0.386875)
        self.assertFalse(payload["effect_claim_allowed"])
        self.assertIn("propensity_overlap_has_tail_units", payload["warning_checks"])
        self.assertEqual(
            payload["stress_tests"]["misspecified_outcome_friction_capacity"]["aipw_ate"],
            0.067304,
        )

    def test_ridge_propensity_scores_and_overlap_tail_units_are_visible(self) -> None:
        report = self.estimate()
        self.assertTrue(check(report, "ridge_propensity_solver_converged")["valid"])
        self.assertTrue(check(report, "propensity_scores_within_open_unit_interval")["valid"])
        self.assertAlmostEqual(unit(report, "U001")["propensity_score"], 0.9944739510580042)
        self.assertAlmostEqual(unit(report, "U006")["propensity_score"], 0.6599264140180411)
        self.assertAlmostEqual(unit(report, "U011")["propensity_score"], 0.36054832011971855)
        overlap = check(report, "propensity_overlap_has_tail_units")
        self.assertFalse(overlap["valid"])
        self.assertEqual(overlap["severity"], "warning")
        self.assertEqual([item["user_id"] for item in overlap["sample"]], ["U001", "U002", "U010"])
        severe = check(report, "propensity_overlap_has_no_severe_tail_units")
        self.assertFalse(severe["valid"])
        self.assertEqual(severe["sample"][0]["user_id"], "U001")

    def test_stabilized_weights_and_effective_sample_size_are_reported(self) -> None:
        report = self.estimate()
        weights = report["primary_estimator"]["weights"]
        self.assertAlmostEqual(weights["max_stabilized_weight"], 0.9091922784948523)
        self.assertAlmostEqual(weights["max_unstabilized_weight"], 1.5638398200583674)
        self.assertAlmostEqual(weights["stabilized_effective_sample_size"], 9.555331641172497)
        self.assertAlmostEqual(
            weights["treated_unstabilized_effective_sample_size"],
            5.833947041739177,
        )
        self.assertAlmostEqual(
            weights["control_unstabilized_effective_sample_size"],
            3.9515787093124097,
        )
        self.assertTrue(check(report, "effective_sample_size_above_minimum")["valid"])

    def test_aipw_formula_matches_manual_unit_level_reconstruction(self) -> None:
        report = self.estimate()
        rows = report["primary_estimator"]["unit_scores"]
        manual = sum(
            (row["m1"] - row["m0"])
            + row["treatment"] * (row["outcome"] - row["m1"]) / row["propensity_score"]
            - (1 - row["treatment"]) * (row["outcome"] - row["m0"]) / (1 - row["propensity_score"])
            for row in rows
        ) / len(rows)
        self.assertAlmostEqual(manual, report["summary"]["aipw_ate"])
        self.assertTrue(check(report, "manual_outcome_ols_matches_statsmodels")["valid"])

    def test_trimming_sensitivity_reports_population_change_and_estimate_shift(self) -> None:
        report = self.estimate()
        trim_005 = trim_row(report, 0.05)
        self.assertEqual(trim_005["removed_user_ids"], ["U001"])
        self.assertAlmostEqual(trim_005["ipw_hajek_ate"], -0.14365619458096424)
        trim_020 = trim_row(report, 0.2)
        self.assertEqual(trim_020["retained_n"], 6)
        self.assertEqual(trim_020["removed_user_ids"], ["U001", "U002", "U005", "U010"])
        self.assertAlmostEqual(trim_020["aipw_ate"], -0.4180284019860759)
        material = check(report, "trimming_changes_target_population_materially")
        self.assertFalse(material["valid"])
        self.assertEqual([row["threshold"] for row in material["sample"]], [0.2, 0.25])

    def test_stress_tests_show_misspecified_models_move_estimates(self) -> None:
        report = self.estimate()
        treatment_stress = stress(report, "misspecified_treatment_friction_capacity")
        outcome_stress = stress(report, "misspecified_outcome_friction_capacity")
        self.assertAlmostEqual(treatment_stress["estimates"]["ipw_hajek_ate"], 0.07385687546522224)
        self.assertAlmostEqual(treatment_stress["estimates"]["aipw_ate"], -0.24107575155241906)
        self.assertGreater(treatment_stress["weights"]["max_stabilized_weight"], 1.5)
        self.assertAlmostEqual(
            outcome_stress["estimates"]["outcome_regression_ate"], 0.08178163351671623
        )
        self.assertAlmostEqual(outcome_stress["estimates"]["aipw_ate"], 0.06730396752272716)

    def test_primary_design_uses_allowed_sources_and_candidate_statuses_match(self) -> None:
        report = self.estimate()
        self.assertTrue(check(report, "primary_models_use_only_allowed_baseline_sources")["valid"])
        self.assertTrue(check(report, "primary_models_cover_required_adjustment_sources")["valid"])
        self.assertTrue(check(report, "candidate_estimator_statuses_match_policy")["valid"])
        primary = candidate(report, "ridge_dr_baseline_risk_v1")
        self.assertEqual(primary["calculated_status"], "estimable_with_warnings")
        self.assertEqual(primary["bad_control_variables"], [])
        self.assertEqual(primary["missing_propensity_sources"], [])
        self.assertEqual(primary["missing_outcome_sources"], [])

    def test_bad_control_and_omitted_source_candidates_are_rejected(self) -> None:
        report = self.estimate()
        propensity_only = candidate(report, "propensity_friction_capacity_only")
        outcome_only = candidate(report, "outcome_friction_capacity_only")
        mediator = candidate(report, "mediator_augmented_outcome_model")
        complete_case = candidate(report, "telemetry_complete_case_weighting")
        self.assertEqual(
            propensity_only["calculated_status"],
            "invalid_omits_required_adjustment_sources",
        )
        self.assertIn("platform", propensity_only["missing_propensity_sources"])
        self.assertEqual(
            outcome_only["calculated_status"], "invalid_omits_required_adjustment_sources"
        )
        self.assertIn("network_quality", outcome_only["missing_outcome_sources"])
        self.assertEqual(mediator["calculated_status"], "invalid_bad_control")
        self.assertEqual(mediator["bad_control_variables"], ["onboarding_completed_48h"])
        self.assertEqual(complete_case["calculated_status"], "invalid_bad_control")
        self.assertEqual(complete_case["bad_control_variables"], ["telemetry_complete_30d"])

    def test_candidate_declared_status_must_match_policy(self) -> None:
        spec = copy.deepcopy(self.estimator_spec)
        spec["candidate_estimators"][1]["declared_status"] = "estimable_with_warnings"
        report = self.estimate(estimator_spec=spec)
        status = check(report, "candidate_estimator_statuses_match_policy")
        self.assertFalse(report["valid"])
        self.assertFalse(status["valid"])
        self.assertEqual(status["sample"][0]["estimator_id"], "propensity_friction_capacity_only")

    def test_effect_claim_cannot_be_enabled_with_unmeasured_backdoor_path(self) -> None:
        spec = copy.deepcopy(self.estimator_spec)
        spec["claim_policy"]["allowed_effect_claim"] = True
        report = self.estimate(estimator_spec=spec)
        claim = check(report, "claim_policy_respects_unmeasured_confounding_limitation")
        self.assertFalse(report["valid"])
        self.assertFalse(claim["valid"])
        self.assertEqual(claim["sample"][0]["field"], "allowed_effect_claim")

    def test_primary_bad_control_source_is_blocked_before_estimation(self) -> None:
        spec = copy.deepcopy(self.estimator_spec)
        spec["outcome_model"]["terms"].append("onboarding_completed_48h")
        spec["outcome_model"]["direct_numeric_terms"].append("onboarding_completed_48h")
        report = self.estimate(estimator_spec=spec)
        source = check(report, "primary_models_use_only_allowed_baseline_sources")
        self.assertFalse(report["valid"])
        self.assertFalse(source["valid"])
        self.assertIn("onboarding_completed_48h", source["sample"]["outcome_bad_controls"])

    def test_primary_missing_required_sources_are_blocked(self) -> None:
        spec = copy.deepcopy(self.estimator_spec)
        spec["propensity_model"] = copy.deepcopy(spec["stress_tests"][0]["propensity_model"])
        report = self.estimate(estimator_spec=spec)
        coverage = check(report, "primary_models_cover_required_adjustment_sources")
        self.assertFalse(report["valid"])
        self.assertFalse(coverage["valid"])
        self.assertIn("acquisition_channel", coverage["sample"]["propensity_missing_sources"])

    def test_invalid_trimming_threshold_blocks_spec(self) -> None:
        spec = copy.deepcopy(self.estimator_spec)
        spec["diagnostics"]["trim_thresholds"].append(0.5)
        report = self.estimate(estimator_spec=spec)
        trimming = check(report, "trimming_thresholds_are_inside_probability_range")
        self.assertFalse(report["valid"])
        self.assertFalse(trimming["valid"])
        self.assertEqual(trimming["sample"], [0.5])

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
            assistance.loc[assistance["user_id"] == "U006", "started_at"] = (
                "2026-07-05T21:30:00+03:00"
            )
            assistance.to_csv(tmp / "onboarding_assistance.csv", index=False)
            report = self.estimate(data_dir=tmp)
            timing = check(report, "treatment_timing_respects_grace_period")
            self.assertFalse(report["valid"])
            self.assertFalse(timing["valid"])
            self.assertEqual(timing["sample"][0]["user_id"], "U006")

    def test_incomplete_outcome_followup_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            outcomes = pd.read_csv(tmp / "outcomes.csv")
            outcomes.loc[outcomes["user_id"] == "U001", "followup_end_at"] = (
                "2026-07-07T10:00:00+03:00"
            )
            outcomes.to_csv(tmp / "outcomes.csv", index=False)
            report = self.estimate(data_dir=tmp)
            followup = check(report, "primary_outcome_followup_is_complete")
            self.assertFalse(report["valid"])
            self.assertFalse(followup["valid"])
            self.assertEqual(followup["sample"][0]["user_id"], "U001")

    def test_cli_fail_on_invalid_exits_nonzero_for_invalid_claim_policy(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            spec = copy.deepcopy(self.estimator_spec)
            spec["claim_policy"]["allowed_effect_claim"] = True
            spec_path = tmp / "invalid_spec.json"
            output_path = tmp / "report.json"
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
            self.assertIn(
                "claim_policy_respects_unmeasured_confounding_limitation",
                payload["summary"]["blocking_checks"],
            )

    def test_committed_report_exists_and_matches_artifact_summary(self) -> None:
        report = read_json(REPORT)
        fresh = self.estimate()
        self.assertEqual(report["summary"], fresh["summary"])
        self.assertEqual(
            report["primary_estimator"]["overlap"],
            fresh["primary_estimator"]["overlap"],
        )


if __name__ == "__main__":
    unittest.main()
