from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
REPO_ROOT = LESSON_ROOT.parents[2]
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
ARTIFACT = LESSON_ROOT / "outputs" / "cost_sensitive_decision_evaluator.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from cost_sensitive_decision_evaluator import run, write_outputs  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class CostSensitiveDecisionEvaluatorTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, **paths: Path) -> dict:
        return run(
            policy_path=paths.get("policy_path", root / "cost_sensitive_decision_policy_spec.json"),
        )

    def test_valid_report_keeps_threshold_choice_on_validation(self) -> None:
        report = self.audit()
        summary = report["summary"]

        self.assertTrue(report["valid"])
        self.assertEqual(summary["cost_sensitive_decision_audit_id"], "trial-churn-cost-sensitive-decision-audit-v0")
        self.assertEqual(summary["analysis_split"], "validation")
        self.assertEqual(summary["final_holdout_split"], "test")
        self.assertEqual(summary["false_positive_cost"], 1.0)
        self.assertEqual(summary["false_negative_cost"], 5.0)
        self.assertEqual(summary["budget_max_actions"], 2)
        self.assertEqual(summary["baseline_selected_threshold"], 0.5)
        self.assertEqual(summary["catboost_selected_threshold"], 1.0)
        self.assertEqual(summary["baseline_best_total_error_cost"], 0.0)
        self.assertEqual(summary["catboost_best_total_error_cost"], 5.0)
        self.assertEqual(summary["candidate_cost_delta_vs_baseline"], 5.0)
        self.assertEqual(summary["baseline_top_k_total_error_cost"], 1.0)
        self.assertEqual(summary["catboost_top_k_total_error_cost"], 7.0)
        self.assertEqual(summary["candidate_top_k_cost_delta_vs_baseline"], 6.0)
        self.assertEqual(summary["decision_status"], "do_not_promote_catboost_candidate")
        self.assertEqual(summary["readiness_status"], "ready_for_optuna_lesson")

    def test_decision_rows_compare_same_population_and_expose_calibration_status(self) -> None:
        report = self.audit()
        rows = {(row["model_role"], row["snapshot_id"]): row for row in report["decision_rows"]}

        self.assertEqual({snapshot_id for _, snapshot_id in rows}, {"S005", "S006", "S007"})
        self.assertEqual(rows[("baseline", "S006")]["score"], 0.555556)
        self.assertEqual(rows[("baseline", "S006")]["score_source"], "calibrated_score")
        self.assertEqual(rows[("baseline", "S006")]["calibration_status"], "approved_phase15_validation_bin_map")
        self.assertEqual(rows[("baseline", "S005")]["score_rank"], 2)
        self.assertEqual(rows[("baseline", "S007")]["score_rank"], 3)
        self.assertEqual(rows[("catboost", "S007")]["score"], 0.507692)
        self.assertEqual(rows[("catboost", "S006")]["score"], 0.492308)
        self.assertEqual(rows[("catboost", "S006")]["calibration_status"], "not_approved_for_candidate")
        self.assertFalse(rows[("catboost", "S006")]["upstream_selected_at_budget"])
        population_check = check(report, "decision_rows_cover_same_validation_population")
        self.assertTrue(population_check["valid"])
        self.assertEqual(list(population_check["observed"]), ["baseline", "catboost"])

    def test_threshold_table_shows_under_budget_and_over_budget_options(self) -> None:
        report = self.audit()
        rows = {
            (row["model_role"], row["threshold"]): row
            for row in report["threshold_comparison"]
        }

        baseline = rows[("baseline", 0.5)]
        self.assertTrue(baseline["threshold_selected"])
        self.assertEqual(baseline["selected_ids"], "S006")
        self.assertEqual(baseline["tp"], 1)
        self.assertEqual(baseline["fp"], 0)
        self.assertEqual(baseline["fn"], 0)
        self.assertEqual(baseline["total_error_cost"], 0.0)

        fixed_catboost = rows[("catboost", 0.5)]
        self.assertFalse(fixed_catboost["threshold_selected"])
        self.assertEqual(fixed_catboost["selected_ids"], "S007")
        self.assertEqual(fixed_catboost["false_positive_ids"], "S007")
        self.assertEqual(fixed_catboost["false_negative_ids"], "S006")
        self.assertEqual(fixed_catboost["total_error_cost"], 6.0)

        inclusive_tie = rows[("catboost", 0.492308)]
        self.assertEqual(inclusive_tie["selected_ids"], "S007,S005,S006")
        self.assertEqual(inclusive_tie["budget_status"], "over_budget")
        self.assertFalse(inclusive_tie["threshold_is_budget_eligible"])
        self.assertEqual(inclusive_tie["total_error_cost"], 2.0)

        no_action = rows[("catboost", 1.0)]
        self.assertTrue(no_action["threshold_selected"])
        self.assertEqual(no_action["action_count"], 0)
        self.assertEqual(no_action["false_negative_ids"], "S006")
        self.assertEqual(no_action["total_error_cost"], 5.0)

    def test_budget_impact_and_gate_block_candidate_promotion(self) -> None:
        report = self.audit()
        impact = {
            (row["model_role"], row["decision_rule"]): row
            for row in report["budget_impact"]
        }
        gates = {row["gate_id"]: row for row in report["decision_gate"]}

        self.assertEqual(impact[("baseline", "top_k_budget_policy")]["selected_ids"], "S006,S005")
        self.assertEqual(impact[("baseline", "top_k_budget_policy")]["total_error_cost"], 1.0)
        self.assertEqual(impact[("catboost", "top_k_budget_policy")]["selected_ids"], "S007,S005")
        self.assertEqual(impact[("catboost", "top_k_budget_policy")]["false_negative_ids"], "S006")
        self.assertEqual(impact[("catboost", "top_k_budget_policy")]["total_error_cost"], 7.0)
        self.assertEqual(impact[("catboost", "fixed_threshold_0_5_diagnostic")]["total_error_cost"], 6.0)

        self.assertTrue(gates["final_holdout_excluded_from_threshold_selection"]["passed"])
        self.assertFalse(gates["candidate_threshold_cost_lte_baseline_best"]["passed"])
        self.assertFalse(gates["candidate_top_k_cost_lte_baseline_top_k"]["passed"])
        self.assertFalse(gates["candidate_has_approved_calibration"]["passed"])
        self.assertFalse(gates["segment_hidden_failures_absent"]["passed"])
        self.assertTrue(gates["no_causal_offer_effect_claim"]["passed"])
        self.assertFalse(gates["promotion_requires_all_gates"]["passed"])

    def test_warnings_name_cost_calibration_segment_and_causal_boundaries(self) -> None:
        report = self.audit()

        self.assertEqual(report["summary"]["blocking_errors"], [])
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "candidate_not_promoted_due_to_decision_gate",
                "candidate_score_is_not_calibrated",
                "catboost_threshold_cost_worse_than_baseline",
                "catboost_top_k_budget_cost_worse_than_baseline",
                "segment_warnings_propagated_to_decision_gate",
                "no_causal_offer_effect_boundary_visible",
            ],
        )
        self.assertEqual(check(report, "candidate_score_is_not_calibrated")["severity"], "warning")
        self.assertEqual(check(report, "catboost_top_k_budget_cost_worse_than_baseline")["observed"]["candidate_top_k_total_error_cost"], 7.0)
        self.assertIn("candidate_worse_than_baseline_on_validation", check(report, "segment_warnings_propagated_to_decision_gate")["observed"])

    def test_serialized_spec_keeps_selection_summary_and_upstream_handoff(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["analysis_split"], "validation")
        self.assertEqual(serialized["threshold_policy"]["selection_data"], "validation")
        self.assertEqual(serialized["selection_summary"]["baseline_selected_threshold"], 0.5)
        self.assertEqual(serialized["selection_summary"]["catboost_selected_threshold"], 1.0)
        self.assertEqual(serialized["selection_summary"]["baseline_threshold_selected_ids"], ["S006"])
        self.assertEqual(serialized["selection_summary"]["catboost_threshold_selected_ids"], [])
        self.assertEqual(serialized["selection_summary"]["catboost_top_k_selected_ids"], ["S007", "S005"])
        self.assertEqual(serialized["upstream_handoff"]["calibration_readiness_status"], "ready_for_leakage_lesson")
        self.assertEqual(serialized["upstream_handoff"]["segment_readiness_status"], "ready_for_cost_sensitive_decision_lesson")

    def test_policy_blocks_threshold_selection_on_final_holdout(self) -> None:
        with TemporaryDirectory() as directory:
            policy_path = Path(directory) / "cost_sensitive_decision_policy_spec.json"
            policy = read_json(DATA_ROOT / "cost_sensitive_decision_policy_spec.json")
            policy["threshold_policy"]["selection_data"] = "test"
            write_json(policy_path, policy)

            report = self.audit(policy_path=policy_path)

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["readiness_status"], "blocked_before_cost_sensitive_decision")
        self.assertEqual(report["summary"]["blocking_errors"], ["threshold_selection_uses_validation_only"])
        self.assertFalse(check(report, "threshold_selection_uses_validation_only")["valid"])

    def test_writer_and_lesson_cli_export_expected_outputs(self) -> None:
        report = self.audit()
        with TemporaryDirectory() as directory:
            output_root = Path(directory)
            output_spec = read_json(DATA_ROOT / "cost_sensitive_decision_policy_spec.json")["output"]
            write_outputs(report, output_root, output_spec)

            threshold_rows = read_csv(output_root / "threshold_comparison.csv")
            gate_rows = read_csv(output_root / "decision_gate.csv")

        self.assertEqual(len(threshold_rows), 10)
        self.assertEqual(len(gate_rows), 7)

        completed = subprocess.run(
            [sys.executable, str(CODE)],
            check=True,
            text=True,
            capture_output=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["catboost_top_k_total_error_cost"], 7.0)
        self.assertEqual(payload["decision_status"], "do_not_promote_catboost_candidate")
        self.assertEqual(payload["readiness_status"], "ready_for_optuna_lesson")

    def test_artifact_cli_output_root_writes_all_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            output_root = Path(directory)
            completed = subprocess.run(
                [sys.executable, str(ARTIFACT), "--output-root", str(output_root)],
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.stdout, "")
            self.assertTrue((output_root / "cost_sensitive_decision_report.json").is_file())
            self.assertTrue((output_root / "cost_sensitive_decision_rows.csv").is_file())
            self.assertTrue((output_root / "threshold_comparison.csv").is_file())
            self.assertTrue((output_root / "budget_impact.csv").is_file())
            self.assertTrue((output_root / "decision_gate.csv").is_file())
            self.assertEqual(read_json(output_root / "cost_sensitive_decision_report.json")["summary"]["catboost_best_total_error_cost"], 5.0)
