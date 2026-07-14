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
ARTIFACT = LESSON_ROOT / "outputs" / "permutation_importance_evaluator.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from permutation_importance_evaluator import (  # noqa: E402
    DEFAULT_BUILT_IN_REPORT_PATH,
    DEFAULT_BUILT_IN_SPEC_PATH,
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


class PermutationImportanceEvaluatorTest(TestCase):
    def audit(
        self,
        root: Path = DATA_ROOT,
        upstream_root: Path = UPSTREAM_DATA_ROOT,
        **paths: Path,
    ) -> dict:
        return run(
            policy_path=paths.get("policy_path", root / "permutation_importance_policy_spec.json"),
            catboost_spec_path=paths.get("catboost_spec_path", root / "catboost_model_spec.json"),
            early_stopping_report_path=paths.get("early_stopping_report_path", DEFAULT_EARLY_STOPPING_REPORT_PATH),
            early_stopping_spec_path=paths.get("early_stopping_spec_path", DEFAULT_EARLY_STOPPING_SPEC_PATH),
            categorical_report_path=paths.get("categorical_report_path", DEFAULT_CATEGORICAL_REPORT_PATH),
            built_in_report_path=paths.get("built_in_report_path", DEFAULT_BUILT_IN_REPORT_PATH),
            built_in_spec_path=paths.get("built_in_spec_path", DEFAULT_BUILT_IN_SPEC_PATH),
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
        for filename in ("permutation_importance_policy_spec.json", "catboost_model_spec.json"):
            shutil.copy2(DATA_ROOT / filename, phase16 / filename)
        for filename in ("ml_raw_features.csv", "ml_labels.csv", "ml_split_manifest.csv"):
            shutil.copy2(UPSTREAM_DATA_ROOT / filename, upstream / filename)
        shutil.copy2(DEFAULT_EARLY_STOPPING_REPORT_PATH, reports / "early_stopping_report.json")
        shutil.copy2(DEFAULT_EARLY_STOPPING_SPEC_PATH, reports / "early_stopping_serialized_spec.json")
        shutil.copy2(DEFAULT_CATEGORICAL_REPORT_PATH, reports / "categorical_feature_report.json")
        shutil.copy2(DEFAULT_BUILT_IN_REPORT_PATH, reports / "built_in_importance_report.json")
        shutil.copy2(DEFAULT_BUILT_IN_SPEC_PATH, reports / "built_in_importance_serialized_spec.json")
        return phase16, upstream, reports

    def test_valid_report_records_heldout_scoring_repeats_and_warnings(self) -> None:
        report = self.audit()
        summary = report["summary"]

        self.assertTrue(report["valid"])
        self.assertEqual(summary["permutation_importance_audit_id"], "trial-churn-permutation-importance-audit-v0")
        self.assertEqual(summary["early_stopping_model_id"], "catboost_depth2_native_categories_es_logloss")
        self.assertEqual(summary["built_in_importance_audit_id"], "trial-churn-built-in-importance-audit-v0")
        self.assertEqual(summary["heldout_split"], "validation")
        self.assertEqual(summary["heldout_row_count"], 3)
        self.assertEqual(summary["baseline_log_loss"], 0.698394)
        self.assertEqual(summary["scoring"], "neg_log_loss")
        self.assertEqual(summary["repeat_count"], 7)
        self.assertEqual(summary["feature_count"], 10)
        self.assertEqual(summary["importance_row_count"], 10)
        self.assertEqual(summary["repeat_row_count"], 70)
        self.assertEqual(summary["warning_ledger_row_count"], 9)
        self.assertEqual(summary["largest_absolute_mean_delta_feature"], "platform")
        self.assertEqual(summary["largest_absolute_mean_delta_value"], -0.011722)
        self.assertEqual(summary["positive_mean_feature_count"], 0)
        self.assertEqual(summary["positive_with_two_std_margin_feature_count"], 0)
        self.assertEqual(summary["readiness_status"], "ready_for_shap_lesson")
        self.assertEqual(
            summary["warnings"],
            [
                "high_cardinality_features_flagged_for_permutation_importance",
                "correlated_features_can_mask_permutation_importance",
                "tiny_heldout_sample_makes_permutation_importance_unstable",
                "poor_or_flat_model_score_limits_permutation_importance",
                "no_positive_permutation_signal_with_uncertainty_margin",
            ],
        )

    def test_platform_has_negative_mean_delta_and_repeat_variance(self) -> None:
        report = self.audit()
        rows = {row["feature_name"]: row for row in report["importance"]}
        platform = rows["platform"]

        self.assertEqual(platform["feature_role"], "categorical")
        self.assertEqual(platform["scoring_name"], "neg_log_loss")
        self.assertEqual(platform["importance_unit"], "log_loss_increase_when_feature_is_permuted")
        self.assertEqual(platform["mean_importance"], -0.011722)
        self.assertEqual(platform["std_importance"], 0.010151)
        self.assertEqual(platform["two_std_lower"], -0.032024)
        self.assertEqual(platform["two_std_upper"], 0.008581)
        self.assertFalse(platform["positive_importance_with_two_std_margin"])
        self.assertEqual(platform["absolute_mean_importance"], 0.011722)
        self.assertEqual(platform["nonzero_repeat_count"], 4)
        self.assertEqual(platform["positive_repeat_count"], 0)
        self.assertEqual(platform["negative_repeat_count"], 4)
        self.assertEqual(platform["direction"], "loss_decrease_when_permuted")
        self.assertEqual(platform["rank_by_absolute_mean"], 1)
        self.assertTrue(platform["is_largest_absolute_mean_delta"])
        self.assertEqual(rows["sessions_14d"]["mean_importance"], 0.0)
        self.assertEqual(rows["acquisition_channel"]["rank_by_absolute_mean"], 10)

    def test_repeat_rows_preserve_baseline_and_platform_deltas(self) -> None:
        report = self.audit()
        repeats = [row for row in report["repeats"] if row["feature_name"] == "platform"]

        self.assertEqual(len(repeats), 7)
        self.assertEqual([row["importance_delta"] for row in repeats], [-0.020513, 0.0, 0.0, -0.020513, 0.0, -0.020513, -0.020513])
        self.assertTrue(all(row["baseline_log_loss"] == 0.698394 for row in repeats))
        self.assertEqual(repeats[0]["permuted_log_loss"], 0.677881)
        self.assertEqual(repeats[0]["direction"], "loss_decrease_when_permuted")
        self.assertEqual(repeats[1]["direction"], "zero")

    def test_validation_split_is_used_and_test_is_excluded(self) -> None:
        report = self.audit()
        heldout = check(report, "heldout_rows_use_validation_and_exclude_final_test")
        serialized = report["serialized_spec"]

        self.assertTrue(heldout["valid"])
        self.assertEqual(heldout["observed"]["snapshot_ids"], ["S005", "S006", "S007"])
        self.assertEqual(heldout["observed"]["final_test_rows_used"], 0)
        self.assertEqual(serialized["heldout_summary"]["heldout_snapshot_ids"], ["S005", "S006", "S007"])
        self.assertNotIn("S009", serialized["heldout_summary"]["heldout_snapshot_ids"])

    def test_warning_ledger_names_high_cardinality_correlation_tiny_score_and_uncertainty(self) -> None:
        report = self.audit()
        rows_by_id = {}
        for row in report["warning_ledger"]:
            rows_by_id.setdefault(row["warning_id"], []).append(row)

        self.assertEqual(rows_by_id["high_cardinality_features_flagged_for_permutation_importance"][0]["feature_name"], "acquisition_channel")
        self.assertEqual(len(rows_by_id["correlated_features_can_mask_permutation_importance"]), 5)
        self.assertEqual(rows_by_id["tiny_heldout_sample_makes_permutation_importance_unstable"][0]["observed"], 3)
        self.assertEqual(rows_by_id["poor_or_flat_model_score_limits_permutation_importance"][0]["observed"], 0.698394)
        self.assertEqual(rows_by_id["no_positive_permutation_signal_with_uncertainty_margin"][0]["expected"], ">= 1 feature with mean - 2*std > 0")

    def test_serialized_spec_records_handoff_for_shap(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["built_in_importance_audit_id"], "trial-churn-built-in-importance-audit-v0")
        self.assertEqual(serialized["heldout_summary"]["baseline_log_loss"], 0.698394)
        self.assertEqual(serialized["top_summary"]["largest_absolute_mean_delta_feature"], "platform")
        self.assertEqual(serialized["top_summary"]["positive_with_two_std_margin_feature_count"], 0)
        self.assertEqual(serialized["warning_summary"]["high_cardinality_features"], ["acquisition_channel"])
        self.assertEqual(serialized["warning_summary"]["correlated_pair_count"], 5)
        self.assertEqual(serialized["upstream_handoff"]["built_in_readiness_status"], "ready_for_permutation_importance_lesson")

    def test_code_example_writes_all_permutation_outputs(self) -> None:
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["heldout_split"], "validation")
        self.assertEqual(payload["baseline_log_loss"], 0.698394)
        self.assertEqual(payload["repeat_count"], 7)
        self.assertEqual(payload["feature_count"], 10)
        self.assertEqual(payload["repeat_row_count"], 70)
        self.assertEqual(payload["largest_absolute_mean_delta_feature"], "platform")
        self.assertEqual(read_json(LESSON_ROOT / "outputs" / "permutation_importance_report.json")["summary"]["warning_ledger_row_count"], 9)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "permutation_importance.csv")), 10)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "permutation_importance_repeats.csv")), 70)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "permutation_warning_ledger.csv")), 9)
        self.assertEqual(
            read_json(LESSON_ROOT / "outputs" / "permutation_importance_serialized_spec.json")["top_summary"]["largest_absolute_mean_delta_feature"],
            "platform",
        )

    def test_invalid_built_in_report_blocks_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            built_in_report = read_json(reports / "built_in_importance_report.json")
            built_in_report["summary"]["readiness_status"] = "blocked_by_built_in_importance_policy"
            write_json(reports / "built_in_importance_report.json", built_in_report)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
                built_in_report_path=reports / "built_in_importance_report.json",
                built_in_spec_path=reports / "built_in_importance_serialized_spec.json",
            )

        self.assertFalse(report["valid"])
        handoff = check(report, "permutation_policy_matches_built_in_importance_handoff")
        self.assertFalse(handoff["valid"])
        self.assertIn("permutation_policy_matches_built_in_importance_handoff", report["summary"]["blocking_errors"])

    def test_test_split_as_heldout_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "permutation_importance_policy_spec.json")
            policy["heldout_split"] = "test"
            write_json(phase16 / "permutation_importance_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
                built_in_report_path=reports / "built_in_importance_report.json",
                built_in_spec_path=reports / "built_in_importance_serialized_spec.json",
            )

        self.assertFalse(report["valid"])
        policy_check = check(report, "permutation_policy_declares_validation_scoring_repeats_and_noncausal_scope")
        self.assertFalse(policy_check["valid"])
        self.assertIn("heldout_split", {error["field"] for error in policy_check["observed"]})

    def test_too_few_repeats_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "permutation_importance_policy_spec.json")
            policy["permutation"]["n_repeats"] = 1
            write_json(phase16 / "permutation_importance_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
                built_in_report_path=reports / "built_in_importance_report.json",
                built_in_spec_path=reports / "built_in_importance_serialized_spec.json",
            )

        self.assertFalse(report["valid"])
        policy_check = check(report, "permutation_policy_declares_validation_scoring_repeats_and_noncausal_scope")
        self.assertFalse(policy_check["valid"])
        self.assertEqual(policy_check["observed"][0]["field"], "permutation.n_repeats")

    def test_positive_causal_claim_blocks_policy(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            policy = read_json(phase16 / "permutation_importance_policy_spec.json")
            policy["interpretation_policy"]["claim"] = "platform causes churn and proves retention effect"
            write_json(phase16 / "permutation_importance_policy_spec.json", policy)

            report = self.audit(
                phase16,
                upstream,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
                built_in_report_path=reports / "built_in_importance_report.json",
                built_in_spec_path=reports / "built_in_importance_serialized_spec.json",
            )

        self.assertFalse(report["valid"])
        policy_check = check(report, "permutation_policy_declares_validation_scoring_repeats_and_noncausal_scope")
        self.assertFalse(policy_check["valid"])
        self.assertEqual(policy_check["observed"][0]["field"], "interpretation_policy.claim")
        self.assertEqual(policy_check["observed"][0]["forbidden_terms"], ["causes churn", "proves retention effect"])

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
            report_exists = (output_dir / "permutation_importance_report.json").exists()
            warning_exists = (output_dir / "permutation_warning_ledger.csv").exists()

        self.assertEqual(result.returncode, 2)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["warning_count"], 5)
        self.assertTrue(report_exists)
        self.assertTrue(warning_exists)

    def test_missing_policy_returns_structured_failure(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            missing_policy = phase16 / "missing_permutation_importance_policy_spec.json"

            report = self.audit(
                phase16,
                upstream,
                policy_path=missing_policy,
                early_stopping_report_path=reports / "early_stopping_report.json",
                early_stopping_spec_path=reports / "early_stopping_serialized_spec.json",
                categorical_report_path=reports / "categorical_feature_report.json",
                built_in_report_path=reports / "built_in_importance_report.json",
                built_in_spec_path=reports / "built_in_importance_serialized_spec.json",
            )

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["blocking_errors"], ["input_files_are_present"])
        self.assertEqual(report["checks"][0]["id"], "input_files_are_present")
