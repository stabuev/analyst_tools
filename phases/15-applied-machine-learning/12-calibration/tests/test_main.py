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
ARTIFACT = LESSON_ROOT / "outputs" / "probability_calibration_auditor.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from probability_calibration_auditor import run  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class ProbabilityCalibrationAuditorTest(TestCase):
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

    def test_valid_calibration_policy_exports_report(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(
            report["summary"]["calibration_policy_id"],
            "trial-churn-calibration-policy-v0",
        )
        self.assertEqual(report["summary"]["sklearn_version"], "1.9.0")
        self.assertEqual(
            report["summary"]["source_model_id"],
            "random_forest_depth2_class_weight_balanced",
        )
        self.assertEqual(
            report["summary"]["calibration_method"],
            "validation_bin_map_with_laplace_smoothing",
        )
        self.assertEqual(report["summary"]["calibration_split"], "validation")
        self.assertEqual(report["summary"]["evaluation_split"], "test")
        self.assertEqual(report["summary"]["calibration_row_count"], 3)
        self.assertEqual(report["summary"]["calibration_prior_positive_rate"], 0.333333)
        self.assertEqual(report["summary"]["uncalibrated_validation_brier"], 0.2904)
        self.assertEqual(report["summary"]["calibrated_validation_brier"], 0.098765)
        self.assertEqual(report["summary"]["uncalibrated_test_brier"], 0.25464)
        self.assertEqual(report["summary"]["calibrated_test_brier"], 0.079012)
        self.assertEqual(report["summary"]["uncalibrated_test_log_loss"], 0.705738)
        self.assertEqual(report["summary"]["calibrated_test_log_loss"], 0.318608)
        self.assertEqual(report["summary"]["uncalibrated_test_precision_at_budget"], 0.0)
        self.assertEqual(report["summary"]["calibrated_test_precision_at_budget"], 0.5)
        self.assertEqual(
            report["summary"]["test_uncalibrated_top_k_selected_ids"],
            ["S009", "S012"],
        )
        self.assertEqual(
            report["summary"]["test_calibrated_top_k_selected_ids"],
            ["S010", "S009"],
        )
        self.assertEqual(report["summary"]["test_fixed_threshold_0_5_action_count_uncalibrated"], 3)
        self.assertEqual(report["summary"]["test_fixed_threshold_0_5_action_count_calibrated"], 1)
        self.assertFalse(report["summary"]["test_used_for_calibration"])
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "calibration_sample_below_minimum",
                "calibration_bins_below_min_rows",
                "calibration_bins_missing_class_coverage",
                "fixed_threshold_action_count_changes_after_calibration",
                "tiny_test_improvement_is_not_production_claim",
            ],
        )
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_leakage_lesson")

    def test_calibration_bins_are_learned_on_validation_with_smoothing(self) -> None:
        report = self.audit()
        rows = {(row["split"], row["bin_id"]): row for row in report["calibration_bins"]}

        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[("validation", "bin_1")]["row_count"], 1)
        self.assertEqual(rows[("validation", "bin_1")]["fraction_positive"], 0.0)
        self.assertEqual(
            rows[("validation", "bin_1")]["calibrated_probability_from_validation"],
            0.222222,
        )
        self.assertEqual(rows[("validation", "bin_2")]["positive_count"], 1)
        self.assertEqual(
            rows[("validation", "bin_2")]["calibrated_probability_from_validation"],
            0.555556,
        )
        self.assertEqual(rows[("test", "bin_2")]["row_count"], 1)
        self.assertEqual(rows[("test", "bin_2")]["mean_uncalibrated_score"], 0.58)
        self.assertEqual(rows[("test", "bin_2")]["learned_on_split"], "validation")
        sparse = check(report, "calibration_bins_below_min_rows")
        self.assertEqual(sparse["severity"], "warning")
        self.assertFalse(sparse["valid"])

    def test_metrics_compare_uncalibrated_and_calibrated_probabilities(self) -> None:
        report = self.audit()
        rows = {(row["split"], row["probability_source"]): row for row in report["metrics"]}

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[("test", "uncalibrated")]["brier_score"], 0.25464)
        self.assertEqual(rows[("test", "calibrated")]["brier_score"], 0.079012)
        self.assertLess(
            rows[("test", "calibrated")]["expected_calibration_error"],
            rows[("test", "uncalibrated")]["expected_calibration_error"],
        )
        warning = check(report, "tiny_test_improvement_is_not_production_claim")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])

    def test_predictions_keep_raw_and_calibrated_scores_without_test_fit(self) -> None:
        report = self.audit()
        rows = {
            (row["split"], row["snapshot_id"]): row
            for row in report["predictions"]
        }

        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[("validation", "S006")]["uncalibrated_score"], 0.5)
        self.assertEqual(rows[("validation", "S006")]["calibrated_score"], 0.555556)
        self.assertEqual(rows[("test", "S010")]["bin_id"], "bin_2")
        self.assertEqual(rows[("test", "S010")]["calibrated_score"], 0.555556)
        self.assertEqual(rows[("test", "S010")]["selected_at_budget_uncalibrated"], 0)
        self.assertEqual(rows[("test", "S010")]["selected_at_budget_calibrated"], 1)
        self.assertEqual({row["trained_on_split"] for row in rows.values()}, {"train"})
        self.assertEqual({row["calibrated_on_split"] for row in rows.values()}, {"validation"})
        self.assertEqual({row["test_used_for_calibration"] for row in rows.values()}, {False})

    def test_threshold_impact_separates_top_k_from_fixed_thresholds(self) -> None:
        report = self.audit()
        rows = {
            (
                row["split"],
                row["probability_source"],
                row["decision_rule"],
                row["threshold"],
            ): row
            for row in report["threshold_impact"]
        }

        self.assertEqual(len(report["threshold_impact"]), 16)
        uncalibrated_topk = rows[("test", "uncalibrated", "rank_top_k_within_scoring_batch", "")]
        calibrated_topk = rows[("test", "calibrated", "rank_top_k_within_scoring_batch", "")]
        uncalibrated_threshold = rows[("test", "uncalibrated", "fixed_threshold", 0.5)]
        calibrated_threshold = rows[("test", "calibrated", "fixed_threshold", 0.5)]
        self.assertEqual(uncalibrated_topk["precision"], 0.0)
        self.assertEqual(uncalibrated_topk["selected_ids"], "S009,S012")
        self.assertEqual(calibrated_topk["precision"], 0.5)
        self.assertEqual(calibrated_topk["selected_ids"], "S010,S009")
        self.assertEqual(uncalibrated_threshold["action_count"], 3)
        self.assertTrue(uncalibrated_threshold["budget_exceeded"])
        self.assertEqual(calibrated_threshold["action_count"], 1)
        self.assertFalse(calibrated_threshold["budget_exceeded"])
        warning = check(report, "fixed_threshold_action_count_changes_after_calibration")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])

    def test_serialized_spec_records_validation_only_calibrator(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["calibration_policy_id"], "trial-churn-calibration-policy-v0")
        self.assertEqual(
            serialized["source_model_id"],
            "random_forest_depth2_class_weight_balanced",
        )
        self.assertEqual(serialized["calibration_method"]["prior_positive_rate"], 0.333333)
        self.assertEqual(len(serialized["calibration_method"]["learned_bin_map"]), 3)
        self.assertFalse(serialized["test_used_for_calibration"])
        self.assertEqual(serialized["fit_trace"][0]["fit_split"], "train")
        self.assertEqual(serialized["fit_trace"][0]["test_ids_seen"], [])
        self.assertEqual(serialized["fit_trace"][1]["fit_split"], "validation")
        self.assertEqual(serialized["fit_trace"][1]["calibration_ids"], ["S005", "S006", "S007"])
        self.assertEqual(serialized["fit_trace"][1]["test_ids_seen"], [])

    def test_code_example_writes_calibration_artifacts(self) -> None:
        report_path = LESSON_ROOT / "outputs" / "calibration_report.json"
        bins_path = LESSON_ROOT / "outputs" / "calibration_bins.csv"
        metrics_path = LESSON_ROOT / "outputs" / "calibration_metrics.csv"
        predictions_path = LESSON_ROOT / "outputs" / "calibrated_predictions.csv"
        threshold_path = LESSON_ROOT / "outputs" / "calibration_threshold_impact.csv"
        audit_path = LESSON_ROOT / "outputs" / "calibration_policy_audit.csv"
        serialized_path = LESSON_ROOT / "outputs" / "calibration_serialized_spec.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["calibration_policy_id"], "trial-churn-calibration-policy-v0")
        self.assertEqual(payload["calibrated_test_brier"], 0.079012)
        self.assertEqual(payload["test_fixed_threshold_0_5_action_count_calibrated"], 1)
        self.assertEqual(read_json(report_path)["summary"]["calibration_row_count"], 3)
        self.assertEqual(len(read_csv(bins_path)), 6)
        self.assertEqual(len(read_csv(metrics_path)), 4)
        self.assertEqual(len(read_csv(predictions_path)), 8)
        self.assertEqual(len(read_csv(threshold_path)), 16)
        self.assertEqual(len(read_csv(audit_path)), 12)
        self.assertEqual(
            read_json(serialized_path)["source_model_id"],
            payload["source_model_id"],
        )

    def test_data_generator_check_rebuilds_committed_calibration_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)
        self.assertTrue((DATA_ROOT / "calibration_policy_spec.json").exists())

    def test_calibration_on_test_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "calibration_policy_spec.json")
            spec["calibration_split"] = "test"
            write_json(root / "calibration_policy_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "calibration_policy_spec_declares_probability_contract")
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertIn(
            "calibration_policy_spec_declares_probability_contract",
            report["summary"]["blocking_errors"],
        )

    def test_source_model_must_match_imbalance_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "calibration_policy_spec.json")
            spec["source_model_id"] = "random_forest_depth2_unweighted"
            write_json(root / "calibration_policy_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "calibration_policy_spec_declares_probability_contract")
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["sample"][0]["field"], "source_model_id")

    def test_brier_and_log_loss_are_required(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "calibration_policy_spec.json")
            spec["metrics"]["proper_scoring_rules"] = ["brier_score"]
            write_json(root / "calibration_policy_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "calibration_policy_spec_declares_probability_contract")
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["sample"][0]["field"], "metrics.proper_scoring_rules")

    def test_cli_writes_report_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "calibration_policy_spec.json")
            spec["audit_policy"]["forbid_calibration_on_test"] = False
            write_json(root / "calibration_policy_spec.json", spec)
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
                    "--calibration-policy-spec",
                    root / "calibration_policy_spec.json",
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
            "calibration_policy_spec_declares_probability_contract",
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
                "--calibration-policy-spec",
                DATA_ROOT / "calibration_policy_spec.json",
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
        self.assertIn("calibration_sample_below_minimum", result.stdout)
