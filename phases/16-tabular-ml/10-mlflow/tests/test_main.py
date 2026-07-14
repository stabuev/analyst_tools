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
ARTIFACT = LESSON_ROOT / "outputs" / "mlflow_experiment_ledger_exporter.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from mlflow_experiment_ledger_exporter import run, write_outputs  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["reproducibility_checks"] if item["id"] == check_id)


class MLflowExperimentLedgerExporterTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, **paths: Path) -> dict:
        return run(policy_path=paths.get("policy_path", root / "mlflow_tracking_policy_spec.json"))

    def test_valid_summary_exports_local_mlflow_ledger_without_raw_run_ids(self) -> None:
        report = self.audit()
        summary = report["summary"]

        self.assertTrue(report["valid"])
        self.assertEqual(summary["mlflow_tracking_audit_id"], "trial-churn-mlflow-tracking-audit-v0")
        self.assertEqual(summary["mlflow_version"], "3.14.0")
        self.assertEqual(summary["tracking_package"], "mlflow-skinny")
        self.assertEqual(summary["experiment_name"], "trial_churn_tabular_ml_local_tracking_v0")
        self.assertEqual(summary["tracking_backend"], "local_file_store")
        self.assertEqual(summary["run_count"], 3)
        self.assertFalse(summary["raw_run_ids_exported"])
        self.assertEqual(summary["best_run_alias"], "best_optuna_trial")
        self.assertEqual(summary["best_validation_logloss"], 0.696531)
        self.assertEqual(summary["best_trial_validation_top_k_cost"], 7.0)
        self.assertEqual(summary["baseline_validation_top_k_cost"], 1.0)
        self.assertEqual(summary["source_package_id"], "trial-churn-ml-baseline-package-v0")
        self.assertEqual(summary["optuna_tuning_audit_id"], "trial-churn-optuna-tuning-audit-v0")
        self.assertEqual(summary["decision_status"], "mlflow_ledger_ready_for_stability_package")
        self.assertEqual(summary["readiness_status"], "ready_for_drift_and_stability_lesson")

    def test_run_table_has_three_stable_aliases_and_required_metrics(self) -> None:
        report = self.audit()
        rows = {row["run_alias"]: row for row in report["run_table"]}

        self.assertEqual(list(rows), ["source_early_stopped_catboost", "best_optuna_trial", "phase15_baseline_cost_gate"])
        source = rows["source_early_stopped_catboost"]
        best = rows["best_optuna_trial"]
        baseline = rows["phase15_baseline_cost_gate"]

        self.assertTrue(source["run_id_present"])
        self.assertEqual(source["run_id_length"], 32)
        self.assertFalse(source["raw_run_id_exported"])
        self.assertEqual(source["model_id"], "catboost_depth2_native_categories_es_logloss")
        self.assertEqual(source["depth"], "2")
        self.assertEqual(source["learning_rate"], "0.2")
        self.assertEqual(source["validation_logloss"], 0.698394)
        self.assertEqual(source["validation_top_k_total_error_cost"], 7.0)

        self.assertEqual(best["model_id"], "catboost_optuna_fixed_budget_logloss")
        self.assertEqual(best["run_role"], "tuned_candidate")
        self.assertEqual(best["optuna_trial_number"], "4")
        self.assertEqual(best["learning_rate"], "0.05")
        self.assertEqual(best["validation_logloss"], 0.696531)
        self.assertEqual(best["objective_improved_vs_source"], 1.0)
        self.assertEqual(best["cost_gate_still_fails_vs_baseline"], 1.0)
        self.assertEqual(best["artifact_count"], 4)

        self.assertEqual(baseline["model_id"], "trial-churn-ml-baseline-package-v0")
        self.assertEqual(baseline["validation_top_k_total_error_cost"], 1.0)
        self.assertEqual(baseline["artifact_count"], 2)
        self.assertTrue(check(report, "required_mlflow_runs_exported")["valid"])
        self.assertTrue(check(report, "run_table_omits_raw_run_ids")["valid"])

    def test_artifact_inventory_logs_upstream_files_and_model_metadata(self) -> None:
        report = self.audit()
        paths = {(row["run_alias"], row["artifact_path"]): row for row in report["artifact_inventory"]}

        self.assertEqual(len(report["artifact_inventory"]), 8)
        self.assertTrue(paths[("source_early_stopped_catboost", "upstream/optuna_best_trial_trace.csv")]["logged_to_mlflow"])
        self.assertTrue(paths[("best_optuna_trial", "upstream/optuna_tuning_serialized_spec.json")]["logged_to_mlflow"])
        self.assertTrue(paths[("best_optuna_trial", "upstream/optuna_trial_ledger.csv")]["logged_to_mlflow"])
        self.assertTrue(paths[("best_optuna_trial", "upstream/optuna_tuned_predictions.csv")]["logged_to_mlflow"])
        self.assertTrue(paths[("best_optuna_trial", "model_metadata/best_optuna_trial_model_metadata.json")]["logged_to_mlflow"])
        self.assertTrue(paths[("phase15_baseline_cost_gate", "model_metadata/phase15_baseline_cost_gate_model_metadata.json")]["logged_to_mlflow"])
        self.assertTrue(all(row["source_file_exists"] for row in report["artifact_inventory"]))
        self.assertTrue(all(len(row["source_sha256"]) == 64 for row in report["artifact_inventory"]))
        self.assertTrue(check(report, "required_artifacts_logged")["valid"])

    def test_metric_history_keeps_mlflow_logged_values_once_per_metric(self) -> None:
        report = self.audit()
        metrics = {(row["run_alias"], row["metric_name"]): row for row in report["metric_history"]}

        self.assertEqual(metrics[("source_early_stopped_catboost", "validation_logloss")]["metric_value"], 0.698394)
        self.assertEqual(metrics[("best_optuna_trial", "validation_logloss")]["metric_value"], 0.696531)
        self.assertEqual(metrics[("best_optuna_trial", "validation_top_k_total_error_cost")]["metric_value"], 7.0)
        self.assertEqual(metrics[("best_optuna_trial", "baseline_validation_top_k_cost")]["metric_value"], 1.0)
        self.assertEqual(metrics[("best_optuna_trial", "test_used_for_selection")]["metric_value"], 0.0)
        self.assertEqual(metrics[("phase15_baseline_cost_gate", "validation_top_k_total_error_cost")]["metric_value"], 1.0)
        self.assertTrue(all(row["logged_once"] for row in report["metric_history"]))
        self.assertTrue(check(report, "required_metrics_logged")["valid"])

    def test_model_metadata_preserves_lineage_warnings_and_params(self) -> None:
        report = self.audit()
        metadata = {row["run_alias"]: row for row in report["model_metadata"]}

        best = metadata["best_optuna_trial"]
        self.assertEqual(best["source_package_id"], "trial-churn-ml-baseline-package-v0")
        self.assertEqual(best["upstream_optuna_tuning_audit_id"], "trial-churn-optuna-tuning-audit-v0")
        self.assertEqual(best["params"]["optuna_trial_number"], 4)
        self.assertEqual(best["params"]["learning_rate"], 0.05)
        self.assertEqual(best["metrics"]["validation_logloss"], 0.696531)
        self.assertIn("best_trial_logloss_improves_but_cost_gate_still_fails", best["known_warnings"])
        self.assertTrue(check(report, "source_package_lineage_logged")["valid"])

    def test_tracking_scope_blocks_registry_remote_server_and_serving(self) -> None:
        with TemporaryDirectory() as directory:
            policy_path = Path(directory) / "mlflow_tracking_policy_spec.json"
            policy = read_json(DATA_ROOT / "mlflow_tracking_policy_spec.json")
            policy["tracking_scope"]["registry"] = True
            write_json(policy_path, policy)

            report = self.audit(policy_path=policy_path)

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["readiness_status"], "blocked_before_mlflow_tracking")
        self.assertEqual(report["summary"]["blocking_errors"], ["tracking_scope_excludes_registry_and_serving"])
        self.assertEqual(report["run_table"], [])
        self.assertFalse(check(report, "tracking_scope_excludes_registry_and_serving")["valid"])

    def test_missing_required_artifact_is_a_reproducibility_blocker(self) -> None:
        with TemporaryDirectory() as directory:
            policy_path = Path(directory) / "mlflow_tracking_policy_spec.json"
            policy = read_json(DATA_ROOT / "mlflow_tracking_policy_spec.json")
            policy["required_artifacts"]["best_optuna_trial"].append("upstream/not_logged.csv")
            write_json(policy_path, policy)

            report = self.audit(policy_path=policy_path)

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["readiness_status"], "blocked_before_mlflow_tracking")
        self.assertEqual(report["summary"]["blocking_errors"], ["required_artifacts_logged"])
        self.assertFalse(check(report, "required_artifacts_logged")["valid"])
        self.assertEqual(len(report["run_table"]), 3)

    def test_warnings_explain_cost_gate_local_store_and_skinny_package_boundaries(self) -> None:
        report = self.audit()

        self.assertEqual(report["summary"]["blocking_errors"], [])
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "mlflow_ledger_tracks_candidate_with_failed_cost_gate",
                "local_tracking_store_not_registry",
                "mlflow_skinny_used_due_to_pandas3_boundary",
            ],
        )
        self.assertEqual(check(report, "mlflow_ledger_tracks_candidate_with_failed_cost_gate")["severity"], "warning")
        self.assertEqual(check(report, "local_tracking_store_not_registry")["observed"], "local_file_store")
        self.assertEqual(check(report, "mlflow_skinny_used_due_to_pandas3_boundary")["observed"]["package"], "mlflow-skinny")

    def test_serialized_spec_is_ready_for_final_stability_package(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["mlflow_tracking_audit_id"], "trial-churn-mlflow-tracking-audit-v0")
        self.assertEqual(serialized["experiment"]["tracking_backend"], "local_file_store")
        self.assertEqual(serialized["experiment"]["tracking_package"], "mlflow-skinny")
        self.assertEqual(serialized["source_package_id"], "trial-churn-ml-baseline-package-v0")
        self.assertEqual(serialized["optuna_tuning_audit_id"], "trial-churn-optuna-tuning-audit-v0")
        self.assertEqual(serialized["run_aliases"], ["source_early_stopped_catboost", "best_optuna_trial", "phase15_baseline_cost_gate"])
        self.assertEqual(serialized["artifact_count"], 8)
        self.assertEqual(serialized["decision_policy"]["next_lesson_readiness"], "ready_for_drift_and_stability_lesson")

    def test_writer_and_lesson_cli_export_expected_outputs(self) -> None:
        report = self.audit()
        with TemporaryDirectory() as directory:
            output_root = Path(directory)
            output_spec = read_json(DATA_ROOT / "mlflow_tracking_policy_spec.json")["output"]
            write_outputs(report, output_root, output_spec)

            run_rows = read_csv(output_root / "mlflow_run_table.csv")
            inventory_rows = read_csv(output_root / "mlflow_artifact_inventory.csv")
            checks_rows = read_csv(output_root / "mlflow_reproducibility_checks.csv")
            exported_report = read_json(output_root / "mlflow_experiment_report.json")

        self.assertEqual(len(run_rows), 3)
        self.assertEqual(len(inventory_rows), 8)
        self.assertGreaterEqual(len(checks_rows), 15)
        self.assertEqual(exported_report["summary"]["best_run_alias"], "best_optuna_trial")

        completed = subprocess.run(
            [sys.executable, str(CODE)],
            check=True,
            text=True,
            capture_output=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["run_count"], 3)
        self.assertFalse(payload["raw_run_ids_exported"])
        self.assertEqual(payload["best_validation_logloss"], 0.696531)
        self.assertEqual(payload["readiness_status"], "ready_for_drift_and_stability_lesson")

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
            self.assertTrue((output_root / "mlflow_experiment_report.json").is_file())
            self.assertTrue((output_root / "mlflow_run_table.csv").is_file())
            self.assertTrue((output_root / "mlflow_artifact_inventory.csv").is_file())
            self.assertTrue((output_root / "mlflow_metric_history.csv").is_file())
            self.assertTrue((output_root / "mlflow_reproducibility_checks.csv").is_file())
            self.assertTrue((output_root / "mlflow_model_metadata.json").is_file())
            self.assertTrue((output_root / "mlflow_tracking_serialized_spec.json").is_file())
            self.assertEqual(read_json(output_root / "mlflow_experiment_report.json")["summary"]["decision_status"], "mlflow_ledger_ready_for_stability_package")
