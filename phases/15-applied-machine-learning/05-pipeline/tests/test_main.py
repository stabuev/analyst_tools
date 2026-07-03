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
ARTIFACT = LESSON_ROOT / "outputs" / "pipeline_runner.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from pipeline_runner import run  # noqa: E402


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


class PipelineRunnerTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, **outputs: Path) -> dict:
        return run(
            spec_path=root / "problem_spec.json",
            preprocessing_contract_path=root / "preprocessing_contract.json",
            pipeline_spec_path=root / "pipeline_spec.json",
            features_path=root / "ml_raw_features.csv",
            labels_path=root / "ml_labels.csv",
            manifest_path=root / "ml_split_manifest.csv",
            **outputs,
        )

    def copy_profile(self, directory: Path) -> Path:
        target = directory / "tiny"
        shutil.copytree(DATA_ROOT, target)
        return target

    def test_valid_pipeline_fits_train_and_scores_validation_test(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["pipeline_id"], "trial-churn-sklearn-pipeline-v0")
        self.assertEqual(report["summary"]["sklearn_version"], "1.9.0")
        self.assertEqual(report["summary"]["fit_split"], "train")
        self.assertEqual(report["summary"]["fit_row_count"], 4)
        self.assertEqual(report["summary"]["predict_splits"], ["validation", "test"])
        self.assertEqual(report["summary"]["prediction_row_count"], 8)
        self.assertEqual(report["summary"]["transformed_feature_count"], 23)
        self.assertEqual(report["summary"]["estimator"], "LogisticRegression")
        self.assertEqual(report["summary"]["blocking_errors"], [])
        self.assertEqual(
            report["summary"]["warnings"],
            ["pipeline_unknown_categories_bucketed", "tiny_pipeline_training_sample_expected"],
        )
        self.assertEqual(
            report["summary"]["readiness_status"], "ready_for_column_transformer_lesson"
        )

    def test_serialized_spec_records_single_pipeline_order_and_fit_trace(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(
            [step["name"] for step in serialized["steps"]], ["preprocess", "estimator"]
        )
        self.assertEqual(serialized["steps"][0]["class"], "ContractPreprocessor")
        self.assertEqual(serialized["steps"][1]["class"], "LogisticRegression")
        self.assertEqual(serialized["steps"][1]["params"]["solver"], "liblinear")
        self.assertEqual(serialized["steps"][1]["params"]["random_state"], 0)
        self.assertEqual(serialized["steps"][1]["coef_shape"], [1, 23])
        self.assertEqual(len(serialized["feature_names"]), 23)
        self.assertIn("cat__acquisition_channel=__unknown__", serialized["feature_names"])

        fit, validation, test = serialized["fit_trace"]
        self.assertEqual(fit["event"], "pipeline.fit")
        self.assertEqual(fit["snapshot_ids"], ["S001", "S002", "S003", "S004"])
        self.assertTrue(fit["fits_preprocessing"])
        self.assertTrue(fit["fits_estimator"])
        self.assertEqual(validation["event"], "pipeline.predict_proba")
        self.assertEqual(validation["snapshot_ids"], ["S005", "S006", "S007"])
        self.assertFalse(validation["fits_anything"])
        self.assertEqual(test["snapshot_ids"], ["S009", "S010", "S011", "S012", "S013"])
        self.assertFalse(test["fits_anything"])

    def test_prediction_rows_have_probabilities_for_validation_and_test_only(self) -> None:
        report = self.audit()
        rows = report["predictions"]

        self.assertEqual(len(rows), 8)
        self.assertEqual({row["split"] for row in rows}, {"validation", "test"})
        self.assertNotIn("train", {row["split"] for row in rows})
        self.assertTrue(all(0 <= row["score"] <= 1 for row in rows))
        self.assertEqual({row["trained_on_split"] for row in rows}, {"train"})
        self.assertEqual(
            {row["snapshot_id"]: row["score"] for row in rows},
            {
                "S005": 0.501623,
                "S006": 0.302765,
                "S007": 0.781539,
                "S009": 0.620732,
                "S010": 0.414951,
                "S011": 0.18009,
                "S012": 0.555921,
                "S013": 0.392083,
            },
        )
        self.assertEqual(
            report["summary"]["score_summary_by_split"]["validation"],
            {"row_count": 3, "min": 0.302765, "max": 0.781539, "mean": 0.528642},
        )
        self.assertEqual(
            report["summary"]["score_summary_by_split"]["test"],
            {"row_count": 5, "min": 0.18009, "max": 0.620732, "mean": 0.432755},
        )

    def test_preprocessing_state_is_embedded_and_fit_on_train_only(self) -> None:
        report = self.audit()
        state = report["preprocessing_state"]

        self.assertEqual(state["fit_row_count"], 4)
        self.assertEqual(state["numeric_features"]["sessions_14d"]["fill_value"], 4.0)
        self.assertEqual(state["numeric_features"]["sessions_14d"]["mean"], 4.5)
        self.assertEqual(state["numeric_features"]["sessions_14d"]["scale"], 2.179449)
        self.assertEqual(state["numeric_features"]["days_since_signup"]["mean"], 7.0)
        self.assertEqual(
            state["categorical_features"]["acquisition_channel"]["observed_train_categories"],
            ["organic", "paid_search", "referral"],
        )
        self.assertEqual(
            state["categorical_features"]["acquisition_channel"]["encoded_categories"],
            ["organic", "paid_search", "referral", "__missing__", "__unknown__"],
        )

    def test_unknown_validation_and_test_categories_are_audited(self) -> None:
        report = self.audit()
        unknown = report["summary"]["unknown_category_events"]

        self.assertEqual(len(unknown), 2)
        self.assertEqual({item["value"] for item in unknown}, {"influencer", "partnership"})
        warning = check(report, "pipeline_unknown_categories_bucketed")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])
        self.assertEqual(warning["observed"], 2)

    def test_code_example_writes_report_predictions_and_serialized_spec(self) -> None:
        report_path = LESSON_ROOT / "outputs" / "pipeline_report.json"
        predictions_path = LESSON_ROOT / "outputs" / "pipeline_predictions.csv"
        serialized_path = LESSON_ROOT / "outputs" / "pipeline_serialized_spec.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["pipeline_id"], "trial-churn-sklearn-pipeline-v0")
        self.assertEqual(payload["fit_split"], "train")
        self.assertEqual(payload["prediction_row_count"], 8)
        self.assertEqual(payload["transformed_feature_count"], 23)
        self.assertEqual(payload["validation_score_mean"], 0.528642)
        self.assertEqual(payload["test_score_mean"], 0.432755)
        self.assertEqual(
            read_json(report_path)["summary"]["readiness_status"],
            "ready_for_column_transformer_lesson",
        )
        self.assertEqual(len(read_csv(predictions_path)), 8)
        self.assertEqual(read_json(serialized_path)["steps"][1]["class"], "LogisticRegression")

    def test_data_generator_check_rebuilds_committed_pipeline_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)

    def test_pipeline_fit_split_cannot_be_validation(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "pipeline_spec.json")
            spec["fit_split"] = "validation"
            write_json(root / "pipeline_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "pipeline_spec_declares_single_safe_pipeline")
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["sample"][0]["field"], "fit_split")
        self.assertEqual(report["summary"]["readiness_status"], "blocked_before_pipeline_fit")

    def test_external_preprocessed_matrix_input_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "pipeline_spec.json")
            spec["preprocessing_location"] = "external_preprocessed_matrix"
            write_json(root / "pipeline_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "pipeline_spec_declares_single_safe_pipeline")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "preprocessing_location")

    def test_prediction_splits_must_be_validation_and_test_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "pipeline_spec.json")
            spec["predict_splits"] = ["train", "validation"]
            write_json(root / "pipeline_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "pipeline_spec_declares_single_safe_pipeline")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "predict_splits")

    def test_pipeline_step_order_is_part_of_the_contract(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "pipeline_spec.json")
            spec["steps"] = list(reversed(spec["steps"]))
            write_json(root / "pipeline_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "pipeline_spec_declares_single_safe_pipeline")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "steps")

    def test_estimator_must_be_declared_as_logistic_regression(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "pipeline_spec.json")
            spec["steps"][1]["kind"] = "decision_tree"
            write_json(root / "pipeline_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "pipeline_spec_declares_single_safe_pipeline")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "steps.estimator.kind")

    def test_estimator_requires_fixed_random_state(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "pipeline_spec.json")
            del spec["steps"][1]["params"]["random_state"]
            write_json(root / "pipeline_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "pipeline_spec_declares_single_safe_pipeline")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "steps.estimator.params.random_state")

    def test_missing_feature_row_blocks_fit_before_pipeline_is_built(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = [
                row
                for row in read_csv(root / "ml_raw_features.csv")
                if row["snapshot_id"] != "S006"
            ]
            write_csv(root / "ml_raw_features.csv", rows)

            report = self.audit(root)

        population = check(report, "raw_features_cover_pipeline_population")
        self.assertFalse(report["valid"])
        self.assertFalse(population["valid"])
        self.assertEqual(population["sample"][0]["reason"], "manifest rows missing features")
        self.assertIn("S006", population["sample"][0]["sample"])

    def test_duplicate_feature_row_blocks_pipeline(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_raw_features.csv")
            rows.append(dict(rows[0]))
            write_csv(root / "ml_raw_features.csv", rows)

            report = self.audit(root)

        population = check(report, "raw_features_cover_pipeline_population")
        self.assertFalse(report["valid"])
        self.assertEqual(population["sample"][0]["reason"], "duplicate feature rows")

    def test_forbidden_target_column_in_raw_features_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_raw_features.csv")
            for row in rows:
                row["churned_14d"] = "false"
            write_csv(root / "ml_raw_features.csv", rows)

            report = self.audit(root)

        population = check(report, "raw_features_cover_pipeline_population")
        self.assertFalse(report["valid"])
        self.assertEqual(population["sample"][0]["reason"], "forbidden columns present")
        self.assertIn("churned_14d", population["sample"][0]["sample"])

    def test_labels_must_be_complete_for_audited_splits(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_labels.csv")
            rows[0]["label_window_complete"] = "false"
            write_csv(root / "ml_labels.csv", rows)

            report = self.audit(root)

        labels = check(report, "labels_support_pipeline_training_and_prediction_audit")
        self.assertFalse(report["valid"])
        self.assertEqual(labels["sample"][0]["reason"], "label window is incomplete")

    def test_train_split_must_contain_both_classes_for_logistic_regression(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_labels.csv")
            for row in rows:
                if row["snapshot_id"] in {"S001", "S002", "S003", "S004"}:
                    row["churned_14d"] = "false"
            write_csv(root / "ml_labels.csv", rows)

            report = self.audit(root)

        train_classes = check(report, "train_split_has_both_classes_for_estimator")
        self.assertFalse(report["valid"])
        self.assertFalse(train_classes["valid"])
        self.assertEqual(train_classes["observed"], [0])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_pipeline(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "pipeline_spec.json")
            spec["fit_split"] = "test"
            write_json(root / "pipeline_spec.json", spec)
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
            "pipeline_spec_declares_single_safe_pipeline", payload["summary"]["blocking_errors"]
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
        self.assertIn("pipeline_unknown_categories_bucketed", result.stdout)
