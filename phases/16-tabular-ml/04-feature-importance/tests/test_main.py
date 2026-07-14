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
ARTIFACT = LESSON_ROOT / "outputs" / "built_in_importance_reporter.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from built_in_importance_reporter import (  # noqa: E402
    DEFAULT_CATEGORICAL_REPORT_PATH,
    DEFAULT_EARLY_STOPPING_REPORT_PATH,
    DEFAULT_EARLY_STOPPING_SPEC_PATH,
    run,
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


class BuiltInImportanceReporterTest(TestCase):
    def audit(
        self,
        root: Path = DATA_ROOT,
        upstream_root: Path = UPSTREAM_DATA_ROOT,
        **paths: Path,
    ) -> dict:
        return run(
            policy_path=paths.get("policy_path", root / "built_in_importance_policy_spec.json"),
            catboost_spec_path=paths.get("catboost_spec_path", root / "catboost_model_spec.json"),
            early_stopping_report_path=paths.get("early_stopping_report_path", DEFAULT_EARLY_STOPPING_REPORT_PATH),
            early_stopping_spec_path=paths.get("early_stopping_spec_path", DEFAULT_EARLY_STOPPING_SPEC_PATH),
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
        for filename in ("built_in_importance_policy_spec.json", "catboost_model_spec.json"):
            shutil.copy2(DATA_ROOT / filename, phase16 / filename)
        for filename in ("ml_raw_features.csv", "ml_labels.csv", "ml_split_manifest.csv"):
            shutil.copy2(UPSTREAM_DATA_ROOT / filename, upstream / filename)
        shutil.copy2(DEFAULT_EARLY_STOPPING_REPORT_PATH, reports / "early_stopping_report.json")
        shutil.copy2(DEFAULT_EARLY_STOPPING_SPEC_PATH, reports / "early_stopping_serialized_spec.json")
        shutil.copy2(DEFAULT_CATEGORICAL_REPORT_PATH, reports / "categorical_feature_report.json")
        return phase16, upstream, reports

    def test_valid_report_records_methods_features_and_top_feature(self) -> None:
        report = self.audit()
        summary = report["summary"]

        self.assertTrue(report["valid"])
        self.assertEqual(summary["built_in_importance_audit_id"], "trial-churn-built-in-importance-audit-v0")
        self.assertEqual(summary["early_stopping_model_id"], "catboost_depth2_native_categories_es_logloss")
        self.assertEqual(summary["method_count"], 2)
        self.assertEqual(summary["feature_count"], 10)
        self.assertEqual(summary["importance_row_count"], 20)
        self.assertEqual(summary["feature_name_audit_row_count"], 10)
        self.assertEqual(summary["warning_ledger_row_count"], 8)
        self.assertEqual(summary["top_prediction_values_change_feature"], "platform")
        self.assertEqual(summary["top_loss_function_change_feature"], "platform")
        self.assertEqual(summary["tree_count"], 1)
        self.assertEqual(summary["readiness_status"], "ready_for_permutation_importance_lesson")
        self.assertEqual(
            summary["warnings"],
            [
                "high_cardinality_features_flagged_for_built_in_importance",
                "correlated_features_can_split_builtin_importance",
                "tiny_tree_count_makes_importance_unstable",
                "single_feature_dominates_prediction_values_change",
            ],
        )

    def test_importance_rows_have_method_labels_and_expected_values(self) -> None:
        report = self.audit()
        rows = {(row["method"], row["feature_name"]): row for row in report["importance"]}

        pvc_platform = rows[("PredictionValuesChange", "platform")]
        self.assertEqual(pvc_platform["method_label"], "model_internal_prediction_change")
        self.assertEqual(pvc_platform["interpretation_scope"], "model_internal_diagnostic_not_causal")
        self.assertEqual(pvc_platform["raw_importance"], 100.0)
        self.assertEqual(pvc_platform["normalized_absolute_importance"], 1.0)
        self.assertTrue(pvc_platform["is_top_feature_for_method"])
        self.assertEqual(pvc_platform["rank_within_method"], 1)

        loss_platform = rows[("LossFunctionChange", "platform")]
        self.assertEqual(loss_platform["method_label"], "validation_loss_delta_when_feature_is_removed")
        self.assertTrue(loss_platform["requires_eval_data"])
        self.assertEqual(loss_platform["data_split"], "validation")
        self.assertEqual(loss_platform["raw_importance"], -0.005247)
        self.assertEqual(loss_platform["direction"], "negative")
        self.assertTrue(loss_platform["is_top_feature_for_method"])
        self.assertEqual(rows[("PredictionValuesChange", "acquisition_channel")]["raw_importance"], 0.0)

    def test_feature_name_audit_preserves_training_pool_order_and_risk_flags(self) -> None:
        report = self.audit()
        rows = {row["feature_name"]: row for row in report["feature_name_audit"]}

        self.assertEqual([row["feature_name"] for row in report["feature_name_audit"]][:3], ["sessions_14d", "active_days_14d", "support_tickets_14d"])
        self.assertTrue(all(row["name_matches"] for row in report["feature_name_audit"]))
        self.assertEqual(rows["platform"]["feature_index"], 7)
        self.assertTrue(rows["platform"]["is_categorical"])
        self.assertFalse(rows["platform"]["high_cardinality_feature"])
        self.assertTrue(rows["acquisition_channel"]["high_cardinality_feature"])
        self.assertTrue(rows["sessions_14d"]["correlated_feature"])
        self.assertFalse(rows["plan_id"]["correlated_feature"])
        self.assertTrue(check(report, "feature_names_match_training_pool_order")["valid"])

    def test_warning_ledger_names_high_cardinality_correlation_tree_count_and_dominance(self) -> None:
        report = self.audit()
        warning_ids = {row["warning_id"] for row in report["warning_ledger"]}
        rows_by_id = {}
        for row in report["warning_ledger"]:
            rows_by_id.setdefault(row["warning_id"], []).append(row)

        self.assertEqual(
            warning_ids,
            {
                "high_cardinality_features_flagged_for_built_in_importance",
                "correlated_features_can_split_builtin_importance",
                "tiny_tree_count_makes_importance_unstable",
                "single_feature_dominates_prediction_values_change",
            },
        )
        self.assertEqual(rows_by_id["high_cardinality_features_flagged_for_built_in_importance"][0]["feature_name"], "acquisition_channel")
        self.assertEqual(len(rows_by_id["correlated_features_can_split_builtin_importance"]), 5)
        self.assertEqual(rows_by_id["tiny_tree_count_makes_importance_unstable"][0]["observed"], 1)
        self.assertEqual(rows_by_id["single_feature_dominates_prediction_values_change"][0]["feature_name"], "platform")

    def test_serialized_spec_records_handoff_and_top_features(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["early_stopping_audit_id"], "trial-churn-early-stopping-audit-v0")
        self.assertEqual(serialized["tree_count_summary"]["tree_count"], 1)
        self.assertEqual(serialized["top_features_by_method"]["PredictionValuesChange"]["feature_name"], "platform")
        self.assertEqual(serialized["top_features_by_method"]["LossFunctionChange"]["raw_importance"], -0.005247)
        self.assertEqual(serialized["warning_summary"]["high_cardinality_features"], ["acquisition_channel"])
        self.assertEqual(serialized["warning_summary"]["correlated_pair_count"], 5)
        self.assertEqual(
            serialized["upstream_handoff"]["early_stopping_readiness_status"],
            "ready_for_feature_importance_lesson",
        )

    def test_code_example_writes_all_built_in_importance_outputs(self) -> None:
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["method_count"], 2)
        self.assertEqual(payload["feature_count"], 10)
        self.assertEqual(payload["importance_row_count"], 20)
        self.assertEqual(payload["top_prediction_values_change_feature"], "platform")
        self.assertEqual(read_json(LESSON_ROOT / "outputs" / "built_in_importance_report.json")["summary"]["warning_ledger_row_count"], 8)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "built_in_importance.csv")), 20)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "feature_name_audit.csv")), 10)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "importance_warning_ledger.csv")), 8)
        self.assertEqual(
            read_json(LESSON_ROOT / "outputs" / "built_in_importance_serialized_spec.json")["top_features_by_method"]["PredictionValuesChange"]["feature_name"],
            "platform",
        )

    def test_invalid_early_stopping_report_blocks_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            early_report = read_json(reports / "early_stopping_report.json")
            early_report["summary"]["readiness_status"] = "blocked_by_early_stopping_policy"
            write_json(reports / "early_stopping_report.json", early_report)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        handoff = check(report, "built_in_importance_policy_matches_early_stopping_handoff")
        self.assertFalse(handoff["valid"])
        self.assertIn("built_in_importance_policy_matches_early_stopping_handoff", report["summary"]["blocking_errors"])

    def test_missing_loss_function_change_method_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "built_in_importance_policy_spec.json")
            policy["importance_methods"] = policy["importance_methods"][:1]
            write_json(phase16 / "built_in_importance_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        policy_check = check(report, "importance_policy_declares_methods_feature_names_and_noncausal_scope")
        self.assertFalse(policy_check["valid"])
        self.assertEqual(policy_check["observed"][0]["field"], "importance_methods")

    def test_feature_order_mismatch_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "built_in_importance_policy_spec.json")
            policy["feature_name_policy"]["expected_feature_order"] = list(reversed(policy["feature_name_policy"]["expected_feature_order"]))
            write_json(phase16 / "built_in_importance_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        policy_check = check(report, "importance_policy_declares_methods_feature_names_and_noncausal_scope")
        self.assertFalse(policy_check["valid"])
        self.assertEqual(policy_check["observed"][0]["field"], "feature_name_policy.expected_feature_order")

    def test_positive_causal_claim_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "built_in_importance_policy_spec.json")
            policy["interpretation_policy"]["claim"] = "platform causes churn, so change the product decision"
            write_json(phase16 / "built_in_importance_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        policy_check = check(report, "importance_policy_declares_methods_feature_names_and_noncausal_scope")
        self.assertFalse(policy_check["valid"])
        self.assertEqual(policy_check["observed"][0]["field"], "interpretation_policy.claim")
        self.assertEqual(policy_check["observed"][0]["forbidden_terms"], ["causes churn"])

    def test_missing_categorical_report_blocks_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            missing_report = reports / "missing_categorical_feature_report.json"

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=missing_report,
            )

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["blocking_errors"], ["input_files_are_present"])

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
            report_exists = (output_dir / "built_in_importance_report.json").exists()
            warning_exists = (output_dir / "importance_warning_ledger.csv").exists()

        self.assertEqual(result.returncode, 2)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["warning_count"], 4)
        self.assertTrue(report_exists)
        self.assertTrue(warning_exists)

    def test_missing_policy_returns_structured_failure(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            missing_policy = phase16 / "missing_built_in_importance_policy_spec.json"

            report = self.audit(
                phase16,
                upstream,
                policy_path=missing_policy,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
            )

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["blocking_errors"], ["input_files_are_present"])
        self.assertEqual(report["checks"][0]["id"], "input_files_are_present")
