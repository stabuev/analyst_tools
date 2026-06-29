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
DID_SPEC = ROOT / "outputs" / "did_spec.json"
REPORT = ROOT / "outputs" / "did_report.json"
ARTIFACT = ROOT / "outputs" / "did_analyzer.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("did_analyzer", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DID = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(DID)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def candidate(report: dict, design_id: str) -> dict:
    return next(
        item
        for item in report["policy_context"]["candidate_design_audits"]
        if item["design_id"] == design_id
    )


def cell(report: dict, group: str, period: str) -> dict:
    return next(
        item
        for item in report["primary_2x2"]["manual_estimate"]["cell_table"]
        if item["group"] == group and item["period"] == period
    )


def event_row(report: dict, event_time: int) -> dict:
    return next(
        item for item in report["event_study"]["rows"] if item["event_time_weeks"] == event_time
    )


class DidAnalyzerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.did_spec = read_json(DID_SPEC)

    def estimate(
        self,
        *,
        data_dir: Path | None = None,
        did_spec: dict | None = None,
    ) -> dict:
        return DID.estimate_did(
            DATA_DIR if data_dir is None else data_dir,
            self.did_spec if did_spec is None else did_spec,
        )

    def test_valid_report_matches_expected_tiny_did_numbers(self) -> None:
        report = self.estimate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["regions_n"], 2)
        self.assertEqual(report["summary"]["weeks_n"], 8)
        self.assertEqual(report["summary"]["panel_rows_n"], 16)
        self.assertAlmostEqual(report["summary"]["treated_pre_mean"], 0.47)
        self.assertAlmostEqual(report["summary"]["treated_post_mean"], 0.575)
        self.assertAlmostEqual(report["summary"]["treated_change"], 0.105)
        self.assertAlmostEqual(report["summary"]["control_pre_mean"], 0.45)
        self.assertAlmostEqual(report["summary"]["control_post_mean"], 0.475)
        self.assertAlmostEqual(report["summary"]["control_change"], 0.025)
        self.assertAlmostEqual(report["summary"]["did_estimate"], 0.08)
        self.assertAlmostEqual(report["summary"]["twfe_coefficient"], 0.08)
        self.assertEqual(report["summary"]["blocking_checks"], [])

    def test_code_example_prints_transferable_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["did_valid"])
        self.assertEqual(payload["panel_rows_n"], 16)
        self.assertEqual(payload["treated_region"], "north")
        self.assertEqual(payload["control_region"], "south")
        self.assertEqual(payload["treated_change"], 0.105)
        self.assertEqual(payload["control_change"], 0.025)
        self.assertEqual(payload["did_estimate"], 0.08)
        self.assertEqual(payload["twfe_coefficient"], 0.08)
        self.assertEqual(payload["fake_pre_placebo_did"], 0.0)
        self.assertTrue(payload["effect_claim_allowed"])
        self.assertIn("twfe_is_diagnostic_only_for_staggered_adoption", payload["warning_checks"])

    def test_four_cell_manual_accounting_is_explicit(self) -> None:
        report = self.estimate()
        self.assertEqual(
            cell(report, "treated", "pre")["week_starts"],
            [
                "2026-06-15",
                "2026-06-22",
                "2026-06-29",
            ],
        )
        self.assertEqual(
            cell(report, "treated", "post")["week_starts"],
            [
                "2026-07-06",
                "2026-07-13",
            ],
        )
        self.assertEqual(cell(report, "control", "post")["rollout_active_values"], [False])
        self.assertTrue(check(report, "manual_2x2_did_matches_saturated_regression")["valid"])
        self.assertAlmostEqual(
            report["primary_2x2"]["saturated_regression"]["interaction_estimate"],
            report["summary"]["did_estimate"],
        )

    def test_pretrend_and_placebo_checks_pass_on_tiny_data(self) -> None:
        report = self.estimate()
        self.assertTrue(check(report, "parallel_pretrend_slope_check_passes")["valid"])
        slopes = {
            row["region_id"]: row["slope_per_week"] for row in report["pretrend_check"]["rows"]
        }
        self.assertAlmostEqual(slopes["north"], 0.01)
        self.assertAlmostEqual(slopes["south"], 0.01)
        fake = check(report, "placebo_fake_rollout_in_pre_period_within_threshold")
        friction = check(report, "placebo_mean_friction_score_should_not_jump_within_threshold")
        self.assertTrue(fake["valid"])
        self.assertTrue(friction["valid"])
        self.assertAlmostEqual(fake["sample"]["did_estimate"], 0.0)
        self.assertAlmostEqual(friction["sample"]["did_estimate"], 0.0)

    def test_event_study_table_has_reference_and_sparse_tail_warning(self) -> None:
        report = self.estimate()
        self.assertTrue(check(report, "event_study_has_reference_period")["valid"])
        self.assertAlmostEqual(report["event_study"]["reference_mean"], 0.48)
        self.assertAlmostEqual(event_row(report, -3)["relative_to_reference"], -0.02)
        self.assertAlmostEqual(event_row(report, 0)["relative_to_reference"], 0.09)
        self.assertEqual(event_row(report, 0)["regions"], ["north", "south"])
        sparse = check(report, "event_study_sparse_tails_are_visible")
        self.assertFalse(sparse["valid"])
        self.assertEqual(sparse["severity"], "warning")
        self.assertEqual(sparse["sample"], [-5, -4, 3, 4])

    def test_twfe_is_reconciled_but_diagnostic_only(self) -> None:
        report = self.estimate()
        twfe = report["twfe_diagnostic"]
        self.assertAlmostEqual(twfe["coefficient"], 0.08)
        self.assertAlmostEqual(twfe["statsmodels_coefficient"], 0.08)
        self.assertLess(twfe["manual_statsmodels_max_param_diff"], 1e-10)
        warning = check(report, "twfe_is_diagnostic_only_for_staggered_adoption")
        self.assertFalse(warning["valid"])
        self.assertEqual(warning["severity"], "warning")
        self.assertEqual(warning["sample"]["status"], "diagnostic_only_due_to_staggered_adoption")

    def test_candidate_design_statuses_match_policy(self) -> None:
        report = self.estimate()
        self.assertTrue(check(report, "candidate_design_statuses_match_policy")["valid"])
        self.assertEqual(
            candidate(report, "north_rollout_vs_south_not_yet_2x2")["calculated_status"],
            "estimable_with_assumptions",
        )
        self.assertEqual(
            candidate(report, "fake_pre_rollout_placebo")["calculated_status"],
            "placebo_check",
        )
        self.assertEqual(
            candidate(report, "south_late_vs_north_already_treated")["calculated_status"],
            "invalid_already_treated_control",
        )
        self.assertEqual(
            candidate(report, "naive_twfe_full_staggered_panel")["calculated_status"],
            "diagnostic_only_staggered_risk",
        )

    def test_candidate_declared_status_must_match_policy(self) -> None:
        spec = copy.deepcopy(self.did_spec)
        spec["candidate_designs"][2]["declared_status"] = "estimable_with_assumptions"
        report = self.estimate(did_spec=spec)
        status = check(report, "candidate_design_statuses_match_policy")
        self.assertFalse(report["valid"])
        self.assertFalse(status["valid"])
        self.assertEqual(status["sample"][0]["design_id"], "south_late_vs_north_already_treated")

    def test_primary_control_cannot_be_treated_inside_post_window(self) -> None:
        spec = copy.deepcopy(self.did_spec)
        spec["primary_2x2"]["post_window"]["end"] = "2026-07-20"
        report = self.estimate(did_spec=spec)
        support = check(report, "primary_control_is_not_yet_treated_in_post_window")
        self.assertFalse(report["valid"])
        self.assertFalse(support["valid"])
        self.assertEqual(support["sample"]["control_errors"][0]["region_id"], "south")

    def test_event_reference_period_must_exist(self) -> None:
        spec = copy.deepcopy(self.did_spec)
        spec["event_study"]["reference_event_time"] = -99
        report = self.estimate(did_spec=spec)
        reference = check(report, "event_study_has_reference_period")
        self.assertFalse(report["valid"])
        self.assertFalse(reference["valid"])
        self.assertEqual(reference["sample"]["reference_event_time"], -99)

    def test_duplicate_region_week_blocks_panel_build(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            panel = pd.read_csv(tmp / "region_week_panel.csv")
            panel = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
            panel.to_csv(tmp / "region_week_panel.csv", index=False)
            report = self.estimate(data_dir=tmp)
            grain = check(report, "source_tables_preserve_declared_grain")
            self.assertFalse(report["valid"])
            self.assertFalse(grain["valid"])
            self.assertEqual(grain["sample"][0]["table"], "region_week_panel")

    def test_rollout_active_must_match_calendar(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            panel = pd.read_csv(tmp / "region_week_panel.csv")
            panel.loc[
                (panel["region_id"] == "south") & (panel["week_start"] == "2026-07-13"),
                "rollout_active",
            ] = True
            panel.to_csv(tmp / "region_week_panel.csv", index=False)
            report = self.estimate(data_dir=tmp)
            calendar = check(report, "rollout_active_matches_calendar")
            self.assertFalse(report["valid"])
            self.assertFalse(calendar["valid"])
            self.assertEqual(calendar["sample"][0]["region_id"], "south")

    def test_failed_pretrend_blocks_limited_effect_claim(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            panel = pd.read_csv(tmp / "region_week_panel.csv")
            panel.loc[
                (panel["region_id"] == "south") & (panel["week_start"] == "2026-06-29"),
                "activation_rate_14d",
            ] = 0.52
            panel.to_csv(tmp / "region_week_panel.csv", index=False)
            report = self.estimate(data_dir=tmp)
            pretrend = check(report, "parallel_pretrend_slope_check_passes")
            claim = check(report, "claim_policy_requires_passing_design_assumptions")
            self.assertFalse(report["valid"])
            self.assertFalse(pretrend["valid"])
            self.assertFalse(claim["valid"])
            self.assertIn("parallel_pretrend_slope_check_passes", claim["sample"])

    def test_failed_placebo_blocks_limited_effect_claim(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            shutil.copytree(DATA_DIR, tmp, dirs_exist_ok=True)
            panel = pd.read_csv(tmp / "region_week_panel.csv")
            panel.loc[
                (panel["region_id"] == "north") & (panel["week_start"] == "2026-06-29"),
                "activation_rate_14d",
            ] = 0.55
            panel.to_csv(tmp / "region_week_panel.csv", index=False)
            report = self.estimate(data_dir=tmp)
            placebo = check(report, "placebo_fake_rollout_in_pre_period_within_threshold")
            claim = check(report, "claim_policy_requires_passing_design_assumptions")
            self.assertFalse(report["valid"])
            self.assertFalse(placebo["valid"])
            self.assertFalse(claim["valid"])
            self.assertIn("placebo_fake_rollout_in_pre_period_within_threshold", claim["sample"])

    def test_scenario_registry_alignment_is_required(self) -> None:
        spec = copy.deepcopy(self.did_spec)
        spec["scenario_id"] = "missing_scenario"
        report = self.estimate(did_spec=spec)
        scenario = check(report, "did_spec_matches_scenario_registry")
        self.assertFalse(report["valid"])
        self.assertFalse(scenario["valid"])
        self.assertEqual(scenario["sample"][0]["scenario_id"], "missing_scenario")

    def test_cli_fail_on_invalid_exits_nonzero_for_bad_post_window(self) -> None:
        with TemporaryDirectory() as directory:
            tmp = Path(directory)
            spec = copy.deepcopy(self.did_spec)
            spec["primary_2x2"]["post_window"]["end"] = "2026-07-20"
            spec_path = tmp / "invalid_did_spec.json"
            output_path = tmp / "did_report.json"
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
                "primary_control_is_not_yet_treated_in_post_window",
                payload["summary"]["blocking_checks"],
            )

    def test_committed_report_exists_and_matches_artifact_summary(self) -> None:
        report = read_json(REPORT)
        fresh = self.estimate()
        self.assertEqual(report["summary"], fresh["summary"])
        self.assertEqual(report["event_study"], fresh["event_study"])


if __name__ == "__main__":
    unittest.main()
