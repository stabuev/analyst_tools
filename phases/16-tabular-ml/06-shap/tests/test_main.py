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
ARTIFACT = LESSON_ROOT / "outputs" / "shap_explanation_reporter.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from shap_explanation_reporter import (  # noqa: E402
    DEFAULT_BUILT_IN_REPORT_PATH,
    DEFAULT_BUILT_IN_SPEC_PATH,
    DEFAULT_CATEGORICAL_REPORT_PATH,
    DEFAULT_EARLY_STOPPING_REPORT_PATH,
    DEFAULT_EARLY_STOPPING_SPEC_PATH,
    DEFAULT_PERMUTATION_REPORT_PATH,
    DEFAULT_PERMUTATION_SPEC_PATH,
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


class ShapExplanationReporterTest(TestCase):
    def audit(
        self,
        root: Path = DATA_ROOT,
        upstream_root: Path = UPSTREAM_DATA_ROOT,
        **paths: Path,
    ) -> dict:
        return run(
            policy_path=paths.get("policy_path", root / "shap_explanation_policy_spec.json"),
            catboost_spec_path=paths.get("catboost_spec_path", root / "catboost_model_spec.json"),
            early_stopping_report_path=paths.get("early_stopping_report_path", DEFAULT_EARLY_STOPPING_REPORT_PATH),
            early_stopping_spec_path=paths.get("early_stopping_spec_path", DEFAULT_EARLY_STOPPING_SPEC_PATH),
            categorical_report_path=paths.get("categorical_report_path", DEFAULT_CATEGORICAL_REPORT_PATH),
            built_in_report_path=paths.get("built_in_report_path", DEFAULT_BUILT_IN_REPORT_PATH),
            built_in_spec_path=paths.get("built_in_spec_path", DEFAULT_BUILT_IN_SPEC_PATH),
            permutation_report_path=paths.get("permutation_report_path", DEFAULT_PERMUTATION_REPORT_PATH),
            permutation_spec_path=paths.get("permutation_spec_path", DEFAULT_PERMUTATION_SPEC_PATH),
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
        for filename in ("shap_explanation_policy_spec.json", "catboost_model_spec.json"):
            shutil.copy2(DATA_ROOT / filename, phase16 / filename)
        for filename in ("ml_raw_features.csv", "ml_labels.csv", "ml_split_manifest.csv"):
            shutil.copy2(UPSTREAM_DATA_ROOT / filename, upstream / filename)
        shutil.copy2(DEFAULT_EARLY_STOPPING_REPORT_PATH, reports / "early_stopping_report.json")
        shutil.copy2(DEFAULT_EARLY_STOPPING_SPEC_PATH, reports / "early_stopping_serialized_spec.json")
        shutil.copy2(DEFAULT_CATEGORICAL_REPORT_PATH, reports / "categorical_feature_report.json")
        shutil.copy2(DEFAULT_BUILT_IN_REPORT_PATH, reports / "built_in_importance_report.json")
        shutil.copy2(DEFAULT_BUILT_IN_SPEC_PATH, reports / "built_in_importance_serialized_spec.json")
        shutil.copy2(DEFAULT_PERMUTATION_REPORT_PATH, reports / "permutation_importance_report.json")
        shutil.copy2(DEFAULT_PERMUTATION_SPEC_PATH, reports / "permutation_importance_serialized_spec.json")
        return phase16, upstream, reports

    def test_valid_report_records_background_output_additivity_and_warnings(self) -> None:
        report = self.audit()
        summary = report["summary"]

        self.assertTrue(report["valid"])
        self.assertEqual(summary["shap_explanation_audit_id"], "trial-churn-shap-explanation-audit-v0")
        self.assertEqual(summary["early_stopping_model_id"], "catboost_depth2_native_categories_es_logloss")
        self.assertEqual(summary["permutation_importance_audit_id"], "trial-churn-permutation-importance-audit-v0")
        self.assertEqual(summary["background_split"], "train")
        self.assertEqual(summary["background_row_count"], 4)
        self.assertEqual(summary["explain_split"], "validation")
        self.assertEqual(summary["explain_row_count"], 3)
        self.assertEqual(summary["output_space"], "raw_margin")
        self.assertEqual(summary["expected_value"], 0.0)
        self.assertEqual(summary["additivity_max_abs_error"], 0.0)
        self.assertEqual(summary["additivity_passed_row_count"], 3)
        self.assertEqual(summary["global_summary_row_count"], 10)
        self.assertEqual(summary["local_explanation_row_count"], 3)
        self.assertEqual(summary["top_mean_abs_shap_feature"], "platform")
        self.assertEqual(summary["top_mean_abs_shap_value"], 0.030769)
        self.assertEqual(summary["top_contribution_direction"], "mixed")
        self.assertEqual(summary["disagreement_row_count"], 4)
        self.assertEqual(summary["warning_ledger_row_count"], 12)
        self.assertEqual(summary["readiness_status"], "ready_for_segment_analysis_lesson")
        self.assertEqual(
            summary["warnings"],
            [
                "high_cardinality_features_flagged_for_shap_explanations",
                "correlated_features_can_share_shap_attribution",
                "tiny_background_reference_makes_shap_baseline_unstable",
                "tiny_explanation_sample_makes_global_shap_unstable",
                "tiny_tree_count_makes_shap_explanations_unstable",
                "poor_or_flat_model_score_limits_shap_claims",
                "raw_margin_output_is_not_probability",
                "tree_path_dependent_background_required_for_catboost_categories",
            ],
        )

    def test_global_summary_ranks_platform_and_keeps_zero_features(self) -> None:
        report = self.audit()
        rows = {row["feature_name"]: row for row in report["global_summary"]}
        platform = rows["platform"]

        self.assertEqual(platform["feature_role"], "categorical")
        self.assertEqual(platform["output_space"], "raw_margin")
        self.assertEqual(platform["mean_abs_shap"], 0.030769)
        self.assertEqual(platform["mean_shap_value"], -0.010256)
        self.assertEqual(platform["std_shap_value"], 0.02901)
        self.assertEqual(platform["positive_row_count"], 1)
        self.assertEqual(platform["negative_row_count"], 2)
        self.assertEqual(platform["nonzero_row_count"], 3)
        self.assertEqual(platform["rank_by_mean_abs_shap"], 1)
        self.assertTrue(platform["is_top_mean_abs_shap_feature"])
        self.assertEqual(platform["contribution_direction"], "mixed")
        self.assertEqual(rows["sessions_14d"]["rank_by_mean_abs_shap"], 2)
        self.assertEqual(rows["acquisition_channel"]["rank_by_mean_abs_shap"], 10)
        self.assertEqual(rows["acquisition_channel"]["mean_abs_shap"], 0.0)

    def test_local_explanations_show_raw_margin_contributions_for_declared_rows(self) -> None:
        report = self.audit()
        rows = {row["snapshot_id"]: row for row in report["local_explanations"]}

        self.assertEqual(set(rows), {"S005", "S006", "S007"})
        self.assertEqual(rows["S005"]["feature_name"], "platform")
        self.assertEqual(rows["S005"]["feature_value"], "ios")
        self.assertEqual(rows["S005"]["raw_prediction"], -0.030769)
        self.assertEqual(rows["S005"]["predicted_probability"], 0.492308)
        self.assertEqual(rows["S005"]["shap_value"], -0.030769)
        self.assertEqual(rows["S005"]["contribution_direction"], "negative")
        self.assertEqual(rows["S006"]["feature_value"], "web")
        self.assertEqual(rows["S006"]["target"], 1)
        self.assertEqual(rows["S007"]["feature_value"], "android")
        self.assertEqual(rows["S007"]["predicted_probability"], 0.507692)
        self.assertEqual(rows["S007"]["shap_value"], 0.030769)
        self.assertEqual(rows["S007"]["contribution_direction"], "positive")

    def test_additivity_audit_reconstructs_raw_formula_values(self) -> None:
        report = self.audit()
        rows = {row["snapshot_id"]: row for row in report["additivity_audit"]}

        self.assertEqual(set(rows), {"S005", "S006", "S007"})
        self.assertTrue(all(row["passes_additivity"] for row in rows.values()))
        self.assertEqual(rows["S005"]["expected_value"], 0.0)
        self.assertEqual(rows["S005"]["shap_sum"], -0.030769)
        self.assertEqual(rows["S005"]["model_raw_prediction"], -0.030769)
        self.assertEqual(rows["S005"]["reconstructed_raw_prediction"], -0.030769)
        self.assertEqual(rows["S005"]["absolute_error"], 0.0)
        self.assertEqual(rows["S007"]["shap_sum"], 0.030769)

    def test_background_and_explain_rows_exclude_final_test(self) -> None:
        report = self.audit()
        background = check(report, "background_reference_uses_train_and_excludes_test")
        explain = check(report, "explain_rows_use_validation_and_exclude_final_test")
        serialized = report["serialized_spec"]

        self.assertTrue(background["valid"])
        self.assertEqual(background["observed"]["snapshot_ids"], ["S001", "S002", "S003", "S004"])
        self.assertFalse(background["observed"]["external_background_data_passed"])
        self.assertTrue(explain["valid"])
        self.assertEqual(explain["observed"]["snapshot_ids"], ["S005", "S006", "S007"])
        self.assertEqual(explain["observed"]["final_test_rows_used"], 0)
        self.assertNotIn("S009", serialized["explanation_summary"]["snapshot_ids"])

    def test_disagreement_table_does_not_hide_conflicting_method_meanings(self) -> None:
        report = self.audit()
        rows = {row["method"]: row for row in report["disagreement"]}

        self.assertEqual(set(rows), {"CatBoost PredictionValuesChange", "CatBoost LossFunctionChange", "Permutation importance", "Tree SHAP mean_abs"})
        self.assertTrue(all(row["top_feature_name"] == "platform" for row in rows.values()))
        self.assertTrue(all(row["disagreement_status"] == "same_top_feature_conflicting_direction_or_scope" for row in rows.values()))
        self.assertEqual(rows["CatBoost PredictionValuesChange"]["raw_value"], 100.0)
        self.assertEqual(rows["CatBoost PredictionValuesChange"]["direction"], "positive")
        self.assertEqual(rows["CatBoost LossFunctionChange"]["raw_value"], -0.005247)
        self.assertEqual(rows["CatBoost LossFunctionChange"]["direction"], "negative")
        self.assertEqual(rows["Permutation importance"]["raw_value"], -0.011722)
        self.assertEqual(rows["Permutation importance"]["direction"], "loss_decrease_when_permuted")
        self.assertEqual(rows["Tree SHAP mean_abs"]["raw_value"], 0.030769)
        self.assertEqual(rows["Tree SHAP mean_abs"]["direction"], "mixed")

    def test_warning_ledger_names_high_cardinality_correlation_tiny_score_raw_and_background_limits(self) -> None:
        report = self.audit()
        rows_by_id = {}
        for row in report["warning_ledger"]:
            rows_by_id.setdefault(row["warning_id"], []).append(row)

        self.assertEqual(rows_by_id["high_cardinality_features_flagged_for_shap_explanations"][0]["feature_name"], "acquisition_channel")
        self.assertEqual(len(rows_by_id["correlated_features_can_share_shap_attribution"]), 5)
        self.assertEqual(rows_by_id["tiny_background_reference_makes_shap_baseline_unstable"][0]["observed"], 4)
        self.assertEqual(rows_by_id["tiny_explanation_sample_makes_global_shap_unstable"][0]["observed"], 3)
        self.assertEqual(rows_by_id["tiny_tree_count_makes_shap_explanations_unstable"][0]["observed"], 1)
        self.assertEqual(rows_by_id["poor_or_flat_model_score_limits_shap_claims"][0]["observed"], 0.698394)
        self.assertEqual(rows_by_id["raw_margin_output_is_not_probability"][0]["observed"], "raw_margin")
        self.assertEqual(
            rows_by_id["tree_path_dependent_background_required_for_catboost_categories"][0]["observed"],
            "catboost_tree_path_dependent_training_path_counts",
        )

    def test_serialized_spec_records_handoff_for_segment_analysis(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["shap_version"], "0.51.0")
        self.assertEqual(serialized["explainer"]["feature_perturbation"], "tree_path_dependent")
        self.assertFalse(serialized["explainer"]["external_background_data_passed"])
        self.assertEqual(serialized["background_summary"]["snapshot_ids"], ["S001", "S002", "S003", "S004"])
        self.assertEqual(serialized["explanation_summary"]["raw_predictions"], [-0.030769, -0.030769, 0.030769])
        self.assertEqual(serialized["additivity_summary"]["passed_row_count"], 3)
        self.assertEqual(serialized["top_summary"]["top_mean_abs_shap_feature"], "platform")
        self.assertEqual(serialized["disagreement_summary"]["disagreement_status"], "same_top_feature_conflicting_direction_or_scope")
        self.assertEqual(serialized["upstream_handoff"]["permutation_readiness_status"], "ready_for_shap_lesson")

    def test_code_example_writes_all_shap_outputs(self) -> None:
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["explain_split"], "validation")
        self.assertEqual(payload["background_row_count"], 4)
        self.assertEqual(payload["explain_row_count"], 3)
        self.assertEqual(payload["output_space"], "raw_margin")
        self.assertEqual(payload["additivity_max_abs_error"], 0.0)
        self.assertEqual(payload["top_mean_abs_shap_feature"], "platform")
        self.assertEqual(payload["warning_count"], 8)
        self.assertEqual(payload["readiness_status"], "ready_for_segment_analysis_lesson")
        self.assertEqual(read_json(LESSON_ROOT / "outputs" / "shap_explanation_report.json")["summary"]["warning_ledger_row_count"], 12)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "shap_global_summary.csv")), 10)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "shap_local_explanations.csv")), 3)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "shap_additivity_audit.csv")), 3)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "explanation_disagreement.csv")), 4)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "shap_warning_ledger.csv")), 12)

    def test_fail_on_warning_returns_two_without_blocking_report(self) -> None:
        result = subprocess.run([sys.executable, ARTIFACT, "--fail-on-warning"], check=False, capture_output=True, text=True)

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["warning_count"], 8)

    def test_invalid_permutation_handoff_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            permutation_report = read_json(reports / "permutation_importance_report.json")
            permutation_report["summary"]["readiness_status"] = "blocked_by_permutation_importance_policy"
            write_json(reports / "permutation_importance_report.json", permutation_report)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
                built_in_report_path=reports / "built_in_importance_report.json",
                built_in_spec_path=reports / "built_in_importance_serialized_spec.json",
                permutation_report_path=reports / "permutation_importance_report.json",
                permutation_spec_path=reports / "permutation_importance_serialized_spec.json",
            )

        self.assertFalse(report["valid"])
        handoff = check(report, "shap_policy_matches_permutation_handoff")
        self.assertFalse(handoff["valid"])
        self.assertIn("shap_policy_matches_permutation_handoff", report["summary"]["blocking_errors"])

    def test_probability_output_space_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "shap_explanation_policy_spec.json")
            policy["explainer"]["model_output"] = "probability"
            policy["explainer"]["output_space"] = "probability"
            write_json(phase16 / "shap_explanation_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
                built_in_report_path=reports / "built_in_importance_report.json",
                built_in_spec_path=reports / "built_in_importance_serialized_spec.json",
                permutation_report_path=reports / "permutation_importance_report.json",
                permutation_spec_path=reports / "permutation_importance_serialized_spec.json",
            )

        self.assertFalse(report["valid"])
        policy_check = check(report, "shap_policy_declares_background_output_additivity_and_limits")
        self.assertFalse(policy_check["valid"])
        self.assertIn("explainer.output_space", {error["field"] for error in policy_check["observed"]})

    def test_local_snapshot_outside_validation_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "shap_explanation_policy_spec.json")
            policy["local_explanations"]["snapshot_ids"] = ["S005", "S009"]
            write_json(phase16 / "shap_explanation_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
                built_in_report_path=reports / "built_in_importance_report.json",
                built_in_spec_path=reports / "built_in_importance_serialized_spec.json",
                permutation_report_path=reports / "permutation_importance_report.json",
                permutation_spec_path=reports / "permutation_importance_serialized_spec.json",
            )

        self.assertFalse(report["valid"])
        explain = check(report, "explain_rows_use_validation_and_exclude_final_test")
        self.assertFalse(explain["valid"])
        self.assertEqual(explain["observed"]["unknown_local_snapshot_ids"], ["S009"])

    def test_positive_causal_or_fairness_claim_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "shap_explanation_policy_spec.json")
            policy["interpretation_policy"]["claim"] = "platform causes churn and fairness certified production stable"
            write_json(phase16 / "shap_explanation_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
                built_in_report_path=reports / "built_in_importance_report.json",
                built_in_spec_path=reports / "built_in_importance_serialized_spec.json",
                permutation_report_path=reports / "permutation_importance_report.json",
                permutation_spec_path=reports / "permutation_importance_serialized_spec.json",
            )

        self.assertFalse(report["valid"])
        policy_check = check(report, "shap_policy_declares_background_output_additivity_and_limits")
        self.assertFalse(policy_check["valid"])
        self.assertEqual(policy_check["observed"][0]["field"], "interpretation_policy.claim")
        self.assertEqual(
            policy_check["observed"][0]["forbidden_terms"],
            ["causes churn", "fairness certified", "production stable"],
        )
