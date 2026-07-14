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
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
ARTIFACT = LESSON_ROOT / "outputs" / "optuna_tuning_auditor.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from optuna_tuning_auditor import run, write_outputs  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class OptunaTuningAuditorTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, **paths: Path) -> dict:
        return run(policy_path=paths.get("policy_path", root / "optuna_tuning_policy_spec.json"))

    def test_valid_summary_locks_fixed_budget_validation_only_study(self) -> None:
        report = self.audit()
        summary = report["summary"]

        self.assertTrue(report["valid"])
        self.assertEqual(summary["optuna_tuning_audit_id"], "trial-churn-optuna-tuning-audit-v0")
        self.assertEqual(summary["optuna_version"], "4.9.0")
        self.assertEqual(summary["study_name"], "trial_churn_catboost_fixed_budget_v0")
        self.assertEqual(summary["sampler"], "GridSampler")
        self.assertEqual(summary["sampler_seed"], 1609)
        self.assertEqual(summary["n_trials"], 6)
        self.assertEqual(summary["complete_trial_count"], 6)
        self.assertEqual(summary["fit_split"], "train")
        self.assertEqual(summary["objective_split"], "validation")
        self.assertEqual(summary["final_holdout_split"], "test")
        self.assertFalse(summary["test_used_for_objective"])
        self.assertEqual(summary["source_validation_logloss"], 0.698394)
        self.assertEqual(summary["best_trial_number"], 4)
        self.assertEqual(summary["best_validation_logloss"], 0.696531)
        self.assertEqual(summary["best_depth"], 2)
        self.assertEqual(summary["best_learning_rate"], 0.05)
        self.assertTrue(summary["objective_improved_vs_source"])
        self.assertEqual(summary["best_trial_validation_top_k_cost"], 7.0)
        self.assertEqual(summary["baseline_validation_top_k_cost"], 1.0)
        self.assertTrue(summary["cost_gate_still_fails_vs_baseline"])
        self.assertEqual(summary["decision_status"], "tuned_candidate_ready_for_mlflow_tracking")
        self.assertEqual(summary["readiness_status"], "ready_for_mlflow_lesson")

    def test_trial_ledger_contains_all_complete_trials_and_best_trace(self) -> None:
        report = self.audit()
        ledger = report["trial_ledger"]

        self.assertEqual([row["trial_number"] for row in ledger], [0, 1, 2, 3, 4, 5])
        self.assertEqual([row["depth"] for row in ledger], [1, 1, 2, 1, 2, 2])
        self.assertEqual([row["learning_rate"] for row in ledger], [0.05, 0.2, 0.2, 0.4, 0.05, 0.4])
        self.assertEqual([row["objective_value"] for row in ledger], [0.698842, 0.71759, 0.70728, 0.746454, 0.696531, 0.72301])
        self.assertEqual([row["is_best_trial"] for row in ledger], [False, False, False, False, True, False])
        self.assertTrue(all(row["state"] == "COMPLETE" for row in ledger))
        self.assertTrue(all(row["objective_metric"] == "validation_logloss" for row in ledger))
        self.assertTrue(all(row["direction"] == "minimize" for row in ledger))
        self.assertTrue(all(row["fit_split"] == "train" for row in ledger))
        self.assertTrue(all(row["objective_split"] == "validation" for row in ledger))
        self.assertTrue(all(row["final_holdout_used_for_objective"] is False for row in ledger))
        self.assertTrue(all(row["validation_top_k_selected_ids"] == "S007,S005" for row in ledger))
        self.assertTrue(all(row["validation_top_k_false_negative_ids"] == "S006" for row in ledger))
        self.assertTrue(all(row["validation_fixed_threshold_0_5_total_error_cost"] == 6.0 for row in ledger))
        self.assertTrue(check(report, "trial_ledger_contains_all_trials")["valid"])
        self.assertTrue(check(report, "best_trial_matches_min_validation_objective")["valid"])

    def test_search_space_and_objective_audits_make_no_test_boundary_visible(self) -> None:
        report = self.audit()
        search = {row["parameter"]: row for row in report["search_space_audit"]}
        objective = {row["split"]: row for row in report["objective_audit"]}

        self.assertEqual(search["depth"]["values"], [1, 2])
        self.assertEqual(search["depth"]["value_count"], 2)
        self.assertEqual(search["learning_rate"]["values"], [0.05, 0.2, 0.4])
        self.assertEqual(search["learning_rate"]["value_count"], 3)
        self.assertEqual(search["__grid__"]["value_count"], 6)
        self.assertTrue(all(row["declared_before_study"] for row in report["search_space_audit"]))
        self.assertTrue(all(not row["hidden_search"] for row in report["search_space_audit"]))

        self.assertEqual(objective["train"]["snapshot_ids"], "S001,S002,S003,S004")
        self.assertTrue(objective["train"]["used_for_fit"])
        self.assertFalse(objective["train"]["used_for_objective"])
        self.assertEqual(objective["validation"]["snapshot_ids"], "S005,S006,S007")
        self.assertTrue(objective["validation"]["used_for_objective"])
        self.assertTrue(objective["validation"]["used_for_best_trial_selection"])
        self.assertEqual(objective["test"]["snapshot_ids"], "S009,S010,S011,S012,S013")
        self.assertFalse(objective["test"]["used_for_objective"])
        self.assertFalse(objective["test"]["used_for_best_trial_selection"])
        self.assertTrue(objective["test"]["used_after_selection_for_reporting"])
        self.assertTrue(check(report, "objective_uses_validation_and_excludes_test")["valid"])
        self.assertTrue(check(report, "final_holdout_not_used_for_objective")["valid"])

    def test_predictions_score_final_holdout_only_after_best_trial_selection(self) -> None:
        report = self.audit()
        rows = {(row["split"], row["snapshot_id"]): row for row in report["predictions"]}

        self.assertEqual(rows[("validation", "S005")]["score"], 0.495)
        self.assertEqual(rows[("validation", "S006")]["score"], 0.495)
        self.assertEqual(rows[("validation", "S007")]["score"], 0.505)
        self.assertTrue(rows[("validation", "S006")]["used_for_objective"])
        self.assertFalse(rows[("validation", "S006")]["used_for_final_holdout_reporting"])

        self.assertEqual(rows[("test", "S009")]["score"], 0.505)
        self.assertEqual(rows[("test", "S010")]["score"], 0.495)
        self.assertEqual(rows[("test", "S013")]["score"], 0.495)
        test_rows = [row for row in report["predictions"] if row["split"] == "test"]
        self.assertTrue(test_rows)
        self.assertTrue(all(row["used_for_final_holdout_reporting"] for row in test_rows))
        self.assertTrue(all(not row["used_for_objective"] for row in test_rows))
        self.assertTrue(all(not row["test_used_for_best_trial_selection"] for row in test_rows))
        self.assertTrue(check(report, "test_predictions_are_after_selection_only")["valid"])

    def test_best_trial_trace_keeps_source_best_and_baseline_comparison(self) -> None:
        report = self.audit()
        trace = {row["trace_role"]: row for row in report["best_trial_trace"]}

        source = trace["source_early_stopped_catboost"]
        best = trace["best_optuna_trial"]
        baseline = trace["calibrated_phase15_baseline_cost_gate"]
        self.assertEqual(source["validation_logloss"], 0.698394)
        self.assertEqual(source["validation_top_k_total_error_cost"], 7.0)
        self.assertEqual(best["trial_number"], 4)
        self.assertEqual(best["validation_logloss"], 0.696531)
        self.assertEqual(best["validation_top_k_total_error_cost"], 7.0)
        self.assertEqual(best["validation_top_k_selected_ids"], "S007,S005")
        self.assertEqual(baseline["validation_top_k_total_error_cost"], 1.0)
        self.assertEqual(baseline["validation_top_k_selected_ids"], "S006,S005")
        self.assertFalse(source["test_used_for_selection"])
        self.assertFalse(best["test_used_for_selection"])
        self.assertFalse(baseline["test_used_for_selection"])
        self.assertTrue(check(report, "best_trial_improves_validation_logloss")["valid"])

    def test_warnings_document_tiny_study_and_business_gate_limits(self) -> None:
        report = self.audit()

        self.assertEqual(report["summary"]["blocking_errors"], [])
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "tiny_fixed_budget_study_expected",
                "upstream_candidate_not_promoted_before_tuning",
                "best_trial_logloss_improves_but_cost_gate_still_fails",
                "no_test_objective_boundary_visible",
            ],
        )
        self.assertEqual(check(report, "tiny_fixed_budget_study_expected")["severity"], "warning")
        self.assertEqual(
            check(report, "best_trial_logloss_improves_but_cost_gate_still_fails")["observed"],
            {"best_trial_validation_top_k_cost": 7.0, "baseline_validation_top_k_cost": 1.0},
        )

    def test_serialized_spec_preserves_search_space_best_trial_and_upstream_handoff(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["objective_split"], "validation")
        self.assertEqual(serialized["final_holdout_split"], "test")
        self.assertEqual(serialized["study"]["sampler"]["name"], "GridSampler")
        self.assertEqual(serialized["study"]["sampler"]["seed"], 1609)
        self.assertEqual(serialized["study"]["n_trials"], 6)
        self.assertEqual(serialized["search_space"]["depth"]["values"], [1, 2])
        self.assertEqual(serialized["search_space"]["learning_rate"]["values"], [0.05, 0.2, 0.4])
        self.assertEqual(serialized["best_trial"]["trial_number"], 4)
        self.assertEqual(serialized["best_trial"]["objective_value"], 0.696531)
        self.assertEqual(serialized["best_trial"]["validation_top_k_total_error_cost"], 7.0)
        self.assertEqual(serialized["upstream_handoff"]["early_stopping_readiness_status"], "ready_for_feature_importance_lesson")
        self.assertEqual(serialized["upstream_handoff"]["cost_sensitive_readiness_status"], "ready_for_optuna_lesson")
        self.assertEqual(serialized["upstream_handoff"]["cost_sensitive_decision_status"], "do_not_promote_catboost_candidate")

    def test_policy_blocks_objective_selection_on_final_holdout(self) -> None:
        with TemporaryDirectory() as directory:
            policy_path = Path(directory) / "optuna_tuning_policy_spec.json"
            policy = read_json(DATA_ROOT / "optuna_tuning_policy_spec.json")
            policy["objective_policy"]["selection_data"] = "test"
            write_json(policy_path, policy)

            report = self.audit(policy_path=policy_path)

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["readiness_status"], "blocked_before_optuna_tuning")
        self.assertEqual(report["summary"]["blocking_errors"], ["objective_uses_validation_and_excludes_test"])
        self.assertFalse(check(report, "objective_uses_validation_and_excludes_test")["valid"])
        self.assertEqual(report["trial_ledger"], [])

    def test_writer_and_lesson_cli_export_expected_outputs(self) -> None:
        report = self.audit()
        with TemporaryDirectory() as directory:
            output_root = Path(directory)
            output_spec = read_json(DATA_ROOT / "optuna_tuning_policy_spec.json")["output"]
            write_outputs(report, output_root, output_spec)

            ledger_rows = read_csv(output_root / "optuna_trial_ledger.csv")
            objective_rows = read_csv(output_root / "optuna_objective_audit.csv")
            exported_report = read_json(output_root / "optuna_tuning_report.json")

        self.assertEqual(len(ledger_rows), 6)
        self.assertEqual(len(objective_rows), 3)
        self.assertEqual(exported_report["summary"]["best_trial_number"], 4)

        completed = subprocess.run(
            [sys.executable, str(CODE)],
            check=True,
            text=True,
            capture_output=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["best_trial_number"], 4)
        self.assertEqual(payload["best_validation_logloss"], 0.696531)
        self.assertEqual(payload["best_trial_validation_top_k_cost"], 7.0)
        self.assertTrue(payload["cost_gate_still_fails_vs_baseline"])
        self.assertEqual(payload["readiness_status"], "ready_for_mlflow_lesson")

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
            self.assertTrue((output_root / "optuna_tuning_report.json").is_file())
            self.assertTrue((output_root / "optuna_trial_ledger.csv").is_file())
            self.assertTrue((output_root / "optuna_best_trial_trace.csv").is_file())
            self.assertTrue((output_root / "optuna_tuned_predictions.csv").is_file())
            self.assertTrue((output_root / "optuna_search_space_audit.csv").is_file())
            self.assertTrue((output_root / "optuna_objective_audit.csv").is_file())
            self.assertTrue((output_root / "optuna_tuning_serialized_spec.json").is_file())
            self.assertEqual(read_json(output_root / "optuna_tuning_report.json")["summary"]["decision_status"], "tuned_candidate_ready_for_mlflow_tracking")
