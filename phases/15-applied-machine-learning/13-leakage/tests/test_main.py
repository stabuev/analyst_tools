from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
ARTIFACT = LESSON_ROOT / "outputs" / "ml_leakage_auditor.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from ml_leakage_auditor import run  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class MLLeakageAuditorTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, **outputs: Path) -> dict:
        return run(
            spec_path=root / "problem_spec.json",
            preprocessing_contract_path=root / "preprocessing_contract.json",
            pipeline_spec_path=root / "pipeline_spec.json",
            column_transformer_spec_path=root / "column_transformer_spec.json",
            linear_baseline_spec_path=root / "linear_baseline_spec.json",
            tree_diagnostic_spec_path=root / "tree_diagnostic_spec.json",
            tree_ensemble_spec_path=root / "tree_ensemble_spec.json",
            cv_plan_spec_path=root / "cv_plan_spec.json",
            imbalance_policy_spec_path=root / "imbalance_policy_spec.json",
            calibration_policy_spec_path=root / "calibration_policy_spec.json",
            leakage_policy_spec_path=root / "leakage_policy_spec.json",
            feature_source_inventory_path=root / "feature_source_inventory.csv",
            feature_availability_path=root / "ml_feature_availability.csv",
            feature_selection_log_path=root / "ml_feature_selection_log.csv",
            model_selection_log_path=root / "ml_model_selection_log.csv",
            features_path=root / "ml_raw_features.csv",
            labels_path=root / "ml_labels.csv",
            manifest_path=root / "ml_split_manifest.csv",
            cv_fold_manifest_path=root / "ml_cv_fold_manifest.csv",
            **outputs,
        )

    def copy_profile(self, directory: Path) -> Path:
        target = directory / "tiny"
        shutil.copytree(DATA_ROOT, target)
        return target

    def cli_args(self, root: Path = DATA_ROOT) -> list[str]:
        return [
            sys.executable,
            str(ARTIFACT),
            "--spec",
            str(root / "problem_spec.json"),
            "--preprocessing-contract",
            str(root / "preprocessing_contract.json"),
            "--pipeline-spec",
            str(root / "pipeline_spec.json"),
            "--column-transformer-spec",
            str(root / "column_transformer_spec.json"),
            "--linear-baseline-spec",
            str(root / "linear_baseline_spec.json"),
            "--tree-diagnostic-spec",
            str(root / "tree_diagnostic_spec.json"),
            "--tree-ensemble-spec",
            str(root / "tree_ensemble_spec.json"),
            "--cv-plan-spec",
            str(root / "cv_plan_spec.json"),
            "--imbalance-policy-spec",
            str(root / "imbalance_policy_spec.json"),
            "--calibration-policy-spec",
            str(root / "calibration_policy_spec.json"),
            "--leakage-policy-spec",
            str(root / "leakage_policy_spec.json"),
            "--feature-source-inventory",
            str(root / "feature_source_inventory.csv"),
            "--feature-availability",
            str(root / "ml_feature_availability.csv"),
            "--feature-selection-log",
            str(root / "ml_feature_selection_log.csv"),
            "--model-selection-log",
            str(root / "ml_model_selection_log.csv"),
            "--features",
            str(root / "ml_raw_features.csv"),
            "--labels",
            str(root / "ml_labels.csv"),
            "--manifest",
            str(root / "ml_split_manifest.csv"),
            "--cv-fold-manifest",
            str(root / "ml_cv_fold_manifest.csv"),
        ]

    def test_valid_leakage_policy_exports_report(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["leakage_policy_id"], "trial-churn-leakage-policy-v0")
        self.assertEqual(report["summary"]["sklearn_version"], "1.9.0")
        self.assertEqual(
            report["summary"]["source_model_id"],
            "random_forest_depth2_class_weight_balanced",
        )
        self.assertEqual(
            report["summary"]["selected_model_id"],
            "random_forest_depth2_class_weight_balanced",
        )
        self.assertEqual(report["summary"]["delivery_feature_count"], 10)
        self.assertEqual(report["summary"]["forbidden_candidate_count"], 5)
        self.assertEqual(report["summary"]["blocked_delivery_feature_count"], 0)
        self.assertFalse(report["summary"]["preprocessing_full_sample_fit_detected"])
        self.assertEqual(
            report["summary"]["selected_feature_selector_id"],
            "predeclared_feature_contract",
        )
        self.assertEqual(report["summary"]["feature_selection_outside_cv_selected_count"], 0)
        self.assertEqual(report["summary"]["test_selected_model_count"], 0)
        self.assertFalse(report["summary"]["test_used_for_model_selection"])
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "leakage_forbidden_feature_candidates_reported",
                "leakage_rejected_feature_selection_patterns_reported",
                "leakage_test_cherry_pick_candidates_reported",
            ],
        )
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_error_analysis_lesson")

    def test_feature_availability_separates_delivery_features_from_forbidden_candidates(self) -> None:
        report = self.audit()
        rows = {row["feature_name"]: row for row in report["feature_availability"]}

        self.assertEqual(len(rows), 15)
        delivery = [row for row in rows.values() if row["used_in_delivery_model"]]
        self.assertEqual(len(delivery), 10)
        self.assertTrue(all(row["candidate_allowed"] for row in delivery))
        self.assertTrue(all(not row["blocking_if_used"] for row in delivery))
        self.assertEqual(rows["sessions_14d"]["decision"], "allowed_delivery_feature")
        self.assertEqual(rows["plan_id"]["timing"], "known_before_prediction_time")
        self.assertEqual(rows["churned_14d"]["risk_type"], "target_leakage")
        self.assertEqual(rows["churned_14d"]["decision"], "rejected_known_bad_candidate")
        self.assertTrue(rows["cancelled_after_prediction"]["timing_forbidden_by_policy"])

    def test_forbidden_feature_report_lists_future_label_and_full_sample_risks(self) -> None:
        report = self.audit()
        risks = {row["feature_name"]: row["risk_type"] for row in report["forbidden_features"]}

        self.assertEqual(
            risks,
            {
                "churned_14d": "target_leakage",
                "days_until_label_observed": "label_availability_leakage",
                "cancelled_after_prediction": "future_behavior_leakage",
                "retention_offer_accepted": "post_intervention_outcome_leakage",
                "segment_churn_rate_full_dataset": "full_sample_target_encoding",
            },
        )
        warning = check(report, "leakage_forbidden_feature_candidates_reported")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])

    def test_preprocessing_scope_is_train_only_across_upstream_specs(self) -> None:
        report = self.audit()
        rows = {row["component_type"]: row for row in report["preprocessing_scope"]}

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows["preprocessing_contract"]["declared_fit_split"], "train")
        self.assertEqual(rows["pipeline_spec"]["preprocessing_location"], "inside_pipeline")
        self.assertEqual(rows["column_transformer_spec"]["preprocessing_location"], "inside_pipeline")
        self.assertEqual(rows["calibration_policy_spec"]["transform_or_predict_splits"], "validation,test")
        self.assertTrue(all(row["valid"] for row in rows.values()))

    def test_feature_selection_rejects_all_rows_and_validation_before_cv(self) -> None:
        report = self.audit()
        rows = {row["selector_id"]: row for row in report["feature_selection"]}

        self.assertEqual(rows["predeclared_feature_contract"]["decision"], "allowed_delivery_selector")
        self.assertEqual(rows["select_k_best_all_rows"]["decision"], "rejected_known_bad_selector")
        self.assertEqual(
            rows["validation_score_manual_pruning"]["decision"],
            "rejected_known_bad_selector",
        )
        self.assertEqual(rows["future_rfecv_inside_pipeline"]["decision"], "allowed_future_pattern")
        self.assertTrue(rows["select_k_best_all_rows"]["scope_forbidden"])
        self.assertFalse(rows["future_rfecv_inside_pipeline"]["scope_forbidden"])
        warning = check(report, "leakage_rejected_feature_selection_patterns_reported")
        self.assertEqual(len(warning["observed"]), 2)

    def test_model_selection_uses_validation_and_reports_rejected_test_cherry_pick(self) -> None:
        report = self.audit()
        rows = {row["candidate_id"]: row for row in report["model_selection"]}

        selected = rows["random_forest_depth2_class_weight_balanced"]
        self.assertTrue(selected["selected_for_delivery"])
        self.assertEqual(selected["selection_split"], "validation")
        self.assertFalse(selected["test_metric_visible_to_selector"])
        self.assertEqual(selected["decision"], "selected_on_validation")
        leaky = rows["leaky_test_best_threshold_0_5"]
        self.assertEqual(leaky["selection_split"], "test")
        self.assertTrue(leaky["test_selection_or_cherry_pick"])
        self.assertEqual(leaky["decision"], "rejected_test_cherry_pick")
        warning = check(report, "leakage_test_cherry_pick_candidates_reported")
        self.assertEqual(warning["observed"][0]["candidate_id"], "leaky_test_best_threshold_0_5")

    def test_serialized_spec_records_calibration_handoff_and_no_test_selection(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["leakage_policy_id"], "trial-churn-leakage-policy-v0")
        self.assertEqual(
            serialized["source_model_id"],
            "random_forest_depth2_class_weight_balanced",
        )
        self.assertEqual(
            serialized["upstream_calibration_summary"]["calibration_policy_id"],
            "trial-churn-calibration-policy-v0",
        )
        self.assertEqual(
            serialized["upstream_calibration_summary"]["readiness_status"],
            "ready_for_leakage_lesson",
        )
        self.assertFalse(serialized["upstream_calibration_summary"]["test_used_for_calibration"])
        self.assertFalse(serialized["test_used_for_model_selection"])
        self.assertEqual(
            serialized["feature_selection_policy"]["current_selector_id"],
            "predeclared_feature_contract",
        )

    def test_code_example_writes_leakage_artifacts(self) -> None:
        report_path = LESSON_ROOT / "outputs" / "leakage_report.json"
        availability_path = LESSON_ROOT / "outputs" / "feature_availability_report.csv"
        forbidden_path = LESSON_ROOT / "outputs" / "forbidden_feature_report.csv"
        preprocessing_path = LESSON_ROOT / "outputs" / "preprocessing_scope_audit.csv"
        feature_selection_path = LESSON_ROOT / "outputs" / "feature_selection_audit.csv"
        model_selection_path = LESSON_ROOT / "outputs" / "model_selection_audit.csv"
        audit_path = LESSON_ROOT / "outputs" / "leakage_policy_audit.csv"
        serialized_path = LESSON_ROOT / "outputs" / "leakage_serialized_spec.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["leakage_policy_id"], "trial-churn-leakage-policy-v0")
        self.assertEqual(payload["delivery_feature_count"], 10)
        self.assertEqual(payload["forbidden_candidate_count"], 5)
        self.assertFalse(payload["test_used_for_model_selection"])
        self.assertEqual(read_json(report_path)["summary"]["blocked_delivery_feature_count"], 0)
        self.assertEqual(len(read_csv(availability_path)), 15)
        self.assertEqual(len(read_csv(forbidden_path)), 5)
        self.assertEqual(len(read_csv(preprocessing_path)), 4)
        self.assertEqual(len(read_csv(feature_selection_path)), 4)
        self.assertEqual(len(read_csv(model_selection_path)), 4)
        self.assertEqual(len(read_csv(audit_path)), 10)
        self.assertEqual(
            read_json(serialized_path)["source_model_id"],
            payload["source_model_id"],
        )

    def test_data_generator_check_rebuilds_committed_leakage_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)
        self.assertTrue((DATA_ROOT / "leakage_policy_spec.json").exists())
        self.assertTrue((DATA_ROOT / "ml_feature_availability.csv").exists())
        self.assertTrue((DATA_ROOT / "ml_feature_selection_log.csv").exists())
        self.assertTrue((DATA_ROOT / "ml_model_selection_log.csv").exists())

    def test_forbidden_feature_in_delivery_model_blocks_readiness(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_feature_availability.csv")
            for row in rows:
                if row["feature_name"] == "churned_14d":
                    row["used_in_delivery_model"] = "true"
            write_csv(root / "ml_feature_availability.csv", rows)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn(
            "leakage_no_forbidden_features_in_delivery_model",
            report["summary"]["blocking_errors"],
        )
        failed_check = check(report, "leakage_no_forbidden_features_in_delivery_model")
        self.assertEqual(failed_check["observed"][0]["feature_name"], "churned_14d")
        self.assertEqual(report["summary"]["readiness_status"], "blocked_by_leakage_audit")

    def test_full_sample_preprocessing_blocks_readiness(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            contract = read_json(root / "preprocessing_contract.json")
            contract["fit_split"] = "all_data"
            write_json(root / "preprocessing_contract.json", contract)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn(
            "leakage_preprocessing_fit_scope_is_train_only",
            report["summary"]["blocking_errors"],
        )
        failed_check = check(report, "leakage_preprocessing_fit_scope_is_train_only")
        self.assertEqual(failed_check["observed"][0]["component_id"], "trial-churn-preprocessing-v0")

    def test_selected_feature_selector_outside_cv_blocks_readiness(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_feature_selection_log.csv")
            for row in rows:
                if row["selector_id"] == "predeclared_feature_contract":
                    row["selected_for_delivery"] = "false"
                if row["selector_id"] == "select_k_best_all_rows":
                    row["selected_for_delivery"] = "true"
            write_csv(root / "ml_feature_selection_log.csv", rows)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn(
            "leakage_feature_selection_not_outside_cv",
            report["summary"]["blocking_errors"],
        )
        failed_check = check(report, "leakage_feature_selection_not_outside_cv")
        self.assertEqual(failed_check["observed"][0]["selector_id"], "select_k_best_all_rows")

    def test_test_based_model_selection_blocks_readiness(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_model_selection_log.csv")
            for row in rows:
                if row["candidate_id"] == "random_forest_depth2_class_weight_balanced":
                    row["selected_for_delivery"] = "false"
                if row["candidate_id"] == "leaky_test_best_threshold_0_5":
                    row["selected_for_delivery"] = "true"
            write_csv(root / "ml_model_selection_log.csv", rows)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn(
            "leakage_model_selection_uses_validation_not_test",
            report["summary"]["blocking_errors"],
        )
        failed_check = check(report, "leakage_model_selection_uses_validation_not_test")
        blocked = failed_check["observed"]["blocked_selected_candidates"][0]
        self.assertEqual(blocked["candidate_id"], "leaky_test_best_threshold_0_5")
        self.assertTrue(blocked["test_metric_visible_to_selector"])

    def test_upstream_calibration_handoff_failure_blocks_before_leakage_audit(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "calibration_policy_spec.json")
            spec["calibration_split"] = "test"
            write_json(root / "calibration_policy_spec.json", spec)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn(
            "upstream_calibration_handoff_is_valid",
            report["summary"]["blocking_errors"],
        )
        self.assertEqual(report["summary"]["readiness_status"], "blocked_before_leakage_audit")

    def test_cli_invalid_spec_returns_nonzero_and_writes_runtime_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            output = Path(directory) / "report.json"
            spec = read_json(root / "leakage_policy_spec.json")
            spec["model_selection_policy"]["selected_model_id"] = "unknown_model"
            write_json(root / "leakage_policy_spec.json", spec)
            result = subprocess.run(
                self.cli_args(root) + ["--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            report = read_json(output)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["valid"])
        self.assertIn(
            "leakage_policy_spec_declares_audit_contract",
            report["summary"]["blocking_errors"],
        )

    def test_cli_fail_on_warning_returns_nonzero_for_visible_rejected_candidates(self) -> None:
        result = subprocess.run(
            self.cli_args() + ["--fail-on-warning"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertIn(
            "leakage_test_cherry_pick_candidates_reported",
            payload["summary"]["warnings"],
        )
