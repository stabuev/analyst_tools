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
PHASE_16_ROOT = REPO_ROOT / "phases" / "16-tabular-ml"
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"
ARTIFACT = LESSON_ROOT / "outputs" / "early_stopping_auditor.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from early_stopping_auditor import (  # noqa: E402
    DEFAULT_CATBOOST_REPORT_PATH,
    DEFAULT_CATEGORICAL_REPORT_PATH,
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


class EarlyStoppingAuditorTest(TestCase):
    def audit(
        self,
        root: Path = DATA_ROOT,
        upstream_root: Path = UPSTREAM_DATA_ROOT,
        **paths: Path,
    ) -> dict:
        return run(
            policy_path=paths.get("policy_path", root / "early_stopping_policy_spec.json"),
            catboost_spec_path=paths.get("catboost_spec_path", root / "catboost_model_spec.json"),
            catboost_report_path=paths.get("catboost_report_path", DEFAULT_CATBOOST_REPORT_PATH),
            categorical_report_path=paths.get("categorical_report_path", DEFAULT_CATEGORICAL_REPORT_PATH),
            features_path=paths.get("features_path", upstream_root / "ml_raw_features.csv"),
            labels_path=paths.get("labels_path", upstream_root / "ml_labels.csv"),
            manifest_path=paths.get("manifest_path", upstream_root / "ml_split_manifest.csv"),
        )

    def copy_inputs(self, directory: Path) -> tuple[Path, Path, Path]:
        phase16 = directory / "phase16"
        upstream = directory / "upstream"
        reports = directory / "reports"
        phase16.mkdir()
        upstream.mkdir()
        reports.mkdir()
        for filename in ("early_stopping_policy_spec.json", "catboost_model_spec.json"):
            shutil.copy2(DATA_ROOT / filename, phase16 / filename)
        for filename in ("ml_raw_features.csv", "ml_labels.csv", "ml_split_manifest.csv"):
            shutil.copy2(UPSTREAM_DATA_ROOT / filename, upstream / filename)
        shutil.copy2(DEFAULT_CATBOOST_REPORT_PATH, reports / "catboost_report.json")
        shutil.copy2(DEFAULT_CATEGORICAL_REPORT_PATH, reports / "categorical_feature_report.json")
        return phase16, upstream, reports

    def test_valid_early_stopping_audit_records_best_iteration_and_budget(self) -> None:
        report = self.audit()
        summary = report["summary"]

        self.assertTrue(report["valid"])
        self.assertEqual(summary["early_stopping_audit_id"], "trial-churn-early-stopping-audit-v0")
        self.assertEqual(summary["source_catboost_model_id"], "catboost_depth2_native_categories")
        self.assertEqual(summary["early_stopping_model_id"], "catboost_depth2_native_categories_es_logloss")
        self.assertEqual(summary["fit_row_count"], 4)
        self.assertEqual(summary["eval_set_row_count"], 3)
        self.assertEqual(summary["final_holdout_row_count"], 5)
        self.assertEqual(summary["planned_iterations"], 80)
        self.assertEqual(summary["baseline_iterations"], 20)
        self.assertEqual(summary["trained_iteration_count"], 4)
        self.assertEqual(summary["best_iteration"], 0)
        self.assertEqual(summary["tree_count"], 1)
        self.assertTrue(summary["stopped_before_budget"])
        self.assertFalse(summary["test_used_for_best_iteration"])
        self.assertEqual(summary["readiness_status"], "ready_for_feature_importance_lesson")
        self.assertEqual(
            summary["warnings"],
            [
                "tiny_training_pool_expected",
                "tiny_eval_set_expected",
                "best_iteration_zero_is_tiny_fixture_warning",
            ],
        )

    def test_eval_set_lineage_uses_validation_not_test(self) -> None:
        report = self.audit()
        rows = {row["split"]: row for row in report["eval_set_lineage"]}

        self.assertEqual(rows["train"]["role"], "fit_pool")
        self.assertTrue(rows["train"]["used_for_fit"])
        self.assertFalse(rows["train"]["used_as_eval_set"])
        self.assertEqual(rows["train"]["snapshot_ids"], "S001,S002,S003,S004")
        self.assertEqual(rows["validation"]["role"], "eval_set_for_overfitting_detector")
        self.assertTrue(rows["validation"]["used_as_eval_set"])
        self.assertTrue(rows["validation"]["used_for_best_iteration"])
        self.assertEqual(rows["validation"]["snapshot_ids"], "S005,S006,S007")
        self.assertEqual(rows["test"]["role"], "final_holdout_prediction_only")
        self.assertFalse(rows["test"]["used_as_eval_set"])
        self.assertFalse(rows["test"]["used_for_best_iteration"])
        self.assertTrue(rows["test"]["used_for_final_holdout"])

    def test_validation_curve_marks_best_iteration_and_patience_window(self) -> None:
        report = self.audit()
        curve = report["validation_curve"]

        self.assertEqual(len(curve), 4)
        self.assertEqual(curve[0]["iteration"], 0)
        self.assertTrue(curve[0]["is_best_iteration"])
        self.assertEqual(curve[0]["iteration_role"], "best_iteration")
        self.assertEqual(curve[0]["validation_logloss"], 0.698394)
        self.assertEqual(curve[-1]["iteration"], 3)
        self.assertEqual(curve[-1]["iteration_role"], "after_best_within_od_wait")
        self.assertEqual(curve[-1]["validation_logloss"], 0.715)
        self.assertGreater(curve[-1]["delta_from_best_validation_logloss"], 0)
        self.assertTrue(check(report, "validation_curve_contains_best_iteration_and_patience_window")["valid"])

    def test_tree_count_report_shows_budget_reduction(self) -> None:
        report = self.audit()
        row = report["tree_count_report"][0]

        self.assertEqual(row["planned_iterations"], 80)
        self.assertEqual(row["baseline_iterations"], 20)
        self.assertEqual(row["trained_iteration_count"], 4)
        self.assertEqual(row["best_iteration"], 0)
        self.assertEqual(row["tree_count"], 1)
        self.assertEqual(row["tree_count_reduction_from_budget"], 79)
        self.assertEqual(row["tree_count_reduction_from_baseline"], 19)
        self.assertTrue(row["stopped_before_budget"])
        self.assertEqual(row["od_type"], "Iter")
        self.assertEqual(row["od_wait"], 3)
        self.assertFalse(row["test_used_for_best_iteration"])

    def test_serialized_spec_records_handoff_for_feature_importance_lesson(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["categorical_audit_id"], "trial-churn-categorical-feature-audit-v0")
        self.assertEqual(serialized["source_catboost_model_id"], "catboost_depth2_native_categories")
        self.assertEqual(serialized["early_stopping_model_id"], "catboost_depth2_native_categories_es_logloss")
        self.assertEqual(serialized["cat_features"], ["plan_id", "platform", "country", "acquisition_channel"])
        self.assertEqual(serialized["tree_count_summary"]["best_iteration"], 0)
        self.assertEqual(serialized["tree_count_summary"]["tree_count"], 1)
        self.assertEqual(serialized["upstream_handoff"]["categorical_readiness_status"], "ready_for_early_stopping_lesson")

    def test_code_example_writes_all_early_stopping_outputs(self) -> None:
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["planned_iterations"], 80)
        self.assertEqual(payload["trained_iteration_count"], 4)
        self.assertEqual(payload["best_iteration"], 0)
        self.assertEqual(payload["tree_count"], 1)
        self.assertEqual(read_json(LESSON_ROOT / "outputs" / "early_stopping_report.json")["summary"]["tree_count"], 1)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "eval_set_lineage.csv")), 3)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "validation_curve.csv")), 4)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "tree_count_report.csv")), 1)
        self.assertEqual(
            read_json(LESSON_ROOT / "outputs" / "early_stopping_serialized_spec.json")["early_stopping_model_id"],
            "catboost_depth2_native_categories_es_logloss",
        )

    def test_invalid_categorical_report_blocks_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            categorical = read_json(reports / "categorical_feature_report.json")
            categorical["summary"]["readiness_status"] = "blocked_by_categorical_feature_contract"
            write_json(reports / "categorical_feature_report.json", categorical)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        handoff = check(report, "early_stopping_policy_matches_upstream_handoff")
        self.assertFalse(handoff["valid"])
        self.assertIn("early_stopping_policy_matches_upstream_handoff", report["summary"]["blocking_errors"])

    def test_invalid_upstream_catboost_report_blocks_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            catboost_report = read_json(reports / "catboost_report.json")
            catboost_report["valid"] = False
            write_json(reports / "catboost_report.json", catboost_report)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        handoff = check(report, "early_stopping_policy_matches_upstream_handoff")
        self.assertFalse(handoff["valid"])

    def test_test_split_cannot_be_eval_set(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "early_stopping_policy_spec.json")
            policy["eval_split"] = "test"
            policy["eval_set_policy"]["allowed_eval_split"] = "test"
            write_json(phase16 / "early_stopping_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        handoff = check(report, "early_stopping_policy_matches_upstream_handoff")
        self.assertFalse(handoff["valid"])
        self.assertEqual(handoff["observed"][0]["field"], "eval_split")

    def test_missing_use_best_model_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "early_stopping_policy_spec.json")
            policy["catboost_params"]["use_best_model"] = False
            policy["training_control"]["use_best_model"] = False
            write_json(phase16 / "early_stopping_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        control = check(report, "early_stopping_policy_declares_reproducible_training_control")
        self.assertFalse(control["valid"])
        self.assertEqual(control["observed"][0]["field"], "use_best_model")

    def test_missing_overfitting_detector_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "early_stopping_policy_spec.json")
            del policy["catboost_params"]["od_type"]
            write_json(phase16 / "early_stopping_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        control = check(report, "early_stopping_policy_declares_reproducible_training_control")
        self.assertFalse(control["valid"])
        self.assertEqual(control["observed"][0]["field"], "catboost_params.od_type")

    def test_missing_validation_split_blocks_before_fit(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            manifest = read_csv(upstream / "ml_split_manifest.csv")
            for row in manifest:
                if row["split"] == "validation":
                    row["split"] = "train"
            write_csv(upstream / "ml_split_manifest.csv", manifest)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        split_check = check(report, "training_table_has_train_validation_test_splits")
        self.assertFalse(split_check["valid"])
        self.assertEqual(report["validation_curve"], [])

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
            report_exists = (output_dir / "early_stopping_report.json").exists()
            curve_exists = (output_dir / "validation_curve.csv").exists()

        self.assertEqual(result.returncode, 2)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["warning_count"], 3)
        self.assertTrue(report_exists)
        self.assertTrue(curve_exists)

    def test_missing_policy_returns_structured_failure(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            missing_policy = phase16 / "missing_early_stopping_policy_spec.json"

            report = self.audit(
                phase16,
                upstream,
                policy_path=missing_policy,
                catboost_report_path=reports / "catboost_report.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["blocking_errors"], ["input_files_are_present"])
        self.assertEqual(report["checks"][0]["id"], "input_files_are_present")
