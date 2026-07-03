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
ARTIFACT = LESSON_ROOT / "outputs" / "cross_validation_planner.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from cross_validation_planner import run  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class CrossValidationPlannerTest(TestCase):
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

    def test_valid_cv_plan_exports_group_time_aware_report(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["cv_plan_id"], "trial-churn-cv-plan-v0")
        self.assertEqual(report["summary"]["sklearn_version"], "1.9.0")
        self.assertEqual(report["summary"]["fold_count"], 2)
        self.assertEqual(report["summary"]["model_id"], "random_forest_depth2")
        self.assertEqual(report["summary"]["primary_metric"], "precision_at_budget")
        self.assertEqual(report["summary"]["mean_precision_at_budget"], 0.25)
        self.assertEqual(report["summary"]["std_precision_at_budget"], 0.25)
        self.assertEqual(report["summary"]["mean_log_loss"], 0.871057)
        self.assertEqual(report["summary"]["cv_validation_row_count"], 5)
        self.assertEqual(report["summary"]["final_holdout_split"], "test")
        self.assertFalse(report["summary"]["test_used_in_cv"])
        self.assertEqual(
            report["summary"]["warnings"],
            ["tiny_cv_fold_count_expected", "tiny_cv_validation_sample_expected"],
        )
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_imbalance_lesson")

    def test_fold_manifest_excludes_test_and_preserves_group_time_contract(self) -> None:
        report = self.audit()
        rows = report["fold_manifest"]

        self.assertEqual(len(rows), 11)
        self.assertNotIn("test", {row["original_split"] for row in rows})
        self.assertEqual({row["cv_role"] for row in rows}, {"cv_train", "cv_validation"})
        self.assertEqual(check(report, "cv_fold_manifest_excludes_final_test")["valid"], True)
        self.assertEqual(check(report, "cv_group_isolation_respected")["valid"], True)
        self.assertEqual(check(report, "cv_temporal_order_respected")["valid"], True)
        self.assertEqual(check(report, "upstream_tree_ensemble_audit_is_valid")["valid"], True)

    def test_scores_show_fold_level_metric_variation(self) -> None:
        report = self.audit()
        rows = {row["fold_id"]: row for row in report["scores"]}

        self.assertEqual(rows["cv_fold_1"]["train_row_count"], 2)
        self.assertEqual(rows["cv_fold_1"]["validation_row_count"], 2)
        self.assertEqual(rows["cv_fold_1"]["precision_at_budget"], 0.5)
        self.assertEqual(rows["cv_fold_1"]["recall_at_budget"], 1.0)
        self.assertEqual(rows["cv_fold_1"]["log_loss"], 0.737454)
        self.assertEqual(rows["cv_fold_1"]["selected_ids"], "S003,S004")
        self.assertEqual(rows["cv_fold_2"]["train_row_count"], 4)
        self.assertEqual(rows["cv_fold_2"]["validation_row_count"], 3)
        self.assertEqual(rows["cv_fold_2"]["precision_at_budget"], 0.0)
        self.assertEqual(rows["cv_fold_2"]["average_precision"], 0.333333)
        self.assertEqual(rows["cv_fold_2"]["error_cost_at_budget"], 7.0)
        self.assertEqual(rows["cv_fold_2"]["selected_ids"], "S005,S007")

    def test_predictions_are_validation_only_and_record_training_role(self) -> None:
        report = self.audit()
        rows = {row["snapshot_id"]: row for row in report["predictions"]}

        self.assertEqual(set(rows), {"S003", "S004", "S005", "S006", "S007"})
        self.assertEqual({row["cv_role"] for row in rows.values()}, {"cv_validation"})
        self.assertEqual({row["trained_on_role"] for row in rows.values()}, {"cv_train"})
        self.assertEqual(
            {row["generated_at"] for row in rows.values()},
            {"2026-07-02T14:00:00+03:00"},
        )
        self.assertEqual(
            {snapshot_id: row["score"] for snapshot_id, row in rows.items()},
            {"S003": 0.48, "S004": 0.44, "S005": 0.62, "S006": 0.38, "S007": 0.66},
        )
        self.assertEqual(
            {snapshot_id: row["selected_at_budget"] for snapshot_id, row in rows.items()},
            {"S003": 1, "S004": 1, "S005": 1, "S006": 0, "S007": 1},
        )

    def test_serialized_spec_records_fold_fit_trace_without_holdout_peeking(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]
        first_fit, second_fit = serialized["fit_trace"]

        self.assertEqual(serialized["tree_ensemble_id"], "trial-churn-tree-ensemble-v0")
        self.assertEqual(serialized["model"]["class"], "RandomForestClassifier")
        self.assertEqual(serialized["model"]["params"]["n_estimators"], 25)
        self.assertEqual(
            serialized["fold_strategy"]["kind"],
            "predeclared_time_ordered_group_folds",
        )
        self.assertTrue(serialized["scoring"]["requires_proba"])
        self.assertFalse(serialized["test_used_in_cv"])
        self.assertTrue(serialized["sklearn_cv_iterator_compatible"])
        self.assertEqual(first_fit["train_ids"], ["S001", "S002"])
        self.assertEqual(first_fit["validation_ids"], ["S003", "S004"])
        self.assertEqual(second_fit["train_ids"], ["S001", "S002", "S003", "S004"])
        self.assertEqual(second_fit["validation_ids"], ["S005", "S006", "S007"])
        self.assertEqual(first_fit["test_ids_seen"], [])
        self.assertEqual(second_fit["test_ids_seen"], [])

    def test_code_example_writes_cv_artifacts(self) -> None:
        report_path = LESSON_ROOT / "outputs" / "cv_report.json"
        fold_path = LESSON_ROOT / "outputs" / "cv_fold_manifest.csv"
        score_path = LESSON_ROOT / "outputs" / "cv_score_report.csv"
        prediction_path = LESSON_ROOT / "outputs" / "cv_predictions.csv"
        audit_path = LESSON_ROOT / "outputs" / "cv_no_peeking_audit.csv"
        serialized_path = LESSON_ROOT / "outputs" / "cv_serialized_spec.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["cv_plan_id"], "trial-churn-cv-plan-v0")
        self.assertEqual(payload["fold_count"], 2)
        self.assertEqual(payload["mean_precision_at_budget"], 0.25)
        self.assertFalse(payload["test_used_in_cv"])
        self.assertEqual(read_json(report_path)["summary"]["cv_validation_row_count"], 5)
        self.assertEqual(len(read_csv(fold_path)), 11)
        self.assertEqual(len(read_csv(score_path)), 2)
        self.assertEqual(len(read_csv(prediction_path)), 5)
        self.assertEqual(len(read_csv(audit_path)), 11)
        self.assertEqual(read_json(serialized_path)["fold_strategy"]["n_splits"], 2)

    def test_data_generator_check_rebuilds_committed_cv_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)
        self.assertTrue((DATA_ROOT / "cv_plan_spec.json").exists())
        self.assertTrue((DATA_ROOT / "ml_cv_fold_manifest.csv").exists())

    def test_test_holdout_rows_are_rejected_before_cv_fit(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_cv_fold_manifest.csv")
            rows[0].update(
                {
                    "snapshot_id": "S009",
                    "user_id": "U009",
                    "prediction_time": "2026-05-24T09:00:00+03:00",
                    "original_split": "test",
                    "group_key": "U009",
                    "label": "false",
                }
            )
            write_csv(root / "ml_cv_fold_manifest.csv", rows)

            report = self.audit(root)

        holdout = check(report, "cv_fold_manifest_excludes_final_test")
        self.assertFalse(report["valid"])
        self.assertFalse(holdout["valid"])
        self.assertIn("cv_fold_manifest_excludes_final_test", report["summary"]["blocking_errors"])

    def test_group_overlap_inside_a_fold_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_cv_fold_manifest.csv")
            rows[2]["group_key"] = "U001"
            write_csv(root / "ml_cv_fold_manifest.csv", rows)

            report = self.audit(root)

        group_check = check(report, "cv_group_isolation_respected")
        self.assertFalse(report["valid"])
        self.assertFalse(group_check["valid"])
        self.assertEqual(group_check["sample"], [{"fold_id": "cv_fold_1", "overlap": ["U001"]}])

    def test_future_train_rows_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_cv_fold_manifest.csv")
            rows[0]["prediction_time"] = "2026-05-24T09:00:00+03:00"
            write_csv(root / "ml_cv_fold_manifest.csv", rows)

            report = self.audit(root)

        temporal = check(report, "cv_temporal_order_respected")
        self.assertFalse(report["valid"])
        self.assertFalse(temporal["valid"])
        self.assertEqual(temporal["sample"][0]["fold_id"], "cv_fold_1")

    def test_scoring_policy_must_match_ensemble_model_selection_metric(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "cv_plan_spec.json")
            spec["scoring"]["primary_metric"] = "roc_auc"
            write_json(root / "cv_plan_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "cv_plan_spec_declares_group_time_scoring_contract")
        alignment = check(report, "cv_scoring_policy_matches_model_selection_metric")
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertFalse(alignment["valid"])
        self.assertIn(
            "cv_plan_spec_declares_group_time_scoring_contract",
            report["summary"]["blocking_errors"],
        )

    def test_cli_writes_report_and_returns_nonzero_for_invalid_cv_plan(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "cv_plan_spec.json")
            spec["audit_policy"]["forbid_test_rows_in_cv"] = False
            write_json(root / "cv_plan_spec.json", spec)
            output = Path(directory) / "report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--spec",
                    root / "problem_spec.json",
                    "--preprocessing-contract",
                    root / "preprocessing_contract.json",
                    "--pipeline-spec",
                    root / "pipeline_spec.json",
                    "--column-transformer-spec",
                    root / "column_transformer_spec.json",
                    "--linear-baseline-spec",
                    root / "linear_baseline_spec.json",
                    "--tree-diagnostic-spec",
                    root / "tree_diagnostic_spec.json",
                    "--tree-ensemble-spec",
                    root / "tree_ensemble_spec.json",
                    "--cv-plan-spec",
                    root / "cv_plan_spec.json",
                    "--features",
                    root / "ml_raw_features.csv",
                    "--labels",
                    root / "ml_labels.csv",
                    "--manifest",
                    root / "ml_split_manifest.csv",
                    "--cv-fold-manifest",
                    root / "ml_cv_fold_manifest.csv",
                    "--output",
                    output,
                ],
                capture_output=True,
                text=True,
            )
            payload = read_json(output)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["valid"])
        self.assertIn(
            "cv_plan_spec_declares_group_time_scoring_contract",
            payload["summary"]["blocking_errors"],
        )

    def test_cli_can_fail_on_warning_for_strict_gate(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--spec",
                DATA_ROOT / "problem_spec.json",
                "--preprocessing-contract",
                DATA_ROOT / "preprocessing_contract.json",
                "--pipeline-spec",
                DATA_ROOT / "pipeline_spec.json",
                "--column-transformer-spec",
                DATA_ROOT / "column_transformer_spec.json",
                "--linear-baseline-spec",
                DATA_ROOT / "linear_baseline_spec.json",
                "--tree-diagnostic-spec",
                DATA_ROOT / "tree_diagnostic_spec.json",
                "--tree-ensemble-spec",
                DATA_ROOT / "tree_ensemble_spec.json",
                "--cv-plan-spec",
                DATA_ROOT / "cv_plan_spec.json",
                "--features",
                DATA_ROOT / "ml_raw_features.csv",
                "--labels",
                DATA_ROOT / "ml_labels.csv",
                "--manifest",
                DATA_ROOT / "ml_split_manifest.csv",
                "--cv-fold-manifest",
                DATA_ROOT / "ml_cv_fold_manifest.csv",
                "--fail-on-warning",
            ],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tiny_cv_fold_count_expected", result.stdout)
