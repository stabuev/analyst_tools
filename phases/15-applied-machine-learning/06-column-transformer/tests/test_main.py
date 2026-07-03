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
ARTIFACT = LESSON_ROOT / "outputs" / "column_transformer_auditor.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from column_transformer_auditor import run  # noqa: E402


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


class ColumnTransformerAuditorTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, **outputs: Path) -> dict:
        return run(
            spec_path=root / "problem_spec.json",
            preprocessing_contract_path=root / "preprocessing_contract.json",
            pipeline_spec_path=root / "pipeline_spec.json",
            column_transformer_spec_path=root / "column_transformer_spec.json",
            features_path=root / "ml_raw_features.csv",
            labels_path=root / "ml_labels.csv",
            manifest_path=root / "ml_split_manifest.csv",
            **outputs,
        )

    def copy_profile(self, directory: Path) -> Path:
        target = directory / "tiny"
        shutil.copytree(DATA_ROOT, target)
        return target

    def test_valid_column_transformer_routes_and_scores_validation_test(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(
            report["summary"]["column_transformer_id"], "trial-churn-column-transformer-v0"
        )
        self.assertEqual(report["summary"]["sklearn_version"], "1.9.0")
        self.assertEqual(report["summary"]["fit_split"], "train")
        self.assertEqual(report["summary"]["fit_row_count"], 4)
        self.assertEqual(report["summary"]["predict_splits"], ["validation", "test"])
        self.assertEqual(report["summary"]["routed_input_feature_count"], 10)
        self.assertEqual(report["summary"]["transformed_feature_count"], 24)
        self.assertEqual(report["summary"]["prediction_row_count"], 8)
        self.assertEqual(
            report["summary"]["route_names"],
            ["numeric_median", "numeric_constant", "categorical", "binary"],
        )
        self.assertEqual(report["summary"]["dropped_columns"], ["snapshot_id"])
        self.assertEqual(report["summary"]["unapproved_dropped_columns"], [])
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "column_transformer_unknown_categories_bucketed",
                "tiny_column_transformer_training_sample_expected",
            ],
        )
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_linear_baseline_lesson")

    def test_routing_table_declares_numeric_categorical_binary_and_dropped_key(self) -> None:
        report = self.audit()
        routing = report["routing"]

        self.assertEqual(len(routing), 11)
        self.assertEqual(routing[0]["column"], "snapshot_id")
        self.assertEqual(routing[0]["action"], "drop")
        self.assertEqual(routing[0]["reason"], "identifier_not_model_feature")
        self.assertEqual(
            {(row["route"], row["kind"]) for row in routing if row["action"] == "transform"},
            {
                ("numeric_median", "numeric"),
                ("numeric_constant", "numeric"),
                ("categorical", "categorical"),
                ("binary", "binary"),
            },
        )
        acquisition = next(row for row in routing if row["column"] == "acquisition_channel")
        self.assertEqual(acquisition["transformer"], "UnknownCategoryBucketer|OneHotEncoder")
        self.assertEqual(acquisition["output_feature_count"], 5)

    def test_feature_schema_has_prefixed_names_and_unknown_bucket_columns(self) -> None:
        report = self.audit()
        schema = report["feature_schema"]
        names = [row["feature_name"] for row in schema]

        self.assertEqual(len(schema), 24)
        self.assertEqual(names[0], "numeric_median__sessions_14d")
        self.assertIn("categorical__acquisition_channel___unknown__", names)
        self.assertIn("categorical__platform___missing__", names)
        self.assertEqual(names[-1], "binary__had_support_ticket_14d")
        unknown_row = next(row for row in schema if row["source_category"] == "__unknown__")
        self.assertEqual(unknown_row["source_route"], "categorical")

    def test_serialized_spec_records_column_transformer_state_and_fit_trace(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(
            serialized["pipeline_steps"],
            [
                {"name": "preprocess", "class": "ColumnTransformer"},
                {"name": "estimator", "class": "LogisticRegression"},
            ],
        )
        self.assertEqual(serialized["column_transformer"]["remainder"], "drop")
        self.assertEqual(serialized["column_transformer"]["sparse_threshold"], 0.0)
        self.assertEqual(
            [route["name"] for route in serialized["column_transformer"]["routes"]],
            ["numeric_median", "numeric_constant", "categorical", "binary"],
        )
        self.assertEqual(
            serialized["route_state"]["numeric_median"]["imputer_statistics"], [4.0, 2.5, 7.0]
        )
        self.assertEqual(
            serialized["route_state"]["categorical"]["unknown_bucket_state"][
                "observed_train_categories"
            ]["acquisition_channel"],
            ["organic", "paid_search", "referral"],
        )
        self.assertEqual(serialized["estimator"]["coef_shape"], [1, 24])
        fit, validation, test = serialized["fit_trace"]
        self.assertEqual(fit["event"], "pipeline.fit")
        self.assertTrue(fit["fits_column_transformer"])
        self.assertEqual(fit["snapshot_ids"], ["S001", "S002", "S003", "S004"])
        self.assertFalse(validation["fits_anything"])
        self.assertFalse(test["fits_anything"])

    def test_prediction_rows_are_probabilities_for_validation_and_test_only(self) -> None:
        report = self.audit()
        rows = report["predictions"]

        self.assertEqual(len(rows), 8)
        self.assertEqual({row["split"] for row in rows}, {"validation", "test"})
        self.assertNotIn("train", {row["split"] for row in rows})
        self.assertEqual({row["trained_on_split"] for row in rows}, {"train"})
        self.assertTrue(all(0 <= row["score"] <= 1 for row in rows))
        self.assertEqual(
            {row["snapshot_id"]: row["score"] for row in rows},
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
        self.assertEqual(
            report["summary"]["score_summary_by_split"]["validation"],
            {"row_count": 3, "min": 0.294181, "max": 0.783796, "mean": 0.528213},
        )
        self.assertEqual(
            report["summary"]["score_summary_by_split"]["test"],
            {"row_count": 5, "min": 0.169797, "max": 0.628693, "mean": 0.431829},
        )

    def test_unknown_validation_and_test_categories_are_bucketed_before_one_hot_encoder(
        self,
    ) -> None:
        report = self.audit()
        unknown = report["summary"]["unknown_category_events"]

        self.assertEqual(len(unknown), 2)
        self.assertEqual({item["value"] for item in unknown}, {"influencer", "partnership"})
        warning = check(report, "column_transformer_unknown_categories_bucketed")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])
        self.assertEqual(warning["observed"], 2)

    def test_code_example_writes_report_routing_schema_predictions_and_serialized_spec(
        self,
    ) -> None:
        report_path = LESSON_ROOT / "outputs" / "column_transformer_report.json"
        routing_path = LESSON_ROOT / "outputs" / "column_transformer_routing.csv"
        schema_path = LESSON_ROOT / "outputs" / "column_transformer_feature_schema.csv"
        predictions_path = LESSON_ROOT / "outputs" / "column_transformer_predictions.csv"
        serialized_path = LESSON_ROOT / "outputs" / "column_transformer_serialized_spec.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["column_transformer_id"], "trial-churn-column-transformer-v0")
        self.assertEqual(payload["routed_input_feature_count"], 10)
        self.assertEqual(payload["transformed_feature_count"], 24)
        self.assertEqual(payload["prediction_row_count"], 8)
        self.assertEqual(payload["validation_score_mean"], 0.528213)
        self.assertEqual(payload["test_score_mean"], 0.431829)
        self.assertEqual(
            read_json(report_path)["summary"]["readiness_status"],
            "ready_for_linear_baseline_lesson",
        )
        self.assertEqual(len(read_csv(routing_path)), 11)
        self.assertEqual(len(read_csv(schema_path)), 24)
        self.assertEqual(len(read_csv(predictions_path)), 8)
        self.assertEqual(
            read_json(serialized_path)["pipeline_steps"][0]["class"], "ColumnTransformer"
        )

    def test_data_generator_check_rebuilds_committed_column_transformer_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)

    def test_remainder_passthrough_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "column_transformer_spec.json")
            spec["remainder"] = "passthrough"
            write_json(root / "column_transformer_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "column_transformer_spec_declares_explicit_routes")
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["sample"][0]["field"], "remainder")

    def test_missing_route_column_is_rejected_before_fit(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "column_transformer_spec.json")
            spec["routes"][3]["columns"] = []
            write_json(root / "column_transformer_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "column_transformer_spec_declares_explicit_routes")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "routes.binary.columns")

    def test_duplicate_routed_column_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "column_transformer_spec.json")
            spec["routes"][0]["columns"].append("support_tickets_14d")
            write_json(root / "column_transformer_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "column_transformer_spec_declares_explicit_routes")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "routes.columns")
        self.assertEqual(contract["sample"][0]["sample"], ["support_tickets_14d"])

    def test_unknown_bucket_must_be_part_of_categorical_vocabulary(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "column_transformer_spec.json")
            spec["routes"][2]["allowed_categories"]["acquisition_channel"].remove("__unknown__")
            write_json(root / "column_transformer_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "column_transformer_spec_declares_explicit_routes")
        self.assertFalse(report["valid"])
        self.assertIn("allowed_categories.acquisition_channel", contract["sample"][0]["field"])

    def test_one_hot_encoder_cannot_silently_ignore_unknowns_without_bucket(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "column_transformer_spec.json")
            spec["routes"][2]["steps"][1]["params"]["handle_unknown"] = "ignore"
            write_json(root / "column_transformer_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "column_transformer_spec_declares_explicit_routes")
        self.assertFalse(report["valid"])
        self.assertEqual(
            contract["sample"][0]["field"],
            "routes.categorical.steps.one_hot.params.handle_unknown",
        )

    def test_missing_raw_binary_column_blocks_column_transformer(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_raw_features.csv")
            for row in rows:
                del row["had_support_ticket_14d"]
            write_csv(root / "ml_raw_features.csv", rows)

            report = self.audit(root)

        features = check(report, "raw_features_match_column_transformer_routes")
        self.assertFalse(report["valid"])
        self.assertEqual(features["sample"][0]["reason"], "missing feature columns")
        self.assertIn("had_support_ticket_14d", features["sample"][0]["sample"])

    def test_unapproved_raw_feature_column_is_not_silently_dropped(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_raw_features.csv")
            for row in rows:
                row["post_prediction_note"] = "leaky"
            write_csv(root / "ml_raw_features.csv", rows)

            report = self.audit(root)

        features = check(report, "raw_features_match_column_transformer_routes")
        self.assertFalse(report["valid"])
        self.assertEqual(
            features["sample"][0]["reason"],
            "columns would be silently dropped by ColumnTransformer",
        )
        self.assertIn("post_prediction_note", features["sample"][0]["sample"])

    def test_forbidden_target_column_in_raw_features_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_raw_features.csv")
            for row in rows:
                row["churned_14d"] = "false"
            write_csv(root / "ml_raw_features.csv", rows)

            report = self.audit(root)

        features = check(report, "raw_features_match_column_transformer_routes")
        self.assertFalse(report["valid"])
        self.assertEqual(features["sample"][0]["reason"], "forbidden columns present")
        self.assertIn("churned_14d", features["sample"][0]["sample"])

    def test_labels_must_be_complete_for_scored_splits(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_labels.csv")
            rows[0]["label_window_complete"] = "false"
            write_csv(root / "ml_labels.csv", rows)

            report = self.audit(root)

        labels = check(report, "labels_support_column_transformer_training_and_prediction_audit")
        self.assertFalse(report["valid"])
        self.assertEqual(labels["sample"][0]["reason"], "label window is incomplete")

    def test_train_split_must_contain_both_classes_for_estimator(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_labels.csv")
            for row in rows:
                if row["snapshot_id"] in {"S001", "S002", "S003", "S004"}:
                    row["churned_14d"] = "false"
            write_csv(root / "ml_labels.csv", rows)

            report = self.audit(root)

        train_classes = check(
            report, "train_split_has_both_classes_for_column_transformer_estimator"
        )
        self.assertFalse(report["valid"])
        self.assertEqual(train_classes["observed"], [0])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_column_transformer(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "column_transformer_spec.json")
            spec["fit_split"] = "validation"
            write_json(root / "column_transformer_spec.json", spec)
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
            "column_transformer_spec_declares_explicit_routes",
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
        self.assertIn("column_transformer_unknown_categories_bucketed", result.stdout)
