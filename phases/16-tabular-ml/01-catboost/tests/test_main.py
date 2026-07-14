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
REPO_ROOT = LESSON_ROOT.parents[2]
PHASE_15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"
ARTIFACT = LESSON_ROOT / "outputs" / "catboost_baseline_trainer.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from catboost_baseline_trainer import (  # noqa: E402
    DEFAULT_BASELINE_PACKAGE_REPORT_PATH,
    DEFAULT_IMBALANCE_REPORT_PATH,
    run,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class CatBoostBaselineTrainerTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, upstream_root: Path = UPSTREAM_DATA_ROOT, **paths: Path) -> dict:
        return run(
            spec_path=paths.get("spec_path", root / "catboost_model_spec.json"),
            problem_spec_path=paths.get("problem_spec_path", upstream_root / "problem_spec.json"),
            features_path=paths.get("features_path", upstream_root / "ml_raw_features.csv"),
            labels_path=paths.get("labels_path", upstream_root / "ml_labels.csv"),
            manifest_path=paths.get("manifest_path", upstream_root / "ml_split_manifest.csv"),
            baseline_package_report_path=paths.get(
                "baseline_package_report_path",
                DEFAULT_BASELINE_PACKAGE_REPORT_PATH,
            ),
            imbalance_report_path=paths.get("imbalance_report_path", DEFAULT_IMBALANCE_REPORT_PATH),
        )

    def copy_inputs(self, directory: Path) -> tuple[Path, Path, Path]:
        phase16 = directory / "phase16"
        upstream = directory / "upstream"
        reports = directory / "reports"
        phase16.mkdir()
        upstream.mkdir()
        reports.mkdir()

        shutil.copy2(DATA_ROOT / "catboost_model_spec.json", phase16 / "catboost_model_spec.json")
        for filename in (
            "problem_spec.json",
            "ml_raw_features.csv",
            "ml_labels.csv",
            "ml_split_manifest.csv",
        ):
            shutil.copy2(UPSTREAM_DATA_ROOT / filename, upstream / filename)
        shutil.copy2(DEFAULT_BASELINE_PACKAGE_REPORT_PATH, reports / "ml_baseline_package_report.json")
        shutil.copy2(DEFAULT_IMBALANCE_REPORT_PATH, reports / "imbalance_report.json")
        return phase16, upstream, reports

    def test_valid_catboost_baseline_exports_comparison_package(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["catboost_baseline_id"], "trial-churn-catboost-baseline-v0")
        self.assertEqual(report["summary"]["catboost_version"], "1.2.10")
        self.assertEqual(report["summary"]["fit_split"], "train")
        self.assertEqual(report["summary"]["fit_row_count"], 4)
        self.assertEqual(report["summary"]["selection_split"], "validation")
        self.assertEqual(report["summary"]["final_holdout_split"], "test")
        self.assertEqual(report["summary"]["model_id"], "catboost_depth2_native_categories")
        self.assertEqual(report["summary"]["tree_count"], 20)
        self.assertEqual(report["summary"]["prediction_row_count"], 12)
        self.assertEqual(
            report["summary"]["cat_features"],
            ["plan_id", "platform", "country", "acquisition_channel"],
        )
        self.assertEqual(
            report["summary"]["selected_model_id"],
            "random_forest_depth2_class_weight_balanced",
        )
        self.assertFalse(report["summary"]["test_used_for_selection"])
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_categorical_feature_lesson")

    def test_comparison_keeps_phase15_baseline_selected_on_validation(self) -> None:
        report = self.audit()
        rows = {(row["model_id"], row["split"]): row for row in report["comparison"]}
        baseline = rows[("random_forest_depth2_class_weight_balanced", "validation")]
        catboost = rows[("catboost_depth2_native_categories", "validation")]

        self.assertEqual(baseline["precision_at_budget"], 0.5)
        self.assertEqual(baseline["selected_ids"], "S006,S007")
        self.assertEqual(baseline["selection_rank"], 1)
        self.assertTrue(baseline["selected_on_validation"])
        self.assertEqual(catboost["precision_at_budget"], 0.0)
        self.assertEqual(catboost["selected_ids"], "S007,S005")
        self.assertEqual(catboost["selection_rank"], 2)
        self.assertFalse(catboost["selected_on_validation"])
        self.assertEqual(check(report, "catboost_candidate_not_promoted_without_validation_gain")["severity"], "warning")

    def test_predictions_cover_all_splits_with_seeded_scores(self) -> None:
        report = self.audit()
        rows = report["predictions"]
        scores = {row["snapshot_id"]: row["score"] for row in rows}

        self.assertEqual(len(rows), 12)
        self.assertEqual([row["snapshot_id"] for row in rows[:4]], ["S001", "S002", "S003", "S004"])
        self.assertEqual({row["split"] for row in rows}, {"train", "validation", "test"})
        self.assertEqual({row["model_id"] for row in rows}, {"catboost_depth2_native_categories"})
        self.assertEqual({row["trained_on_split"] for row in rows}, {"train"})
        self.assertEqual(
            scores,
            {
                "S001": 0.648694,
                "S002": 0.351306,
                "S003": 0.351306,
                "S004": 0.648694,
                "S005": 0.351306,
                "S006": 0.351306,
                "S007": 0.648694,
                "S009": 0.648694,
                "S010": 0.351306,
                "S011": 0.351306,
                "S012": 0.648694,
                "S013": 0.351306,
            },
        )
        selected_validation = [
            row["snapshot_id"]
            for row in rows
            if row["split"] == "validation" and row["selected_at_budget"] == 1
        ]
        self.assertEqual(selected_validation, ["S005", "S007"])

    def test_training_trace_records_no_test_fit(self) -> None:
        report = self.audit()
        train, validation, test = report["training_trace"]

        self.assertEqual(train["event"], "Pool(train)")
        self.assertTrue(train["fits_model"])
        self.assertEqual(train["snapshot_ids"], "S001,S002,S003,S004")
        self.assertFalse(validation["fits_model"])
        self.assertTrue(validation["used_for_selection"])
        self.assertEqual(validation["snapshot_ids"], "S005,S006,S007")
        self.assertFalse(test["fits_model"])
        self.assertFalse(test["used_for_selection"])
        self.assertTrue(test["used_for_final_holdout"])
        self.assertEqual(test["snapshot_ids"], "S009,S010,S011,S012,S013")

    def test_serialized_spec_records_cat_features_baseline_and_no_promotion(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["model"]["class"], "CatBoostClassifier")
        self.assertEqual(serialized["model"]["catboost_version"], "1.2.10")
        self.assertEqual(serialized["model"]["feature_count"], 10)
        self.assertEqual(
            serialized["model"]["cat_features"],
            ["plan_id", "platform", "country", "acquisition_channel"],
        )
        self.assertEqual(
            serialized["baseline_package"]["package_id"],
            "trial-churn-ml-baseline-package-v0",
        )
        self.assertEqual(
            serialized["selection"]["selected_model_id"],
            "random_forest_depth2_class_weight_balanced",
        )
        self.assertFalse(serialized["selection"]["catboost_candidate_promoted"])
        self.assertFalse(serialized["selection"]["test_used_for_selection"])
        self.assertEqual(serialized["selection"]["catboost_selected_ids_on_validation"], ["S007", "S005"])

    def test_code_example_writes_report_comparison_predictions_trace_and_serialized_spec(self) -> None:
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["model_id"], "catboost_depth2_native_categories")
        self.assertEqual(payload["selected_model_id"], "random_forest_depth2_class_weight_balanced")
        self.assertFalse(payload["test_used_for_selection"])
        self.assertEqual(read_json(LESSON_ROOT / "outputs" / "catboost_report.json")["summary"]["tree_count"], 20)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "catboost_comparison.csv")), 5)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "catboost_predictions.csv")), 12)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "catboost_training_trace.csv")), 3)
        self.assertEqual(
            read_json(LESSON_ROOT / "outputs" / "catboost_serialized_spec.json")["model"]["class"],
            "CatBoostClassifier",
        )

    def test_invalid_baseline_package_blocks_candidate_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            baseline = read_json(reports / "ml_baseline_package_report.json")
            baseline["valid"] = False
            write_json(reports / "ml_baseline_package_report.json", baseline)

            report = self.audit(
                phase16,
                upstream,
                baseline_package_report_path=reports / "ml_baseline_package_report.json",
                imbalance_report_path=reports / "imbalance_report.json",
            )

        self.assertFalse(report["valid"])
        contract = check(report, "baseline_package_is_ready_for_review")
        self.assertFalse(contract["valid"])
        self.assertIn("baseline_package_is_ready_for_review", report["summary"]["blocking_errors"])

    def test_selection_data_must_stay_validation_not_test(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            spec = read_json(phase16 / "catboost_model_spec.json")
            spec["comparison"]["selection_data"] = "test"
            write_json(phase16 / "catboost_model_spec.json", spec)

            report = self.audit(
                phase16,
                upstream,
                baseline_package_report_path=reports / "ml_baseline_package_report.json",
                imbalance_report_path=reports / "imbalance_report.json",
            )

        self.assertFalse(report["valid"])
        contract = check(report, "catboost_spec_declares_reproducible_no_test_selection")
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["observed"][0]["field"], "comparison.selection_data")

    def test_missing_cat_feature_is_rejected_before_fit(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            spec = read_json(phase16 / "catboost_model_spec.json")
            spec["feature_contract"]["categorical_features"].append("plan_name_from_future")
            write_json(phase16 / "catboost_model_spec.json", spec)

            report = self.audit(
                phase16,
                upstream,
                baseline_package_report_path=reports / "ml_baseline_package_report.json",
                imbalance_report_path=reports / "imbalance_report.json",
            )

        self.assertFalse(report["valid"])
        contract = check(report, "feature_contract_matches_table")
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["observed"][0]["missing"], ["plan_name_from_future"])

    def test_target_column_cannot_be_registered_as_cat_feature(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            spec = read_json(phase16 / "catboost_model_spec.json")
            spec["feature_contract"]["categorical_features"].append("churned_14d")
            write_json(phase16 / "catboost_model_spec.json", spec)

            report = self.audit(
                phase16,
                upstream,
                baseline_package_report_path=reports / "ml_baseline_package_report.json",
                imbalance_report_path=reports / "imbalance_report.json",
            )

        self.assertFalse(report["valid"])
        contract = check(report, "feature_contract_matches_table")
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["observed"][0]["field"], "forbidden_columns")

    def test_cli_fail_on_warning_exits_after_writing_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "outputs"
            result = subprocess.run(
                [sys.executable, ARTIFACT, "--output-dir", output_dir, "--fail-on-warning"],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            report_exists = (output_dir / "catboost_report.json").exists()
            predictions_exists = (output_dir / "catboost_predictions.csv").exists()

        self.assertEqual(result.returncode, 2)
        self.assertTrue(payload["audit_valid"])
        self.assertGreater(payload["warning_count"], 0)
        self.assertTrue(report_exists)
        self.assertTrue(predictions_exists)

    def test_missing_problem_spec_returns_structured_failure(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            missing_problem = upstream / "missing_problem_spec.json"

            report = self.audit(
                phase16,
                upstream,
                problem_spec_path=missing_problem,
                baseline_package_report_path=reports / "ml_baseline_package_report.json",
                imbalance_report_path=reports / "imbalance_report.json",
            )

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["blocking_errors"], ["input_files_are_present"])
        self.assertEqual(report["checks"][0]["id"], "input_files_are_present")
