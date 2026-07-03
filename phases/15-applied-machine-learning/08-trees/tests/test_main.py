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
ARTIFACT = LESSON_ROOT / "outputs" / "tree_diagnostic_trainer.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from tree_diagnostic_trainer import run  # noqa: E402


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


class TreeDiagnosticTrainerTest(TestCase):
    def audit(self, root: Path = DATA_ROOT, **outputs: Path) -> dict:
        return run(
            spec_path=root / "problem_spec.json",
            preprocessing_contract_path=root / "preprocessing_contract.json",
            pipeline_spec_path=root / "pipeline_spec.json",
            column_transformer_spec_path=root / "column_transformer_spec.json",
            linear_baseline_spec_path=root / "linear_baseline_spec.json",
            tree_diagnostic_spec_path=root / "tree_diagnostic_spec.json",
            features_path=root / "ml_raw_features.csv",
            labels_path=root / "ml_labels.csv",
            manifest_path=root / "ml_split_manifest.csv",
            **outputs,
        )

    def copy_profile(self, directory: Path) -> Path:
        target = directory / "tiny"
        shutil.copytree(DATA_ROOT, target)
        return target

    def test_valid_tree_diagnostic_exports_overfit_probe(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["tree_diagnostic_id"], "trial-churn-tree-diagnostic-v0")
        self.assertEqual(report["summary"]["sklearn_version"], "1.9.0")
        self.assertEqual(report["summary"]["fit_split"], "train")
        self.assertEqual(report["summary"]["fit_row_count"], 4)
        self.assertEqual(report["summary"]["model_id"], "decision_tree_depth2")
        self.assertEqual(report["summary"]["max_depth_limit"], 2)
        self.assertEqual(report["summary"]["actual_tree_depth"], 1)
        self.assertEqual(report["summary"]["leaf_count"], 2)
        self.assertEqual(report["summary"]["node_count"], 3)
        self.assertEqual(report["summary"]["transformed_feature_count"], 24)
        self.assertEqual(report["summary"]["prediction_row_count"], 12)
        self.assertEqual(report["summary"]["rule_line_count"], 4)
        self.assertEqual(report["summary"]["split_features"], ["categorical__platform_android"])
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_tree_ensemble_lesson")

    def test_tree_metrics_show_train_validation_gap_and_baseline_comparison(self) -> None:
        report = self.audit()

        self.assertEqual(report["summary"]["selected_linear_baseline_id"], "dummy_prior")
        self.assertEqual(report["summary"]["baseline_validation_precision_at_budget"], 0.5)
        self.assertEqual(report["summary"]["tree_validation_precision_at_budget"], 0.0)
        self.assertEqual(
            report["summary"]["train_metrics"],
            {
                "precision_at_budget": 1.0,
                "recall_at_budget": 1.0,
                "average_precision": 1.0,
                "log_loss": 0.0,
                "error_cost_at_budget": 0.0,
                "accuracy_at_0_5": 1.0,
            },
        )
        self.assertEqual(report["summary"]["validation_metrics"]["log_loss"], 24.029102)
        self.assertEqual(report["summary"]["validation_metrics"]["accuracy_at_0_5"], 0.333333)
        self.assertEqual(
            report["summary"]["train_validation_gaps"],
            {
                "accuracy_at_0_5": 0.666667,
                "precision_at_budget": 1.0,
                "log_loss": 24.029102,
            },
        )

    def test_overfit_report_flags_all_declared_gap_metrics(self) -> None:
        report = self.audit()
        rows = {row["metric"]: row for row in report["overfit"]}

        self.assertEqual(set(rows), {"accuracy_at_0_5", "precision_at_budget", "log_loss"})
        self.assertTrue(rows["accuracy_at_0_5"]["warning_triggered"])
        self.assertEqual(rows["accuracy_at_0_5"]["warning_threshold"], 0.25)
        self.assertEqual(rows["precision_at_budget"]["train_validation_gap"], 1.0)
        self.assertEqual(rows["log_loss"]["train_validation_gap"], 24.029102)
        gap_check = check(report, "train_validation_gap_reported")
        self.assertTrue(gap_check["valid"])
        self.assertEqual(
            gap_check["observed"]["triggered"],
            ["accuracy_at_0_5", "precision_at_budget", "log_loss"],
        )

    def test_node_report_and_rules_use_transformed_feature_names(self) -> None:
        report = self.audit()
        nodes = report["nodes"]
        rules = report["rules"]

        self.assertEqual(len(nodes), 3)
        self.assertEqual(nodes[0]["node_id"], 0)
        self.assertEqual(nodes[0]["feature_name"], "categorical__platform_android")
        self.assertEqual(nodes[0]["threshold"], 0.5)
        self.assertEqual(nodes[1]["predicted_class"], 0)
        self.assertEqual(nodes[2]["predicted_class"], 1)
        self.assertIn("categorical__platform_android <= 0.500", rules)
        self.assertIn("weights: [2.000, 0.000] class: 0", rules)
        rules_check = check(report, "tree_rules_exported_with_feature_names")
        self.assertTrue(rules_check["valid"])
        self.assertEqual(
            rules_check["observed"]["used_feature_names"],
            ["categorical__platform_android"],
        )

    def test_predictions_cover_train_validation_and_test_for_gap_diagnostics(self) -> None:
        report = self.audit()
        rows = report["predictions"]

        self.assertEqual(len(rows), 12)
        self.assertEqual({row["split"] for row in rows}, {"train", "validation", "test"})
        self.assertEqual({row["model_id"] for row in rows}, {"decision_tree_depth2"})
        self.assertEqual({row["trained_on_split"] for row in rows}, {"train"})
        scores = {row["snapshot_id"]: row["score"] for row in rows}
        self.assertEqual(
            scores,
            {
                "S001": 1.0,
                "S002": 0.0,
                "S003": 0.0,
                "S004": 1.0,
                "S005": 0.0,
                "S006": 0.0,
                "S007": 1.0,
                "S009": 1.0,
                "S010": 0.0,
                "S011": 0.0,
                "S012": 1.0,
                "S013": 0.0,
            },
        )
        self.assertEqual({row["generated_at"] for row in rows}, {"2026-07-02T12:00:00+03:00"})

    def test_serialized_spec_records_tree_and_handoff_trace(self) -> None:
        report = self.audit()
        serialized = report["serialized_spec"]

        self.assertEqual(serialized["tree_diagnostic_id"], "trial-churn-tree-diagnostic-v0")
        self.assertEqual(serialized["model"]["class"], "DecisionTreeClassifier")
        self.assertEqual(serialized["model"]["actual_depth"], 1)
        self.assertEqual(serialized["model"]["leaf_count"], 2)
        self.assertEqual(serialized["model"]["split_features"], ["categorical__platform_android"])
        self.assertEqual(serialized["baseline_reference"]["selected_baseline_id"], "dummy_prior")
        self.assertFalse(serialized["baseline_reference"]["test_used_for_selection"])
        fit, validation, test = serialized["fit_trace"]
        self.assertEqual(fit["event"], "pipeline.fit")
        self.assertEqual(fit["snapshot_ids"], ["S001", "S002", "S003", "S004"])
        self.assertFalse(validation["fits_anything"])
        self.assertFalse(test["fits_anything"])

    def test_code_example_writes_report_overfit_nodes_rules_predictions_and_serialized_spec(
        self,
    ) -> None:
        report_path = LESSON_ROOT / "outputs" / "tree_report.json"
        overfit_path = LESSON_ROOT / "outputs" / "tree_overfit_report.csv"
        node_path = LESSON_ROOT / "outputs" / "tree_node_report.csv"
        rules_path = LESSON_ROOT / "outputs" / "tree_rules.txt"
        predictions_path = LESSON_ROOT / "outputs" / "tree_predictions.csv"
        serialized_path = LESSON_ROOT / "outputs" / "tree_serialized_spec.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["tree_diagnostic_id"], "trial-churn-tree-diagnostic-v0")
        self.assertEqual(payload["actual_tree_depth"], 1)
        self.assertEqual(payload["split_features"], ["categorical__platform_android"])
        self.assertEqual(payload["tree_validation_precision_at_budget"], 0.0)
        self.assertEqual(payload["baseline_validation_precision_at_budget"], 0.5)
        self.assertEqual(payload["prediction_row_count"], 12)
        self.assertEqual(read_json(report_path)["summary"]["model_id"], "decision_tree_depth2")
        self.assertEqual(len(read_csv(overfit_path)), 3)
        self.assertEqual(len(read_csv(node_path)), 3)
        self.assertIn("categorical__platform_android", rules_path.read_text(encoding="utf-8"))
        self.assertEqual(len(read_csv(predictions_path)), 12)
        self.assertEqual(read_json(serialized_path)["model"]["node_count"], 3)

    def test_data_generator_check_rebuilds_committed_tree_diagnostic_inputs(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)
        self.assertTrue((DATA_ROOT / "tree_diagnostic_spec.json").exists())

    def test_missing_depth_limit_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_diagnostic_spec.json")
            spec["candidate"]["params"]["max_depth"] = None
            write_json(root / "tree_diagnostic_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "tree_diagnostic_spec_declares_constrained_tree")
        self.assertFalse(report["valid"])
        self.assertFalse(contract["valid"])
        self.assertEqual(contract["sample"][0]["field"], "candidate.params.max_depth")

    def test_selection_data_must_stay_validation_not_test(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_diagnostic_spec.json")
            spec["comparison"]["selection_data"] = "test"
            write_json(root / "tree_diagnostic_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "tree_diagnostic_spec_declares_constrained_tree")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "comparison.selection_data")

    def test_rule_export_must_require_feature_names(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_diagnostic_spec.json")
            spec["rule_export"]["require_feature_names"] = False
            write_json(root / "tree_diagnostic_spec.json", spec)

            report = self.audit(root)

        contract = check(report, "tree_diagnostic_spec_declares_constrained_tree")
        self.assertFalse(report["valid"])
        self.assertEqual(contract["sample"][0]["field"], "rule_export.require_feature_names")

    def test_manifest_roles_must_preserve_split_meaning(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_split_manifest.csv")
            rows[0]["role"] = "final_once_only_evaluation"
            write_csv(root / "ml_split_manifest.csv", rows)

            report = self.audit(root)

        manifest = check(report, "split_manifest_supports_tree_diagnostic_roles")
        self.assertFalse(report["valid"])
        self.assertFalse(manifest["valid"])
        self.assertEqual(manifest["sample"][0]["field"], "role")

    def test_upstream_linear_baseline_must_be_valid_before_tree_fit(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "linear_baseline_spec.json")
            spec["fit_split"] = "validation"
            write_json(root / "linear_baseline_spec.json", spec)

            report = self.audit(root)

        upstream = check(report, "upstream_linear_baseline_audit_is_valid")
        self.assertFalse(report["valid"])
        self.assertFalse(upstream["valid"])
        self.assertIn(
            "upstream_linear_baseline_audit_is_valid",
            report["summary"]["blocking_errors"],
        )

    def test_tree_fit_requires_both_train_classes(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_labels.csv")
            for row in rows:
                if row["snapshot_id"] in {"S001", "S002", "S003", "S004"}:
                    row["churned_14d"] = "false"
            write_csv(root / "ml_labels.csv", rows)

            report = self.audit(root)

        upstream = check(report, "upstream_linear_baseline_audit_is_valid")
        self.assertFalse(report["valid"])
        self.assertFalse(upstream["valid"])

    def test_gap_and_baseline_failures_are_warnings_not_blocking_errors(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        gap = check(report, "tree_train_validation_gap_exceeds_threshold")
        worse = check(report, "tree_diagnostic_worse_than_selected_baseline_on_validation")
        self.assertEqual(gap["severity"], "warning")
        self.assertFalse(gap["valid"])
        self.assertEqual(gap["observed"][0]["metric"], "accuracy_at_0_5")
        self.assertEqual(worse["severity"], "warning")
        self.assertFalse(worse["valid"])
        self.assertEqual(worse["observed"]["selected_baseline_id"], "dummy_prior")
        self.assertEqual(worse["observed"]["tree_precision_at_budget"], 0.0)

    def test_cli_writes_report_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "tree_diagnostic_spec.json")
            spec["candidate"]["kind"] = "random_forest_classifier"
            write_json(root / "tree_diagnostic_spec.json", spec)
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
            "tree_diagnostic_spec_declares_constrained_tree",
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
        self.assertIn("tree_train_validation_gap_exceeds_threshold", result.stdout)
