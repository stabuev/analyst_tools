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
MATCHING_SPEC = ROOT / "outputs" / "matching_spec.json"
REPORT = ROOT / "outputs" / "matching_report.json"
ARTIFACT = ROOT / "outputs" / "matching_pipeline.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("matching_pipeline", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
MATCHING = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(MATCHING)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def candidate(report: dict, design_id: str) -> dict:
    return next(
        item
        for item in report["policy_context"]["candidate_matching_design_audits"]
        if item["design_id"] == design_id
    )


def candidate_spec(spec: dict, design_id: str) -> dict:
    return next(
        item for item in spec["candidate_matching_designs"] if item["design_id"] == design_id
    )


def distance(report: dict, treated_id: str, control_id: str) -> dict:
    return next(
        item
        for item in report["distance"]["matrix"]
        if item["treated_user_id"] == treated_id and item["control_user_id"] == control_id
    )


def balance_row(report: dict, feature: str) -> dict:
    return next(item for item in report["balance"]["balance_table"] if item["feature"] == feature)


class MatchingPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.target_trial = read_json(TARGET_TRIAL)
        self.estimand = read_json(ESTIMAND)
        self.adjustment_gate = read_json(ADJUSTMENT_GATE)
        self.matching_spec = read_json(MATCHING_SPEC)

    def estimate(
        self,
        *,
        data_dir: Path | None = None,
        target_trial: dict | None = None,
        estimand: dict | None = None,
        adjustment_gate: dict | None = None,
        matching_spec: dict | None = None,
    ) -> dict:
        return MATCHING.estimate_matching(
            DATA_DIR if data_dir is None else data_dir,
            self.target_trial if target_trial is None else target_trial,
            self.estimand if estimand is None else estimand,
            self.adjustment_gate if adjustment_gate is None else adjustment_gate,
            self.matching_spec if matching_spec is None else matching_spec,
        )

    def test_valid_report_matches_expected_tiny_matching_numbers(self) -> None:
        report = self.estimate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["cohort_n"], 10)
        self.assertEqual(report["summary"]["treated_n"], 6)
        self.assertEqual(report["summary"]["comparator_n"], 4)
        self.assertEqual(report["summary"]["matched_treated_n"], 4)
        self.assertEqual(report["summary"]["unmatched_treated_n"], 2)
        self.assertAlmostEqual(report["summary"]["matched_treated_fraction"], 2 / 3)
        self.assertEqual(report["summary"]["unique_controls_used_n"], 3)
        self.assertEqual(report["summary"]["reused_controls"], {"U005": 2})
        self.assertAlmostEqual(report["summary"]["naive_risk_difference"], -1 / 12)
        self.assertAlmostEqual(report["summary"]["matched_treated_risk"], 0.5)
        self.assertAlmostEqual(report["summary"]["matched_control_risk"], 0.75)
        self.assertAlmostEqual(report["summary"]["matched_att"], -0.25)
        self.assertEqual(report["summary"]["blocking_checks"], [])

    def test_code_example_prints_transferable_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["matching_valid"])
        self.assertEqual(payload["cohort_n"], 10)
        self.assertEqual(payload["matched_treated_n"], 4)
        self.assertEqual(payload["unmatched_treated_n"], 2)
        self.assertEqual(payload["matched_att"], -0.25)
        self.assertEqual(payload["naive_risk_difference"], -0.083333)
        self.assertFalse(payload["effect_claim_allowed"])
        self.assertIn("treated_units_without_common_support_match", payload["warning_checks"])

    def test_manual_distance_matrix_matches_scipy_cdist(self) -> None:
        report = self.estimate()
        scipy_check = check(report, "manual_distance_matrix_matches_scipy_cdist")
        self.assertTrue(scipy_check["valid"])
        self.assertLess(report["distance"]["max_manual_scipy_diff"], 1e-12)
        d = distance(report, "U003", "U005")
        self.assertAlmostEqual(d["distance"], 1.0913493271991717)
        self.assertAlmostEqual(d["distance"], d["scipy_distance"])

    def test_nearest_neighbor_pairs_and_replacement_are_visible(self) -> None:
        report = self.estimate()
        pairs = [
            (pair["treated_user_id"], pair["control_user_id"], round(pair["distance"], 6))
            for pair in report["matching"]["matched_pairs"]
        ]
        self.assertEqual(
            pairs,
            [
                ("U003", "U005", 1.091349),
                ("U004", "U011", 0.21827),
                ("U006", "U007", 0.327405),
                ("U010", "U005", 1.309619),
            ],
        )
        self.assertEqual(report["summary"]["reused_controls"], {"U005": 2})
        self.assertAlmostEqual(report["summary"]["max_matched_distance"], 1.309619192639006)

    def test_common_support_warning_lists_unmatched_treated_units(self) -> None:
        report = self.estimate()
        support = check(report, "treated_units_without_common_support_match")
        self.assertFalse(support["valid"])
        self.assertEqual(support["severity"], "warning")
        self.assertEqual([item["treated_user_id"] for item in support["sample"]], ["U001", "U002"])
        self.assertAlmostEqual(support["sample"][1]["nearest_distance"], 1.6370239907987574)
        self.assertIn(support["id"], report["summary"]["warning_checks"])

    def test_balance_table_and_love_plot_show_improvement_and_remaining_imbalance(self) -> None:
        report = self.estimate()
        friction = balance_row(report, "friction_score")
        capacity = balance_row(report, "specialist_capacity")
        baseline = balance_row(report, "baseline_risk_score")
        self.assertLess(friction["abs_smd_after"], friction["abs_smd_before"])
        self.assertEqual(capacity["abs_smd_after"], 0.0)
        self.assertGreater(baseline["abs_smd_after"], baseline["abs_smd_before"])
        self.assertEqual(baseline["status_after"], "imbalanced")
        self.assertIn("baseline_risk_score", report["summary"]["features_worse_after_matching"])
        self.assertEqual(
            set(report["summary"]["features_above_threshold_after"]),
            {"friction_score", "baseline_risk_score", "activation_14d_pre"},
        )
        love_plot_features = {row["feature"] for row in report["balance"]["love_plot_data"]}
        self.assertIn("friction_score", love_plot_features)
        self.assertIn("baseline_risk_score", love_plot_features)

    def test_matching_estimate_changes_population_not_full_ate(self) -> None:
        report = self.estimate()
        self.assertEqual(report["summary"]["matched_unique_units_n"], 7)
        self.assertEqual(
            report["summary"]["matched_unit_ids"],
            ["U003", "U004", "U005", "U006", "U007", "U010", "U011"],
        )
        self.assertEqual(
            report["matching"]["unmatched_treated"][0]["reason"],
            "nearest_distance_above_caliper",
        )
        self.assertEqual(
            report["matching"]["unmatched_treated"][0]["nearest_control_user_id"],
            "U005",
        )

    def test_primary_design_uses_allowed_sources_and_candidate_statuses_match(self) -> None:
        report = self.estimate()
        self.assertTrue(check(report, "matching_uses_only_allowed_baseline_sources")["valid"])
        self.assertTrue(
            check(report, "matching_source_basis_covers_allowed_adjustment_sources")["valid"]
        )
        self.assertTrue(check(report, "candidate_matching_design_statuses_match_policy")["valid"])
        primary = candidate(report, "nearest_neighbor_friction_capacity_att_v1")
        self.assertEqual(primary["calculated_status"], "estimable_with_warnings")
        self.assertEqual(primary["bad_control_variables"], [])
        self.assertEqual(primary["omitted_allowed_sources"], [])

    def test_forced_no_caliper_and_no_replacement_candidates_are_rejected(self) -> None:
        report = self.estimate()
        forced = candidate(report, "forced_no_caliper_all_treated_match")
        no_replacement = candidate(report, "no_replacement_full_att_match")
        self.assertEqual(forced["calculated_status"], "invalid_common_support_policy")
        self.assertEqual(
            no_replacement["calculated_status"],
            "invalid_insufficient_controls_for_full_att",
        )

    def test_bad_control_matching_sources_and_filters_are_rejected(self) -> None:
        report = self.estimate()
        mediator = candidate(report, "mediator_outcome_matching")
        complete_case = candidate(report, "telemetry_complete_case_matching")
        self.assertEqual(mediator["calculated_status"], "invalid_bad_control")
        self.assertEqual(mediator["bad_control_variables"], ["onboarding_completed_48h"])
        self.assertEqual(complete_case["calculated_status"], "invalid_bad_control")
        self.assertEqual(complete_case["bad_control_variables"], ["telemetry_complete_30d"])

    def test_candidate_declared_status_must_match_policy(self) -> None:
        spec = copy.deepcopy(self.matching_spec)
        candidate_spec(spec, "forced_no_caliper_all_treated_match")["declared_status"] = (
            "estimable_with_warnings"
        )
        report = self.estimate(matching_spec=spec)
        status = check(report, "candidate_matching_design_statuses_match_policy")
        self.assertFalse(report["valid"])
        self.assertFalse(status["valid"])
        self.assertEqual(status["sample"][0]["design_id"], "forced_no_caliper_all_treated_match")

    def test_effect_claim_cannot_be_enabled_with_unmeasured_backdoor_path(self) -> None:
        spec = copy.deepcopy(self.matching_spec)
        spec["claim_policy"]["allowed_effect_claim"] = True
        report = self.estimate(matching_spec=spec)
        claim = check(report, "claim_policy_respects_unmeasured_confounding_limitation")
        self.assertFalse(report["valid"])
        self.assertFalse(claim["valid"])
        self.assertEqual(claim["sample"][0]["field"], "allowed_effect_claim")

    def test_matching_design_source_bad_control_is_blocked(self) -> None:
        spec = copy.deepcopy(self.matching_spec)
        spec["matching_design"]["source_variables"].append("onboarding_completed_48h")
        spec["matching_design"]["distance_features"].append("onboarding_completed_48h")
        report = self.estimate(matching_spec=spec)
        source_check = check(report, "matching_uses_only_allowed_baseline_sources")
        self.assertFalse(report["valid"])
        self.assertFalse(source_check["valid"])
        self.assertIn("onboarding_completed_48h", source_check["sample"]["bad_control_variables"])

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

    def test_cli_returns_nonzero_for_invalid_claim_policy(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            spec = copy.deepcopy(self.matching_spec)
            spec["claim_policy"]["allowed_effect_claim"] = True
            spec_path = tmp / "matching_spec.json"
            output_path = tmp / "matching_report.json"
            write_json(spec_path, spec)
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
                    "--matching-spec",
                    spec_path,
                    "--output",
                    output_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            report = read_json(output_path)
            self.assertFalse(report["valid"])
            self.assertIn(
                "claim_policy_respects_unmeasured_confounding_limitation",
                report["summary"]["blocking_checks"],
            )


if __name__ == "__main__":
    unittest.main()
