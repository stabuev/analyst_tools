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
ARTIFACT = LESSON_ROOT / "outputs" / "imbalance_policy_evaluator.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from imbalance_policy_evaluator import run  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class ImbalancePolicyEvaluatorTest(TestCase):
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

    def test_valid_imbalance_policy_exports_report(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(
            report["summary"]["imbalance_policy_id"],
            "trial-churn-imbalance-policy-v0",
        )
        self.assertEqual(report["summary"]["sklearn_version"], "1.9.0")
        self.assertEqual(
            report["summary"]["selected_model_id"],
            "random_forest_depth2_class_weight_balanced",
        )
        self.assertEqual(report["summary"]["primary_metric"], "precision_at_budget")
        self.assertEqual(report["summary"]["fit_positive_rate"], 0.5)
        self.assertEqual(report["summary"]["test_positive_rate"], 0.2)
        self.assertEqual(report["summary"]["always_negative_test_accuracy"], 0.8)
        self.assertEqual(report["summary"]["always_negative_test_positive_recall"], 0.0)
        self.assertEqual(report["summary"]["validation_precision_at_budget"], 0.5)
        self.assertEqual(report["summary"]["test_precision_at_budget"], 0.0)
        self.assertEqual(report["summary"]["test_top_k_selected_ids"], ["S009", "S012"])
        self.assertEqual(report["summary"]["test_fixed_threshold_0_5_action_count"], 3)
        self.assertFalse(report["summary"]["test_used_for_selection"])
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "imbalance_positive_rate_below_threshold",
                "accuracy_trap_detected_on_test",
                "class_weight_improves_validation_not_test_expected",
                "fixed_threshold_can_exceed_offer_budget",
            ],
        )
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_calibration_lesson")

    def test_distribution_report_flags_imbalanced_validation_and_test(self) -> None:
        report = self.audit()
        rows = {(row["scope"], row["group_id"]): row for row in report["distribution"]}

        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[("split", "all_eligible")]["positive_rate"], 0.333333)
        self.assertEqual(rows[("split", "train")]["positive_rate"], 0.5)
        self.assertFalse(rows[("split", "train")]["warning_triggered"])
        self.assertEqual(rows[("split", "test")]["positive_count"], 1)
        self.assertEqual(rows[("split", "test")]["negative_to_positive_ratio"], 4.0)
        self.assertTrue(rows[("split", "test")]["warning_triggered"])
        low_rate = check(report, "imbalance_positive_rate_below_threshold")
        self.assertEqual(low_rate["severity"], "warning")
        self.assertFalse(low_rate["valid"])

    def test_accuracy_trap_baseline_has_high_test_accuracy_but_zero_recall(self) -> None:
        report = self.audit()
        rows = {row["split"]: row for row in report["baseline_trap"]}

        self.assertEqual(rows["validation"]["accuracy"], 0.666667)
        self.assertEqual(rows["validation"]["positive_recall"], 0.0)
        self.assertFalse(rows["validation"]["trap_detected"])
        self.assertEqual(rows["test"]["accuracy"], 0.8)
        self.assertEqual(rows["test"]["balanced_accuracy"], 0.5)
        self.assertEqual(rows["test"]["positive_recall"], 0.0)
        self.assertTrue(rows["test"]["trap_detected"])
        trap = check(report, "accuracy_trap_detected_on_test")
        self.assertEqual(trap["severity"], "warning")
        self.assertFalse(trap["valid"])

    def test_class_weight_candidate_wins_validation_but_not_test_budget(self) -> None:
        report = self.audit()
        rows = {
            (row["model_id"], row["split"]): row
            for row in report["comparison"]
        }

        unweighted = rows[("random_forest_depth2_unweighted", "validation")]
        weighted = rows[("random_forest_depth2_class_weight_balanced", "validation")]
        weighted_test = rows[("random_forest_depth2_class_weight_balanced", "test")]
        self.assertEqual(unweighted["precision_at_budget"], 0.0)
        self.assertEqual(unweighted["selection_rank"], 2)
        self.assertEqual(weighted["class_weight"], "balanced")
        self.assertEqual(weighted["precision_at_budget"], 0.5)
        self.assertEqual(weighted["recall_at_budget"], 1.0)
        self.assertEqual(weighted["selection_rank"], 1)
        self.assertTrue(weighted["selected_on_validation"])
        self.assertEqual(weighted["selected_ids"], "S006,S007")
        self.assertEqual(weighted_test["precision_at_budget"], 0.0)
        self.assertEqual(weighted_test["selected_ids"], "S009,S012")

    def test_threshold_report_separates_top_k_rule_from_fixed_thresholds(self) -> None:
        report = self.audit()
        rows = {
            (row["split"], row["decision_rule"], row["threshold"]): row
            for row in report["thresholds"]
        }

        self.assertEqual(len(report["thresholds"]), 8)
        validation_topk = rows[("validation", "rank_top_k_within_scoring_batch", "")]
        test_topk = rows[("test", "rank_top_k_within_scoring_batch", "")]
        test_threshold = rows[("test", "fixed_threshold", 0.5)]
        self.assertEqual(validation_topk["precision"], 0.5)
        self.assertEqual(validation_topk["selected_ids"], "S006,S007")
        self.assertFalse(validation_topk["budget_exceeded"])
        self.assertEqual(test_topk["precision"], 0.0)
        self.assertEqual(test_topk["selected_ids"], "S009,S012")
        self.assertEqual(test_threshold["action_count"], 3)
        self.assertTrue(test_threshold["budget_exceeded"])
        warning = check(report, "fixed_threshold_can_exceed_offer_budget")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])

    def test_predictions_include_unweighted_and_weighted_scores_without_test_selection(
        self,
    ) -> None:
        report = self.audit()
        rows = {
            (row["model_id"], row["split"], row["snapshot_id"]): row
            for row in report["predictions"]
        }

        self.assertEqual(len(rows), 16)
        self.assertEqual(
            rows[("random_forest_depth2_unweighted", "validation", "S006")]["score"],
            0.38,
        )
        self.assertEqual(
            rows[
                (
                    "random_forest_depth2_class_weight_balanced",
                    "validation",
                    "S006",
                )
            ]["score"],
            0.5,
        )
        self.assertEqual(
            rows[
                (
                    "random_forest_depth2_class_weight_balanced",
                    "test",
                    "S010",
                )
            ]["selected_at_budget"],
            0,
        )
        self.assertEqual({row["trained_on_split"] for row in rows.values()}, {"train"})
        self.assertEqual(
            {row["generated_at"] for row in rows.values()},
            {"2026-07-03T10:00:00+03:00"},
        )

    def test_serialized_spec_records_fit_only_class_weight_policy(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["imbalance_policy_id"], "trial-churn-imbalance-policy-v0")
        self.assertEqual(
            serialized["class_weight_policy"]["candidate_model_id"],
            "random_forest_depth2_class_weight_balanced",
        )
        self.assertEqual(serialized["class_weight_policy"]["computed_weights"]["class_0"], 1.0)
        self.assertEqual(serialized["class_weight_policy"]["computed_weights"]["class_1"], 1.0)
        self.assertFalse(serialized["test_used_for_selection"])
        self.assertEqual(len(serialized["fit_trace"]), 2)
        for fit in serialized["fit_trace"]:
            self.assertEqual(fit["fit_ids"], ["S001", "S002", "S003", "S004"])
            self.assertEqual(fit["validation_ids_seen"], [])
            self.assertEqual(fit["test_ids_seen"], [])

    def test_code_example_writes_imbalance_artifacts(self) -> None:
        report_path = LESSON_ROOT / "outputs" / "imbalance_report.json"
        distribution_path = LESSON_ROOT / "outputs" / "class_distribution.csv"
        trap_path = LESSON_ROOT / "outputs" / "baseline_trap_report.csv"
        threshold_path = LESSON_ROOT / "outputs" / "imbalance_threshold_report.csv"
        prediction_path = LESSON_ROOT / "outputs" / "imbalance_predictions.csv"
        audit_path = LESSON_ROOT / "outputs" / "imbalance_policy_audit.csv"
        serialized_path = LESSON_ROOT / "outputs" / "imbalance_serialized_spec.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["imbalance_policy_id"], "trial-churn-imbalance-policy-v0")
        self.assertEqual(payload["selected_model_id"], "random_forest_depth2_class_weight_balanced")
        self.assertEqual(payload["always_negative_test_accuracy"], 0.8)
        self.assertEqual(payload["test_fixed_threshold_0_5_action_count"], 3)
        self.assertEqual(read_json(report_path)["summary"]["test_positive_rate"], 0.2)
        self.assertEqual(len(read_csv(distribution_path)), 6)
        self.assertEqual(len(read_csv(trap_path)), 2)
        self.assertEqual(len(read_csv(threshold_path)), 8)
        self.assertEqual(len(read_csv(prediction_path)), 16)
        self.assertEqual(len(read_csv(audit_path)), 13)
        self.assertEqual(
            read_json(serialized_path)["selected_model_id"],
            payload["selected_model_id"],
        )

    def test_data_generator_check_rebuilds_committed_imbalance_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)
        self.assertTrue((DATA_ROOT / "imbalance_policy_spec.json").exists())

    def test_accuracy_cannot_be_primary_metric(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "imbalance_policy_spec.json")
            spec["comparison"]["primary_metric"] = "accuracy"
            write_json(root / "imbalance_policy_spec.json", spec)

            report = self.audit(root)

        contract = check(
            report,
            "imbalance_policy_spec_declares_accuracy_weight_threshold_contract",
        )
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertIn(
            "imbalance_policy_spec_declares_accuracy_weight_threshold_contract",
            report["summary"]["blocking_errors"],
        )

    def test_class_weight_must_be_computed_on_fit_split_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "imbalance_policy_spec.json")
            spec["class_weight_policy"]["compute_on"] = "train_validation_pool"
            write_json(root / "imbalance_policy_spec.json", spec)

            report = self.audit(root)

        contract = check(
            report,
            "imbalance_policy_spec_declares_accuracy_weight_threshold_contract",
        )
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["sample"][0]["field"], "class_weight_policy.compute_on")

    def test_resampling_validation_or_test_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "imbalance_policy_spec.json")
            spec["resampling_policy"]["forbid_resampling_validation_or_test"] = False
            write_json(root / "imbalance_policy_spec.json", spec)

            report = self.audit(root)

        contract = check(
            report,
            "imbalance_policy_spec_declares_accuracy_weight_threshold_contract",
        )
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertEqual(
            contract["sample"][0]["field"],
            "resampling_policy.forbid_resampling_validation_or_test",
        )

    def test_threshold_selection_on_test_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "imbalance_policy_spec.json")
            spec["threshold_policy"]["selection_data"] = "test"
            write_json(root / "imbalance_policy_spec.json", spec)

            report = self.audit(root)

        contract = check(
            report,
            "imbalance_policy_spec_declares_accuracy_weight_threshold_contract",
        )
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["sample"][0]["field"], "threshold_policy.selection_data")

    def test_upstream_cv_must_be_valid_before_imbalance_evaluation(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "cv_plan_spec.json")
            spec["final_holdout_split"] = "validation"
            write_json(root / "cv_plan_spec.json", spec)

            report = self.audit(root)

        upstream = check(report, "upstream_cv_audit_is_valid")
        self.assertFalse(report["valid"])
        self.assertFalse(upstream["valid"])
        self.assertIn("upstream_cv_audit_is_valid", report["summary"]["blocking_errors"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "imbalance_policy_spec.json")
            spec["audit_policy"]["forbid_accuracy_as_primary_metric"] = False
            write_json(root / "imbalance_policy_spec.json", spec)
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
                    "--imbalance-policy-spec",
                    root / "imbalance_policy_spec.json",
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
            "imbalance_policy_spec_declares_accuracy_weight_threshold_contract",
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
                "--imbalance-policy-spec",
                DATA_ROOT / "imbalance_policy_spec.json",
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
        self.assertIn("accuracy_trap_detected_on_test", result.stdout)
