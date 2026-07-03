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
ARTIFACT = LESSON_ROOT / "outputs" / "linear_baseline_trainer.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from linear_baseline_trainer import run  # noqa: E402


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


class LinearBaselineTrainerTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, **outputs: Path) -> dict:
        return run(
            spec_path=root / "problem_spec.json",
            preprocessing_contract_path=root / "preprocessing_contract.json",
            pipeline_spec_path=root / "pipeline_spec.json",
            column_transformer_spec_path=root / "column_transformer_spec.json",
            linear_baseline_spec_path=root / "linear_baseline_spec.json",
            features_path=root / "ml_raw_features.csv",
            labels_path=root / "ml_labels.csv",
            manifest_path=root / "ml_split_manifest.csv",
            **outputs,
        )

    def copy_profile(self, directory: Path) -> Path:
        target = directory / "tiny"
        shutil.copytree(DATA_ROOT, target)
        return target

    def test_valid_linear_baseline_compares_dummy_and_logistic_on_validation(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["linear_baseline_id"], "trial-churn-linear-baseline-v0")
        self.assertEqual(report["summary"]["sklearn_version"], "1.9.0")
        self.assertEqual(report["summary"]["fit_split"], "train")
        self.assertEqual(report["summary"]["fit_row_count"], 4)
        self.assertEqual(report["summary"]["selection_split"], "validation")
        self.assertEqual(report["summary"]["final_holdout_split"], "test")
        self.assertEqual(report["summary"]["candidate_model_ids"], ["dummy_prior", "logistic_l2"])
        self.assertEqual(report["summary"]["selected_model_id"], "dummy_prior")
        self.assertEqual(report["summary"]["selection_budget"], 2)
        self.assertEqual(report["summary"]["transformed_feature_count"], 24)
        self.assertEqual(report["summary"]["coefficient_row_count"], 24)
        self.assertEqual(report["summary"]["prediction_row_count"], 16)
        self.assertEqual(report["summary"]["logistic_intercepts"], {"logistic_l2": [-0.055274]})
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "linear_baseline_unknown_categories_bucketed",
                "tiny_linear_baseline_training_sample_expected",
                "linear_baseline_does_not_beat_dummy_on_tiny_validation",
            ],
        )
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_tree_diagnostics_lesson")

    def test_validation_metrics_select_dummy_without_using_test_rows(self) -> None:
        report = self.audit()
        comparison = report["comparison"]
        by_key = {(row["model_id"], row["split"]): row for row in comparison}

        self.assertEqual(len(comparison), 4)
        self.assertEqual(by_key[("dummy_prior", "validation")]["precision_at_budget"], 0.5)
        self.assertEqual(by_key[("dummy_prior", "validation")]["log_loss"], 0.693147)
        self.assertEqual(by_key[("dummy_prior", "validation")]["selected_on_validation"], True)
        self.assertEqual(by_key[("dummy_prior", "validation")]["selection_rank"], 1)
        self.assertEqual(by_key[("logistic_l2", "validation")]["precision_at_budget"], 0.0)
        self.assertEqual(by_key[("logistic_l2", "validation")]["log_loss"], 1.153885)
        self.assertFalse(by_key[("dummy_prior", "test")]["selected_on_validation"])
        self.assertFalse(by_key[("logistic_l2", "test")]["selected_on_validation"])
        selection = check(report, "validation_selection_does_not_peek_at_test")
        self.assertTrue(selection["valid"])
        self.assertEqual(selection["observed"]["used_split"], "validation")

    def test_predictions_cover_validation_and_test_for_both_candidates(self) -> None:
        report = self.audit()
        rows = report["predictions"]

        self.assertEqual(len(rows), 16)
        self.assertEqual({row["split"] for row in rows}, {"validation", "test"})
        self.assertEqual({row["model_id"] for row in rows}, {"dummy_prior", "logistic_l2"})
        self.assertNotIn("train", {row["split"] for row in rows})
        self.assertEqual({row["trained_on_split"] for row in rows}, {"train"})
        logistic_scores = {
            row["snapshot_id"]: row["score"] for row in rows if row["model_id"] == "logistic_l2"
        }
        self.assertEqual(
            logistic_scores,
            {
                "S005": 0.506662,
                "S006": 0.294181,
                "S007": 0.783796,
                "S009": 0.628693,
                "S010": 0.409307,
                "S011": 0.169797,
                "S012": 0.56243,
                "S013": 0.38892,
            },
        )
        dummy_selected = [
            row["snapshot_id"]
            for row in rows
            if row["model_id"] == "dummy_prior"
            and row["split"] == "validation"
            and row["selected_at_budget"] == 1
        ]
        self.assertEqual(dummy_selected, ["S005", "S006"])

    def test_coefficient_table_joins_logistic_coefficients_to_feature_schema(self) -> None:
        report = self.audit()
        coefficients = report["coefficients"]

        self.assertEqual(len(coefficients), 24)
        self.assertEqual(coefficients[0]["feature_name"], "numeric_median__sessions_14d")
        self.assertEqual(coefficients[0]["coefficient"], 0.443988)
        self.assertEqual(coefficients[0]["coefficient_rank_by_abs"], 1)
        self.assertEqual(coefficients[1]["feature_name"], "categorical__platform_android")
        self.assertEqual(coefficients[1]["coefficient"], 0.424599)
        self.assertEqual(
            coefficients[2]["feature_name"], "categorical__acquisition_channel_paid_search"
        )
        self.assertEqual(coefficients[2]["coefficient"], -0.333739)
        self.assertEqual({row["model_intercept"] for row in coefficients}, {-0.055274})
        self.assertEqual(
            {row["interpretation_limit"] for row in coefficients},
            {"conditional_on_preprocessing_regularization_and_tiny_sample_not_causal"},
        )
        coeff_check = check(report, "coefficient_table_matches_feature_schema")
        self.assertTrue(coeff_check["valid"])
        self.assertEqual(coeff_check["observed"], {"rows": 24, "feature_count": 24})

    def test_serialized_spec_records_models_selection_and_fit_trace(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["linear_baseline_id"], "trial-churn-linear-baseline-v0")
        self.assertEqual(serialized["selection"]["selected_model_id"], "dummy_prior")
        self.assertFalse(serialized["selection"]["test_used_for_selection"])
        models = {row["model_id"]: row for row in serialized["candidate_models"]}
        self.assertEqual(models["dummy_prior"]["class"], "DummyClassifier")
        self.assertEqual(models["dummy_prior"]["class_prior"], [0.5, 0.5])
        self.assertEqual(models["logistic_l2"]["class"], "LogisticRegression")
        self.assertEqual(models["logistic_l2"]["coef_shape"], [1, 24])
        self.assertEqual(models["logistic_l2"]["regularization"]["family"], "l2")
        fit_events = [row for row in serialized["fit_trace"] if row["event"] == "pipeline.fit"]
        predict_events = [
            row for row in serialized["fit_trace"] if row["event"] == "pipeline.predict_proba"
        ]
        self.assertEqual(len(fit_events), 2)
        self.assertEqual(len(predict_events), 4)
        self.assertEqual(fit_events[0]["snapshot_ids"], ["S001", "S002", "S003", "S004"])
        self.assertTrue(all(not row["fits_anything"] for row in predict_events))

    def test_code_example_writes_report_comparison_coefficients_predictions_and_serialized_spec(
        self,
    ) -> None:
        report_path = LESSON_ROOT / "outputs" / "baseline_report.json"
        comparison_path = LESSON_ROOT / "outputs" / "baseline_comparison.csv"
        coefficients_path = LESSON_ROOT / "outputs" / "coefficient_table.csv"
        predictions_path = LESSON_ROOT / "outputs" / "baseline_predictions.csv"
        serialized_path = LESSON_ROOT / "outputs" / "linear_baseline_serialized_spec.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["linear_baseline_id"], "trial-churn-linear-baseline-v0")
        self.assertEqual(payload["selected_model_id"], "dummy_prior")
        self.assertEqual(payload["coefficient_row_count"], 24)
        self.assertEqual(payload["prediction_row_count"], 16)
        self.assertEqual(payload["validation_precision_at_budget"]["dummy_prior"], 0.5)
        self.assertEqual(payload["validation_log_loss"]["logistic_l2"], 1.153885)
        self.assertEqual(read_json(report_path)["summary"]["selected_model_id"], "dummy_prior")
        self.assertEqual(len(read_csv(comparison_path)), 4)
        self.assertEqual(len(read_csv(coefficients_path)), 24)
        self.assertEqual(len(read_csv(predictions_path)), 16)
        self.assertEqual(
            read_json(serialized_path)["selection"]["primary_metric"], "precision_at_budget"
        )

    def test_data_generator_check_rebuilds_committed_linear_baseline_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)
        self.assertTrue((DATA_ROOT / "linear_baseline_spec.json").exists())

    def test_missing_dummy_candidate_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "linear_baseline_spec.json")
            spec["candidates"] = [
                candidate
                for candidate in spec["candidates"]
                if candidate["kind"] != "dummy_classifier"
            ]
            write_json(root / "linear_baseline_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "linear_baseline_spec_declares_dummy_and_logistic")
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["sample"][0]["field"], "candidates")

    def test_selection_data_must_be_validation_not_test(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "linear_baseline_spec.json")
            spec["comparison"]["selection_data"] = "test"
            write_json(root / "linear_baseline_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "linear_baseline_spec_declares_dummy_and_logistic")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "comparison.selection_data")

    def test_logistic_regularization_must_be_declared(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "linear_baseline_spec.json")
            spec["candidates"][1]["regularization"]["family"] = "none"
            write_json(root / "linear_baseline_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "linear_baseline_spec_declares_dummy_and_logistic")
        self.assertFalse(report["valid"])
        self.assertIn("regularization.family", contract["sample"][0]["field"])

    def test_interpretation_limits_are_required_for_coefficients(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "linear_baseline_spec.json")
            spec["coefficient_policy"]["interpretation_limits"] = []
            write_json(root / "linear_baseline_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "linear_baseline_spec_declares_dummy_and_logistic")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "coefficient_policy.interpretation_limits")

    def test_upstream_column_transformer_must_be_valid_before_linear_fit(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "column_transformer_spec.json")
            spec["remainder"] = "passthrough"
            write_json(root / "column_transformer_spec.json", spec)

            report = self.audit(root)

        upstream = check(report, "upstream_column_transformer_audit_is_valid")
        self.assertFalse(report["valid"])
        self.assertFalse(upstream["valid"])
        self.assertIn(
            "upstream_column_transformer_audit_is_valid",
            report["summary"]["blocking_errors"],
        )

    def test_manifest_roles_must_preserve_train_validation_test_meaning(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_split_manifest.csv")
            rows[0]["role"] = "model_selection_and_threshold_selection"
            write_csv(root / "ml_split_manifest.csv", rows)

            report = self.audit(root)

        manifest = check(report, "split_manifest_supports_linear_baseline_roles")
        self.assertFalse(report["valid"])
        self.assertFalse(manifest["valid"])
        self.assertEqual(manifest["sample"][0]["field"], "role")

    def test_train_split_must_contain_both_classes_before_linear_fit(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_labels.csv")
            for row in rows:
                if row["snapshot_id"] in {"S001", "S002", "S003", "S004"}:
                    row["churned_14d"] = "false"
            write_csv(root / "ml_labels.csv", rows)

            report = self.audit(root)

        upstream = check(report, "upstream_column_transformer_audit_is_valid")
        self.assertFalse(report["valid"])
        self.assertFalse(upstream["valid"])
        self.assertIn(
            "upstream_column_transformer_audit_is_valid", report["summary"]["blocking_errors"]
        )

    def test_unknown_categories_and_dummy_gap_are_warnings_not_blocking_errors(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        unknowns = check(report, "linear_baseline_unknown_categories_bucketed")
        dummy_gap = check(report, "linear_baseline_does_not_beat_dummy_on_tiny_validation")
        self.assertEqual(unknowns["severity"], "warning")
        self.assertFalse(unknowns["valid"])
        self.assertEqual(unknowns["observed"], 2)
        self.assertEqual(dummy_gap["severity"], "warning")
        self.assertFalse(dummy_gap["valid"])
        self.assertEqual(dummy_gap["observed"]["dummy_prior_precision_at_budget"], 0.5)
        self.assertEqual(dummy_gap["observed"]["best_logistic_precision_at_budget"], 0.0)

    def test_cli_writes_report_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "linear_baseline_spec.json")
            spec["fit_split"] = "validation"
            write_json(root / "linear_baseline_spec.json", spec)
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
            "linear_baseline_spec_declares_dummy_and_logistic",
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
        self.assertIn("linear_baseline_does_not_beat_dummy_on_tiny_validation", result.stdout)
