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
UPSTREAM_DATA_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning" / "data" / "tiny"
ARTIFACT = LESSON_ROOT / "outputs" / "strong_model_segment_analyzer.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from strong_model_segment_analyzer import (  # noqa: E402
    DEFAULT_BASELINE_PACKAGE_REPORT_PATH,
    DEFAULT_EARLY_STOPPING_REPORT_PATH,
    DEFAULT_EARLY_STOPPING_SPEC_PATH,
    DEFAULT_IMBALANCE_PREDICTIONS_PATH,
    DEFAULT_SHAP_REPORT_PATH,
    DEFAULT_SHAP_SPEC_PATH,
    run,
    write_outputs,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class StrongModelSegmentAnalyzerTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, upstream_root: Path = UPSTREAM_DATA_ROOT, **paths: Path) -> dict:
        return run(
            policy_path=paths.get("policy_path", root / "strong_model_segment_policy_spec.json"),
            catboost_spec_path=paths.get("catboost_spec_path", root / "catboost_model_spec.json"),
            early_stopping_report_path=paths.get("early_stopping_report_path", DEFAULT_EARLY_STOPPING_REPORT_PATH),
            early_stopping_spec_path=paths.get("early_stopping_spec_path", DEFAULT_EARLY_STOPPING_SPEC_PATH),
            shap_report_path=paths.get("shap_report_path", DEFAULT_SHAP_REPORT_PATH),
            shap_spec_path=paths.get("shap_spec_path", DEFAULT_SHAP_SPEC_PATH),
            baseline_package_report_path=paths.get("baseline_package_report_path", DEFAULT_BASELINE_PACKAGE_REPORT_PATH),
            imbalance_predictions_path=paths.get("imbalance_predictions_path", DEFAULT_IMBALANCE_PREDICTIONS_PATH),
            features_path=paths.get("features_path", upstream_root / "ml_raw_features.csv"),
            labels_path=paths.get("labels_path", upstream_root / "ml_labels.csv"),
            manifest_path=paths.get("manifest_path", upstream_root / "ml_split_manifest.csv"),
        )

    def test_valid_report_compares_baseline_and_catboost_on_validation(self) -> None:
        report = self.audit()
        summary = report["summary"]

        self.assertTrue(report["valid"])
        self.assertEqual(summary["segment_analysis_audit_id"], "trial-churn-strong-model-segment-audit-v0")
        self.assertEqual(summary["analysis_split"], "validation")
        self.assertEqual(summary["final_holdout_split"], "test")
        self.assertEqual(summary["row_count_per_model"], 3)
        self.assertEqual(summary["baseline_precision"], 0.5)
        self.assertEqual(summary["catboost_precision"], 0.0)
        self.assertEqual(summary["precision_delta"], -0.5)
        self.assertEqual(summary["baseline_recall"], 1.0)
        self.assertEqual(summary["catboost_recall"], 0.0)
        self.assertEqual(summary["error_rate_delta"], 0.666667)
        self.assertEqual(summary["baseline_selected_ids"], "S007,S006")
        self.assertEqual(summary["catboost_selected_ids"], "S007,S005")
        self.assertEqual(summary["confusion_row_count"], 6)
        self.assertEqual(summary["slice_metric_row_count"], 38)
        self.assertEqual(summary["delta_row_count"], 19)
        self.assertEqual(summary["small_n_slice_count"], 36)
        self.assertEqual(summary["hidden_failure_slice_count"], 13)
        self.assertEqual(summary["score_band_shift_count"], 1)
        self.assertEqual(summary["readiness_status"], "ready_for_cost_sensitive_decision_lesson")

    def test_confusion_rows_keep_the_same_rows_and_show_changed_actions(self) -> None:
        report = self.audit()
        rows = {(row["model_role"], row["snapshot_id"]): row for row in report["confusion_rows"]}

        self.assertEqual({snapshot_id for _, snapshot_id in rows}, {"S005", "S006", "S007"})
        self.assertEqual({row["split"] for row in rows.values()}, {"validation"})
        self.assertEqual(rows[("baseline", "S006")]["confusion_label"], "tp")
        self.assertTrue(rows[("baseline", "S006")]["selected_for_action"])
        self.assertEqual(rows[("catboost", "S006")]["confusion_label"], "fn")
        self.assertFalse(rows[("catboost", "S006")]["selected_for_action"])
        self.assertEqual(rows[("baseline", "S005")]["confusion_label"], "tn")
        self.assertEqual(rows[("catboost", "S005")]["confusion_label"], "fp")
        self.assertEqual(rows[("catboost", "S005")]["score"], 0.492308)
        self.assertEqual(rows[("catboost", "S007")]["score"], 0.507692)
        self.assertEqual(rows[("catboost", "S007")]["acquisition_channel"], "__MISSING__")

    def test_slice_metrics_preserve_overall_score_band_and_business_slices(self) -> None:
        report = self.audit()
        rows = {
            (row["model_role"], row["dimension"], row["slice_value"]): row
            for row in report["slice_metrics"]
        }

        baseline = rows[("baseline", "overall", "all")]
        catboost = rows[("catboost", "overall", "all")]
        self.assertEqual(baseline["tp"], 1)
        self.assertEqual(baseline["fp"], 1)
        self.assertEqual(baseline["fn"], 0)
        self.assertEqual(catboost["tp"], 0)
        self.assertEqual(catboost["fp"], 2)
        self.assertEqual(catboost["fn"], 1)
        self.assertEqual(rows[("baseline", "score_band", "high")]["selected_ids"], "S007,S006")
        self.assertEqual(rows[("catboost", "score_band", "medium")]["selected_ids"], "S005")
        self.assertEqual(rows[("catboost", "business_cohort", "trial_pro:RU")]["false_negative_ids"], "S006")
        self.assertTrue(rows[("catboost", "business_cohort", "trial_pro:RU")]["small_n_warning"])
        self.assertFalse(rows[("baseline", "overall", "all")]["small_n_warning"])

    def test_delta_rows_name_where_catboost_is_worse_than_baseline(self) -> None:
        report = self.audit()
        deltas = {(row["dimension"], row["slice_value"]): row for row in report["segment_deltas"]}

        overall = deltas[("overall", "all")]
        self.assertTrue(overall["candidate_worse_than_baseline"])
        self.assertFalse(overall["hidden_failure_candidate"])
        self.assertIn("new_false_positive_ids:S005", overall["hidden_failure_reasons"])
        self.assertIn("new_false_negative_ids:S006", overall["hidden_failure_reasons"])

        ru = deltas[("country", "RU")]
        self.assertEqual(ru["baseline_error_rate"], 0.0)
        self.assertEqual(ru["candidate_error_rate"], 1.0)
        self.assertEqual(ru["precision_delta"], -1.0)
        self.assertTrue(ru["hidden_failure_candidate"])
        self.assertEqual(ru["candidate_false_positive_ids"], "S005")
        self.assertEqual(ru["candidate_false_negative_ids"], "S006")

        android = deltas[("platform", "android")]
        self.assertFalse(android["candidate_worse_than_baseline"])
        self.assertFalse(android["hidden_failure_candidate"])

        high = deltas[("score_band", "high")]
        self.assertEqual(high["baseline_selected_ids"], "S007,S006")
        self.assertEqual(high["candidate_selected_ids"], "S007")
        self.assertEqual(high["error_rate_delta"], 0.5)
        self.assertTrue(high["hidden_failure_candidate"])

    def test_warnings_are_non_blocking_and_name_small_n_hidden_and_band_shift_limits(self) -> None:
        report = self.audit()
        summary = report["summary"]

        self.assertEqual(summary["blocking_errors"], [])
        self.assertEqual(
            summary["warnings"],
            [
                "strong_model_small_n_slices_visible",
                "strong_model_hidden_failure_slices_visible",
                "candidate_worse_than_baseline_on_validation",
                "score_band_membership_differs_between_models",
                "candidate_not_promoted_without_segment_gain",
            ],
        )
        self.assertEqual(check(report, "strong_model_small_n_slices_visible")["severity"], "warning")
        self.assertEqual(check(report, "strong_model_hidden_failure_slices_visible")["severity"], "warning")
        self.assertEqual(check(report, "score_band_membership_differs_between_models")["observed"]["snapshot_ids"], ["S006"])

    def test_score_band_shift_table_marks_model_specific_band_membership(self) -> None:
        report = self.audit()
        shifts = report["score_band_shifts"]

        self.assertEqual(len(shifts), 1)
        self.assertEqual(shifts[0]["snapshot_id"], "S006")
        self.assertEqual(shifts[0]["actual_label"], 1)
        self.assertEqual(shifts[0]["baseline_score"], 0.5)
        self.assertEqual(shifts[0]["candidate_score"], 0.492308)
        self.assertEqual(shifts[0]["baseline_score_band"], "high")
        self.assertEqual(shifts[0]["candidate_score_band"], "medium")
        self.assertTrue(shifts[0]["baseline_selected_for_action"])
        self.assertFalse(shifts[0]["candidate_selected_for_action"])

    def test_serialized_spec_records_selection_summary_and_upstream_handoff(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["analysis_split"], "validation")
        self.assertFalse(serialized["selection_policy"]["test_used_for_segment_analysis"])
        self.assertEqual(serialized["selection_summary"]["baseline_selected_ids"], ["S007", "S006"])
        self.assertEqual(serialized["selection_summary"]["catboost_selected_ids"], ["S007", "S005"])
        self.assertEqual(serialized["selection_summary"]["catboost_false_positive_ids"], ["S007", "S005"])
        self.assertEqual(serialized["selection_summary"]["catboost_false_negative_ids"], ["S006"])
        self.assertEqual(serialized["warning_summary"]["hidden_failure_slice_count"], 13)
        self.assertEqual(serialized["upstream_handoff"]["shap_readiness_status"], "ready_for_segment_analysis_lesson")

    def test_policy_blocks_final_holdout_segment_analysis(self) -> None:
        with TemporaryDirectory() as directory:
            policy_path = Path(directory) / "strong_model_segment_policy_spec.json"
            policy = read_json(DATA_ROOT / "strong_model_segment_policy_spec.json")
            policy["selection_policy"]["test_used_for_segment_analysis"] = True
            write_json(policy_path, policy)

            report = self.audit(policy_path=policy_path)

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["readiness_status"], "blocked_before_segment_analysis")
        self.assertEqual(report["summary"]["blocking_errors"], ["segment_policy_matches_upstream_handoff"])

    def test_writer_and_lesson_cli_export_expected_tables(self) -> None:
        report = self.audit()
        with TemporaryDirectory() as directory:
            output_root = Path(directory)
            output_spec = read_json(DATA_ROOT / "strong_model_segment_policy_spec.json")["output"]
            write_outputs(report, output_root, output_spec)

            deltas = read_csv(output_root / "strong_model_segment_deltas.csv")
            hidden = read_csv(output_root / "strong_model_hidden_failure_slices.csv")

        self.assertEqual(len(deltas), 19)
        self.assertEqual(len(hidden), 13)

        completed = subprocess.run(
            [sys.executable, str(CODE)],
            check=True,
            text=True,
            capture_output=True,
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["hidden_failure_slice_count"], 13)
        self.assertEqual(payload["readiness_status"], "ready_for_cost_sensitive_decision_lesson")

    def test_cli_output_root_writes_all_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            output_root = Path(directory)
            completed = subprocess.run(
                [sys.executable, str(ARTIFACT), "--output-root", str(output_root)],
                check=True,
                text=True,
                capture_output=True,
            )

            self.assertEqual(completed.stdout, "")
            self.assertTrue((output_root / "strong_model_segment_report.json").is_file())
            self.assertTrue((output_root / "strong_model_confusion_rows.csv").is_file())
            self.assertEqual(read_json(output_root / "strong_model_segment_report.json")["summary"]["score_band_shift_count"], 1)
