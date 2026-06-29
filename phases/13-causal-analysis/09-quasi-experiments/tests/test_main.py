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
SPEC = ROOT / "outputs" / "quasi_experiment_spec.json"
REPORT = ROOT / "outputs" / "quasi_experiment_report.json"
ARTIFACT = ROOT / "outputs" / "quasi_experiment_design_auditor.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("quasi_experiment_design_auditor", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = AUDITOR
MODULE_SPEC.loader.exec_module(AUDITOR)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def candidate(report: dict, design_id: str) -> dict:
    return next(
        item for item in report["candidate_design_audits"] if item["design_id"] == design_id
    )


class QuasiExperimentDesignAuditorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = read_json(SPEC)

    def audit(
        self,
        *,
        data_dir: Path | None = None,
        spec: dict | None = None,
    ) -> dict:
        return AUDITOR.audit_quasi_experiments(
            DATA_DIR if data_dir is None else data_dir,
            self.spec if spec is None else spec,
        )

    def test_valid_report_matches_expected_tiny_quasi_design_numbers(self) -> None:
        report = self.audit()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["blocking_checks"], [])
        self.assertEqual(report["summary"]["rdd_local_rows_n"], 6)
        self.assertAlmostEqual(report["summary"]["rdd_first_stage"], 2 / 3)
        self.assertAlmostEqual(report["summary"]["rdd_reduced_form"], -2 / 3)
        self.assertAlmostEqual(report["summary"]["rdd_wald_local_effect_diagnostic"], -1.0)
        self.assertEqual(report["summary"]["iv_rows_n"], 10)
        self.assertAlmostEqual(report["summary"]["iv_first_stage"], 0.4)
        self.assertAlmostEqual(report["summary"]["iv_reduced_form"], 0.2)
        self.assertAlmostEqual(report["summary"]["iv_wald_late"], 0.5)
        self.assertTrue(report["summary"]["allowed_local_claim"])
        self.assertEqual(
            report["summary"]["warning_checks"],
            [
                "rdd_tiny_wald_estimate_is_diagnostic_only",
                "iv_exclusion_and_monotonicity_cannot_be_proven_from_observed_data",
            ],
        )

    def test_code_example_prints_transferable_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["quasi_design_valid"])
        self.assertEqual(payload["rdd_design_type"], "fuzzy_rdd")
        self.assertEqual(payload["rdd_local_rows_n"], 6)
        self.assertEqual(payload["rdd_first_stage"], 0.666667)
        self.assertEqual(payload["rdd_wald_local_effect_diagnostic"], -1.0)
        self.assertEqual(payload["iv_first_stage"], 0.4)
        self.assertEqual(payload["iv_wald_late"], 0.5)
        self.assertTrue(payload["allowed_local_claim"])

    def test_rdd_local_window_and_fuzzy_assignment_are_explicit(self) -> None:
        report = self.audit()
        rdd = report["rdd_design_audit"]
        self.assertEqual(rdd["local_window"], [52, 68])
        self.assertEqual(rdd["side_counts"], {"right": 3, "left": 3})
        self.assertEqual(rdd["calculated_design_type"], "fuzzy_rdd")
        self.assertEqual(rdd["sharp_assignment_violations"][0]["user_id"], "U006")
        self.assertEqual(
            rdd["sharp_assignment_violations"][0]["assignment_reason"],
            "manual_override",
        )
        self.assertAlmostEqual(rdd["density_screen"]["density_ratio"], 1.0)
        self.assertAlmostEqual(rdd["continuity_checks"][0]["difference"], 0.0)
        self.assertTrue(check(report, "rdd_assignment_is_fuzzy_not_sharp")["valid"])

    def test_iv_first_stage_reduced_form_and_late_are_explicit(self) -> None:
        report = self.audit()
        iv = report["iv_design_audit"]
        self.assertEqual(iv["instrument_counts"], {"encouraged": 5, "not_encouraged": 5})
        self.assertAlmostEqual(iv["first_stage"]["treatment_rate_z1"], 0.8)
        self.assertAlmostEqual(iv["first_stage"]["treatment_rate_z0"], 0.4)
        self.assertAlmostEqual(iv["reduced_form"]["outcome_rate_z1"], 0.8)
        self.assertAlmostEqual(iv["reduced_form"]["outcome_rate_z0"], 0.6)
        self.assertEqual(iv["declared_estimand"], "LATE")
        self.assertTrue(check(report, "iv_estimand_contract_is_late_not_ate")["valid"])

    def test_candidate_design_statuses_match_policy(self) -> None:
        report = self.audit()
        self.assertTrue(check(report, "candidate_design_statuses_match_policy")["valid"])
        self.assertEqual(
            candidate(report, "primary_fuzzy_score_rdd")["calculated_status"],
            "estimable_local_with_assumptions",
        )
        self.assertEqual(
            candidate(report, "sharp_score_cutoff_offer")["calculated_status"],
            "invalid_requires_fuzzy_rdd",
        )
        self.assertEqual(
            candidate(report, "wide_bandwidth_ignores_locality")["calculated_status"],
            "invalid_not_local",
        )
        self.assertEqual(
            candidate(report, "capacity_encouragement_late")["calculated_status"],
            "estimable_late_with_assumptions",
        )
        self.assertEqual(
            candidate(report, "encouragement_claims_ate")["calculated_status"],
            "invalid_late_generalized_to_ate",
        )
        self.assertEqual(
            candidate(report, "weak_encouragement_variant")["calculated_status"],
            "invalid_weak_instrument",
        )

    def test_candidate_declared_status_must_match_policy(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["iv"]["candidate_designs"][1]["declared_status"] = "estimable_late_with_assumptions"
        report = self.audit(spec=spec)
        status = check(report, "candidate_design_statuses_match_policy")
        self.assertFalse(report["valid"])
        self.assertFalse(status["valid"])
        self.assertEqual(status["sample"][0]["design_id"], "encouragement_claims_ate")

    def test_rdd_cutoff_manipulation_screen_catches_bunching(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            assistance = pd.read_csv(tmp / "onboarding_assistance.csv")
            assistance.loc[assistance["user_id"].isin(["U007", "U012"]), "friction_score"] = 61
            assistance.to_csv(tmp / "onboarding_assistance.csv", index=False)
            report = self.audit(data_dir=tmp)
            density = check(report, "rdd_no_visible_running_variable_bunching_inside_bandwidth")
            self.assertFalse(report["valid"])
            self.assertFalse(density["valid"])
            self.assertGreater(density["sample"]["density_ratio"], 2.0)

    def test_rdd_needs_observations_on_both_sides_of_cutoff(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["rdd"]["bandwidth"] = 1
        report = self.audit(spec=spec)
        support = check(report, "rdd_has_observations_on_both_sides_inside_bandwidth")
        self.assertFalse(report["valid"])
        self.assertFalse(support["valid"])
        self.assertLess(support["sample"]["side_counts"].get("left", 0), 3)

    def test_rdd_covariate_jump_blocks_local_claim_policy(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            assistance = pd.read_csv(tmp / "onboarding_assistance.csv")
            assistance.loc[
                assistance["user_id"].isin(["U004", "U005", "U011"]),
                "specialist_capacity",
            ] = 5
            assistance.to_csv(tmp / "onboarding_assistance.csv", index=False)
            report = self.audit(data_dir=tmp)
            continuity = check(report, "rdd_observed_covariates_are_continuous_at_cutoff")
            claim = check(report, "claim_policy_allows_only_local_rdd_and_late_wording")
            self.assertFalse(report["valid"])
            self.assertFalse(continuity["valid"])
            self.assertFalse(claim["valid"])
            self.assertIn(
                "rdd_observed_covariates_are_continuous_at_cutoff",
                claim["sample"]["failed_required_checks"],
            )

    def test_iv_weak_first_stage_blocks_late_claim(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["iv"]["minimum_first_stage"] = 0.5
        report = self.audit(spec=spec)
        first_stage = check(report, "iv_first_stage_is_relevant_enough_for_tiny_design")
        claim = check(report, "claim_policy_allows_only_local_rdd_and_late_wording")
        self.assertFalse(report["valid"])
        self.assertFalse(first_stage["valid"])
        self.assertFalse(claim["valid"])
        self.assertIn(
            "iv_first_stage_is_relevant_enough_for_tiny_design",
            claim["sample"]["failed_required_checks"],
        )

    def test_iv_late_cannot_be_redeclared_as_ate(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["iv"]["declared_estimand"] = "ATE"
        report = self.audit(spec=spec)
        estimand = check(report, "iv_estimand_contract_is_late_not_ate")
        claim = check(report, "claim_policy_allows_only_local_rdd_and_late_wording")
        self.assertFalse(report["valid"])
        self.assertFalse(estimand["valid"])
        self.assertFalse(claim["valid"])
        self.assertEqual(claim["sample"]["overgeneralized_estimands"], ["ATE"])

    def test_iv_observed_balance_screen_can_fail(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            baseline = pd.read_csv(tmp / "pre_treatment_behavior.csv")
            baseline.loc[
                baseline["user_id"].isin(["U001", "U002", "U003", "U005", "U010"]),
                "app_crashes_before_time_zero",
            ] = 9
            baseline.to_csv(tmp / "pre_treatment_behavior.csv", index=False)
            report = self.audit(data_dir=tmp)
            balance = check(report, "iv_observed_pre_treatment_balance_is_plausible")
            self.assertFalse(report["valid"])
            self.assertFalse(balance["valid"])
            self.assertGreater(abs(balance["sample"][1]["difference"]), 0.25)

    def test_source_table_grain_is_enforced(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            encouragement = pd.read_csv(tmp / "encouragement_assignments.csv")
            encouragement = pd.concat([encouragement, encouragement.iloc[[0]]], ignore_index=True)
            encouragement.to_csv(tmp / "encouragement_assignments.csv", index=False)
            report = self.audit(data_dir=tmp)
            grain = check(report, "source_tables_preserve_declared_grain")
            self.assertFalse(report["valid"])
            self.assertFalse(grain["valid"])
            self.assertEqual(grain["sample"][0]["table"], "encouragement_assignments")

    def test_scenario_registry_alignment_is_required(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["rdd"]["scenario_id"] = "missing_score_rdd"
        report = self.audit(spec=spec)
        scenario = check(report, "quasi_experiment_specs_match_scenario_registry")
        self.assertFalse(report["valid"])
        self.assertFalse(scenario["valid"])
        self.assertEqual(scenario["sample"][0]["scenario_id"], "missing_score_rdd")

    def test_cli_fail_on_invalid_exits_nonzero_for_weak_iv(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            spec = copy.deepcopy(self.spec)
            spec["iv"]["minimum_first_stage"] = 0.5
            spec_path = tmp / "invalid_quasi_spec.json"
            output_path = tmp / "quasi_report.json"
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
                "iv_first_stage_is_relevant_enough_for_tiny_design",
                payload["summary"]["blocking_checks"],
            )

    def test_committed_report_exists_and_matches_artifact_summary(self) -> None:
        report = read_json(REPORT)
        fresh = self.audit()
        self.assertEqual(report["summary"], fresh["summary"])
        self.assertEqual(report["rdd_design_audit"], fresh["rdd_design_audit"])
        self.assertEqual(report["iv_design_audit"], fresh["iv_design_audit"])


if __name__ == "__main__":
    unittest.main()
