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
ARTIFACT = LESSON_ROOT / "outputs" / "segment_error_analyzer.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from segment_error_analyzer import SegmentErrorAnalysisError, run  # noqa: E402


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


class SegmentErrorAnalyzerTest(TestCase):
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
            error_analysis_policy_spec_path=root / "error_analysis_policy_spec.json",
            feature_source_inventory_path=root / "feature_source_inventory.csv",
            feature_availability_path=root / "ml_feature_availability.csv",
            feature_selection_log_path=root / "ml_feature_selection_log.csv",
            model_selection_log_path=root / "ml_model_selection_log.csv",
            features_path=root / "ml_raw_features.csv",
            labels_path=root / "ml_labels.csv",
            manifest_path=root / "ml_split_manifest.csv",
            cv_fold_manifest_path=root / "ml_cv_fold_manifest.csv",
            snapshots_path=root / "ml_scoring_snapshots.csv",
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
            "--error-analysis-policy-spec",
            str(root / "error_analysis_policy_spec.json"),
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
            "--snapshots",
            str(root / "ml_scoring_snapshots.csv"),
        ]

    def test_valid_error_analysis_exports_summary(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(
            report["summary"]["error_analysis_policy_id"],
            "trial-churn-error-analysis-policy-v0",
        )
        self.assertEqual(report["summary"]["sklearn_version"], "1.9.0")
        self.assertEqual(report["summary"]["analysis_split"], "test")
        self.assertEqual(report["summary"]["prediction_source"], "calibrated")
        self.assertEqual(report["summary"]["row_count"], 5)
        self.assertEqual(report["summary"]["positive_count"], 1)
        self.assertEqual(report["summary"]["action_count"], 2)
        self.assertEqual(report["summary"]["overall_precision"], 0.5)
        self.assertEqual(report["summary"]["overall_recall"], 1.0)
        self.assertEqual(report["summary"]["overall_error_rate"], 0.2)
        self.assertEqual(report["summary"]["false_positive_count"], 1)
        self.assertEqual(report["summary"]["false_negative_count"], 0)
        self.assertEqual(report["summary"]["slice_metric_row_count"], 23)
        self.assertEqual(report["summary"]["small_n_slice_count"], 19)
        self.assertEqual(report["summary"]["hidden_failure_slice_count"], 4)
        self.assertEqual(report["summary"]["error_example_count"], 1)
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "error_analysis_small_n_slices_visible",
                "error_analysis_hidden_failure_slices_visible",
                "aggregate_metric_not_segment_readiness_claim",
            ],
        )
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_model_card_lesson")

    def test_confusion_rows_keep_test_predictions_and_business_context(self) -> None:
        report = self.audit()
        rows = {row["snapshot_id"]: row for row in report["confusion_rows"]}

        self.assertEqual(set(rows), {"S009", "S010", "S011", "S012", "S013"})
        self.assertEqual({row["split"] for row in rows.values()}, {"test"})
        self.assertEqual(rows["S009"]["confusion_label"], "fp")
        self.assertTrue(rows["S009"]["selected_for_action"])
        self.assertEqual(rows["S009"]["score_band"], "low")
        self.assertEqual(rows["S009"]["acquisition_channel"], "organic")
        self.assertEqual(rows["S010"]["confusion_label"], "tp")
        self.assertEqual(rows["S010"]["score_band"], "high")
        self.assertEqual(rows["S010"]["business_cohort"], "trial_basic:RU")
        self.assertEqual(rows["S011"]["confusion_label"], "tn")
        self.assertFalse(rows["S011"]["selected_for_action"])

    def test_slice_metrics_expose_overall_score_band_and_segment_failures(self) -> None:
        report = self.audit()
        rows = {(row["dimension"], row["slice_value"]): row for row in report["slice_metrics"]}

        overall = rows[("overall", "all")]
        self.assertEqual(overall["tp"], 1)
        self.assertEqual(overall["fp"], 1)
        self.assertEqual(overall["tn"], 3)
        self.assertEqual(overall["fn"], 0)
        self.assertEqual(overall["brier_score"], 0.079012)
        android = rows[("platform", "android")]
        self.assertEqual(android["row_count"], 2)
        self.assertEqual(android["precision"], 0.0)
        self.assertTrue(android["hidden_failure_candidate"])
        self.assertIn("precision_below_overall", android["hidden_failure_reasons"])
        low_band = rows[("score_band", "low")]
        self.assertEqual(low_band["row_count"], 4)
        self.assertEqual(low_band["false_positive_ids"], "S009")
        self.assertTrue(low_band["hidden_failure_candidate"])
        self.assertFalse(low_band["small_n_warning"])
        high_band = rows[("score_band", "high")]
        self.assertEqual(high_band["selected_ids"], "S010")
        self.assertTrue(high_band["small_n_warning"])

    def test_small_n_slices_remain_visible_and_diagnostic_only(self) -> None:
        report = self.audit()
        rows = report["small_n_warnings"]

        self.assertEqual(len(rows), 19)
        segment_rows = [row for row in rows if row["dimension"] == "segment_id"]
        self.assertEqual(len(segment_rows), 5)
        self.assertTrue(all(row["interpretation"] == "diagnostic_only_small_n" for row in rows))
        warning = check(report, "error_analysis_small_n_slices_visible")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])
        self.assertEqual(warning["observed"]["small_n_slice_count"], 19)

    def test_hidden_failure_slices_prevent_aggregate_only_claim(self) -> None:
        report = self.audit()
        hidden = {
            (row["dimension"], row["slice_value"]): row
            for row in report["hidden_failure_slices"]
        }

        self.assertEqual(
            set(hidden),
            {
                ("platform", "android"),
                ("acquisition_channel", "organic"),
                ("business_cohort", "trial_basic:RU"),
                ("score_band", "low"),
            },
        )
        self.assertEqual(hidden[("score_band", "low")]["precision"], 0.0)
        self.assertEqual(hidden[("score_band", "low")]["row_count"], 4)
        warning = check(report, "aggregate_metric_not_segment_readiness_claim")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])
        self.assertEqual(warning["observed"]["hidden_failure_slice_count"], 4)

    def test_error_examples_list_false_positive_without_false_negative(self) -> None:
        report = self.audit()

        self.assertEqual(len(report["error_examples"]), 1)
        example = report["error_examples"][0]
        self.assertEqual(example["snapshot_id"], "S009")
        self.assertEqual(example["confusion_label"], "fp")
        self.assertTrue(example["false_positive"])
        self.assertFalse(example["false_negative"])

    def test_serialized_spec_records_leakage_handoff_and_slice_policy(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(
            serialized["error_analysis_policy_id"],
            "trial-churn-error-analysis-policy-v0",
        )
        self.assertEqual(
            serialized["upstream_leakage_summary"]["leakage_policy_id"],
            "trial-churn-leakage-policy-v0",
        )
        self.assertEqual(
            serialized["upstream_leakage_summary"]["readiness_status"],
            "ready_for_error_analysis_lesson",
        )
        self.assertFalse(serialized["upstream_leakage_summary"]["test_used_for_model_selection"])
        self.assertEqual(
            serialized["slice_policy"]["required_dimensions"],
            ["segment_id", "platform", "country"],
        )
        self.assertEqual(serialized["score_band_policy"]["bands"][0]["band_id"], "low")

    def test_code_example_writes_error_analysis_artifacts(self) -> None:
        report_path = LESSON_ROOT / "outputs" / "error_analysis_report.json"
        confusion_path = LESSON_ROOT / "outputs" / "confusion_rows.csv"
        slice_path = LESSON_ROOT / "outputs" / "slice_metrics.csv"
        small_n_path = LESSON_ROOT / "outputs" / "small_n_warnings.csv"
        hidden_path = LESSON_ROOT / "outputs" / "hidden_failure_slices.csv"
        examples_path = LESSON_ROOT / "outputs" / "error_examples.csv"
        audit_path = LESSON_ROOT / "outputs" / "error_analysis_policy_audit.csv"
        serialized_path = LESSON_ROOT / "outputs" / "error_analysis_serialized_spec.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["error_analysis_policy_id"], "trial-churn-error-analysis-policy-v0")
        self.assertEqual(payload["row_count"], 5)
        self.assertEqual(payload["hidden_failure_slice_count"], 4)
        self.assertEqual(read_json(report_path)["summary"]["slice_metric_row_count"], 23)
        self.assertEqual(len(read_csv(confusion_path)), 5)
        self.assertEqual(len(read_csv(slice_path)), 23)
        self.assertEqual(len(read_csv(small_n_path)), 19)
        self.assertEqual(len(read_csv(hidden_path)), 4)
        self.assertEqual(len(read_csv(examples_path)), 1)
        self.assertEqual(len(read_csv(audit_path)), 9)
        self.assertEqual(
            read_json(serialized_path)["source_model_id"],
            "random_forest_depth2_class_weight_balanced",
        )

    def test_data_generator_check_rebuilds_committed_error_analysis_spec(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)
        self.assertTrue((DATA_ROOT / "error_analysis_policy_spec.json").exists())

    def test_upstream_leakage_failure_blocks_before_error_analysis(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_feature_availability.csv")
            for row in rows:
                if row["feature_name"] == "churned_14d":
                    row["used_in_delivery_model"] = "true"
            write_csv(root / "ml_feature_availability.csv", rows)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn("upstream_leakage_handoff_is_valid", report["summary"]["blocking_errors"])
        self.assertEqual(report["summary"]["readiness_status"], "blocked_before_error_analysis")

    def test_policy_without_required_country_slice_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "error_analysis_policy_spec.json")
            spec["slice_policy"]["required_dimensions"] = ["segment_id", "platform"]
            write_json(root / "error_analysis_policy_spec.json", spec)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn(
            "error_analysis_policy_spec_declares_slice_contract",
            report["summary"]["blocking_errors"],
        )

    def test_missing_snapshot_metadata_is_structured_runtime_failure_in_cli(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = [row for row in read_csv(root / "ml_scoring_snapshots.csv") if row["snapshot_id"] != "S009"]
            write_csv(root / "ml_scoring_snapshots.csv", rows)
            output = Path(directory) / "report.json"
            result = subprocess.run(
                self.cli_args(root) + ["--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            report = read_json(output)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["blocking_errors"], ["segment_error_analysis_runtime_error"])
        self.assertIn("feature or manifest metadata", report["checks"][0]["observed"])

    def test_direct_run_raises_for_missing_snapshot_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = [row for row in read_csv(root / "ml_scoring_snapshots.csv") if row["snapshot_id"] != "S010"]
            write_csv(root / "ml_scoring_snapshots.csv", rows)

            with self.assertRaises(SegmentErrorAnalysisError):
                self.audit(root)

    def test_cli_invalid_spec_returns_nonzero_and_writes_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            output = Path(directory) / "report.json"
            spec = read_json(root / "error_analysis_policy_spec.json")
            spec["analysis_split"] = "validation"
            write_json(root / "error_analysis_policy_spec.json", spec)
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
            "error_analysis_policy_spec_declares_slice_contract",
            report["summary"]["blocking_errors"],
        )

    def test_cli_fail_on_warning_returns_nonzero_for_diagnostic_warnings(self) -> None:
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
            "error_analysis_hidden_failure_slices_visible",
            payload["summary"]["warnings"],
        )
