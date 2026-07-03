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
ARTIFACT = LESSON_ROOT / "outputs" / "tree_ensemble_comparator.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from tree_ensemble_comparator import run  # noqa: E402


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


class TreeEnsembleComparatorTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, **outputs: Path) -> dict:
        return run(
            spec_path=root / "problem_spec.json",
            preprocessing_contract_path=root / "preprocessing_contract.json",
            pipeline_spec_path=root / "pipeline_spec.json",
            column_transformer_spec_path=root / "column_transformer_spec.json",
            linear_baseline_spec_path=root / "linear_baseline_spec.json",
            tree_diagnostic_spec_path=root / "tree_diagnostic_spec.json",
            tree_ensemble_spec_path=root / "tree_ensemble_spec.json",
            features_path=root / "ml_raw_features.csv",
            labels_path=root / "ml_labels.csv",
            manifest_path=root / "ml_split_manifest.csv",
            **outputs,
        )

    def copy_profile(self, directory: Path) -> Path:
        target = directory / "tiny"
        shutil.copytree(DATA_ROOT, target)
        return target

    def test_valid_tree_ensemble_exports_comparison_package(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["tree_ensemble_id"], "trial-churn-tree-ensemble-v0")
        self.assertEqual(report["summary"]["sklearn_version"], "1.9.0")
        self.assertEqual(report["summary"]["fit_split"], "train")
        self.assertEqual(report["summary"]["fit_row_count"], 4)
        self.assertEqual(report["summary"]["model_id"], "random_forest_depth2")
        self.assertEqual(report["summary"]["n_estimators"], 25)
        self.assertEqual(report["summary"]["max_depth_limit"], 2)
        self.assertEqual(report["summary"]["transformed_feature_count"], 24)
        self.assertEqual(report["summary"]["prediction_row_count"], 12)
        self.assertEqual(report["summary"]["selected_model_id"], "dummy_prior")
        self.assertEqual(report["summary"]["selected_model_source"], "15/07-linear-baseline")
        self.assertFalse(report["summary"]["test_used_for_selection"])
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_cross_validation_lesson")

    def test_comparison_keeps_ensemble_below_dummy_on_validation(self) -> None:
        report = self.audit()
        validation = {
            row["model_id"]: row for row in report["comparison"] if row["split"] == "validation"
        }

        self.assertEqual(validation["dummy_prior"]["precision_at_budget"], 0.5)
        self.assertEqual(validation["dummy_prior"]["selection_rank"], 1)
        self.assertTrue(validation["dummy_prior"]["selected_on_validation"])
        self.assertEqual(validation["random_forest_depth2"]["precision_at_budget"], 0.0)
        self.assertEqual(validation["random_forest_depth2"]["log_loss"], 1.004659)
        self.assertEqual(validation["random_forest_depth2"]["selection_rank"], 2)
        self.assertEqual(validation["decision_tree_depth2"]["selection_rank"], 4)
        self.assertEqual(
            report["summary"]["selected_ids_on_validation"],
            ["S005", "S007"],
        )

    def test_stability_report_tracks_seed_variation(self) -> None:
        report = self.audit()
        rows = {row["seed"]: row for row in report["stability"]}

        self.assertEqual(set(rows), {0, 7, 13})
        self.assertEqual(rows[0]["selected_ids"], "S005,S007")
        self.assertEqual(rows[7]["selected_ids"], "S006,S007")
        self.assertEqual(rows[13]["selected_ids"], "S005,S007")
        self.assertEqual(rows[7]["precision_at_budget"], 0.5)
        self.assertEqual(report["summary"]["stability_range"], 0.5)
        stability = check(report, "ensemble_seed_stability_reported")
        self.assertTrue(stability["valid"])
        self.assertEqual(stability["observed"]["selected_id_sets"], ["S005,S007", "S006,S007"])

    def test_feature_importance_includes_mdi_permutation_and_warnings(self) -> None:
        report = self.audit()
        rows = report["feature_importance"]
        top = {(row["method"], row["rank"]): row for row in rows}

        self.assertEqual(len(rows), 16)
        self.assertEqual(top[("mdi", 1)]["feature_name"], "categorical__plan_id_trial_pro")
        self.assertEqual(top[("mdi", 1)]["importance_mean"], 0.138889)
        self.assertEqual(top[("permutation", 1)]["feature_name"], "binary__had_support_ticket_14d")
        self.assertEqual(top[("permutation", 1)]["computed_on_split"], "validation")
        self.assertEqual(top[("permutation", 1)]["importance_mean"], 0.0)
        caution = check(report, "ensemble_feature_importance_requires_caution")
        self.assertEqual(caution["severity"], "warning")
        self.assertFalse(caution["valid"])
        self.assertIn("mdi_can_favor_high_cardinality_features", caution["observed"])

    def test_slice_metrics_flag_small_validation_segments(self) -> None:
        report = self.audit()
        rows = {(row["slice_column"], row["slice_value"]): row for row in report["slice_metrics"]}

        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[("platform", "web")]["precision_at_budget"], 1.0)
        self.assertEqual(rows[("country", "RU")]["row_count"], 2)
        self.assertEqual(rows[("country", "RU")]["precision_at_budget"], 0.5)
        self.assertTrue(all(row["small_n_warning"] for row in rows.values()))
        small_n = check(report, "ensemble_slice_metrics_have_small_n")
        self.assertEqual(small_n["severity"], "warning")
        self.assertFalse(small_n["valid"])
        self.assertEqual(report["summary"]["small_n_slice_count"], 5)

    def test_predictions_cover_all_splits_with_seeded_scores(self) -> None:
        report = self.audit()
        rows = report["predictions"]
        scores = {row["snapshot_id"]: row["score"] for row in rows}

        self.assertEqual(len(rows), 12)
        self.assertEqual({row["split"] for row in rows}, {"train", "validation", "test"})
        self.assertEqual({row["model_id"] for row in rows}, {"random_forest_depth2"})
        self.assertEqual({row["trained_on_split"] for row in rows}, {"train"})
        self.assertEqual(
            scores,
            {
                "S001": 0.82,
                "S002": 0.28,
                "S003": 0.3,
                "S004": 0.84,
                "S005": 0.62,
                "S006": 0.38,
                "S007": 0.66,
                "S009": 0.7,
                "S010": 0.58,
                "S011": 0.26,
                "S012": 0.84,
                "S013": 0.24,
            },
        )
        self.assertEqual({row["generated_at"] for row in rows}, {"2026-07-02T13:00:00+03:00"})

    def test_serialized_spec_records_handoff_selection_and_stability(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["tree_ensemble_id"], "trial-churn-tree-ensemble-v0")
        self.assertEqual(serialized["model"]["class"], "RandomForestClassifier")
        self.assertEqual(serialized["model"]["n_estimators"], 25)
        self.assertEqual(serialized["model"]["feature_count"], 24)
        self.assertEqual(serialized["selection"]["selected_model_id"], "dummy_prior")
        self.assertFalse(serialized["selection"]["test_used_for_selection"])
        self.assertEqual(
            serialized["selection"]["ensemble_selected_ids_on_validation"],
            ["S005", "S007"],
        )
        self.assertEqual(serialized["stability"]["seeds"], [0, 7, 13])
        self.assertEqual(serialized["stability"]["range"], 0.5)
        fit, validation, test = serialized["fit_trace"]
        self.assertEqual(fit["event"], "pipeline.fit")
        self.assertEqual(fit["snapshot_ids"], ["S001", "S002", "S003", "S004"])
        self.assertFalse(validation["fits_anything"])
        self.assertFalse(test["fits_anything"])

    def test_code_example_writes_report_comparison_stability_importance_slices_predictions(
        self,
    ) -> None:
        report_path = LESSON_ROOT / "outputs" / "ensemble_report.json"
        comparison_path = LESSON_ROOT / "outputs" / "ensemble_comparison.csv"
        stability_path = LESSON_ROOT / "outputs" / "ensemble_stability_report.csv"
        importance_path = LESSON_ROOT / "outputs" / "ensemble_feature_importance.csv"
        slice_path = LESSON_ROOT / "outputs" / "ensemble_slice_metrics.csv"
        predictions_path = LESSON_ROOT / "outputs" / "ensemble_predictions.csv"
        serialized_path = LESSON_ROOT / "outputs" / "ensemble_serialized_spec.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["tree_ensemble_id"], "trial-churn-tree-ensemble-v0")
        self.assertEqual(payload["model_id"], "random_forest_depth2")
        self.assertEqual(payload["selected_model_id"], "dummy_prior")
        self.assertEqual(payload["stability_range"], 0.5)
        self.assertEqual(payload["top_mdi_feature"], "categorical__plan_id_trial_pro")
        self.assertEqual(read_json(report_path)["summary"]["n_estimators"], 25)
        self.assertEqual(len(read_csv(comparison_path)), 10)
        self.assertEqual(len(read_csv(stability_path)), 3)
        self.assertEqual(len(read_csv(importance_path)), 16)
        self.assertEqual(len(read_csv(slice_path)), 5)
        self.assertEqual(len(read_csv(predictions_path)), 12)
        self.assertEqual(read_json(serialized_path)["model"]["class"], "RandomForestClassifier")

    def test_data_generator_check_rebuilds_committed_tree_ensemble_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)
        self.assertTrue((DATA_ROOT / "tree_ensemble_spec.json").exists())

    def test_missing_random_state_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_ensemble_spec.json")
            spec["candidate"]["params"]["random_state"] = None
            write_json(root / "tree_ensemble_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "tree_ensemble_spec_declares_reproducible_comparison")
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["sample"][0]["field"], "candidate.params.random_state")

    def test_selection_data_must_stay_validation_not_test(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_ensemble_spec.json")
            spec["comparison"]["selection_data"] = "test"
            write_json(root / "tree_ensemble_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "tree_ensemble_spec_declares_reproducible_comparison")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "comparison.selection_data")

    def test_stability_policy_requires_multiple_integer_seeds(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_ensemble_spec.json")
            spec["stability_policy"]["seeds"] = [0]
            write_json(root / "tree_ensemble_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "tree_ensemble_spec_declares_reproducible_comparison")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "stability_policy.seeds")

    def test_feature_importance_policy_requires_mdi_and_permutation(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_ensemble_spec.json")
            spec["feature_importance_policy"]["methods"] = ["mdi"]
            write_json(root / "tree_ensemble_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "tree_ensemble_spec_declares_reproducible_comparison")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "feature_importance_policy.methods")

    def test_manifest_roles_must_preserve_split_meaning(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_split_manifest.csv")
            rows[0]["role"] = "final_once_only_evaluation"
            write_csv(root / "ml_split_manifest.csv", rows)

            report = self.audit(root)

        manifest = check(report, "split_manifest_supports_tree_ensemble_roles")
        self.assertFalse(report["valid"])
        self.assertFalse(manifest["valid"])
        self.assertEqual(manifest["sample"][0]["field"], "role")

    def test_upstream_tree_diagnostic_must_be_valid_before_ensemble_fit(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_diagnostic_spec.json")
            spec["candidate"]["params"]["max_depth"] = None
            write_json(root / "tree_diagnostic_spec.json", spec)

            report = self.audit(root)

        upstream = check(report, "upstream_tree_diagnostic_audit_is_valid")
        self.assertFalse(report["valid"])
        self.assertFalse(upstream["valid"])
        self.assertIn(
            "upstream_tree_diagnostic_audit_is_valid",
            report["summary"]["blocking_errors"],
        )

    def test_stability_range_threshold_can_emit_warning(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_ensemble_spec.json")
            spec["stability_policy"]["max_allowed_range"] = 0.25
            write_json(root / "tree_ensemble_spec.json", spec)

            report = self.audit(root)

        warning = check(report, "ensemble_seed_stability_range_exceeds_threshold")
        self.assertTrue(report["valid"])
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])
        self.assertEqual(warning["observed"]["range"], 0.5)

    def test_cli_writes_report_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_ensemble_spec.json")
            spec["candidate"]["kind"] = "decision_tree_classifier"
            write_json(root / "tree_ensemble_spec.json", spec)
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
                    "--features",
                    root / "ml_raw_features.csv",
                    "--labels",
                    root / "ml_labels.csv",
                    "--manifest",
                    root / "ml_split_manifest.csv",
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
            "tree_ensemble_spec_declares_reproducible_comparison",
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
                "--features",
                DATA_ROOT / "ml_raw_features.csv",
                "--labels",
                DATA_ROOT / "ml_labels.csv",
                "--manifest",
                DATA_ROOT / "ml_split_manifest.csv",
                "--fail-on-warning",
            ],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ensemble_feature_importance_requires_caution", result.stdout)
