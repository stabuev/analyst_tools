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
ARTIFACT = LESSON_ROOT / "outputs" / "classification_metric_evaluator.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from classification_metric_evaluator import run  # noqa: E402


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


class ClassificationMetricEvaluatorTest(TestCase):
    def audit(self, root: Path = DATA_ROOT) -> dict:
        return run(
            spec_path=root / "problem_spec.json",
            snapshots_path=root / "ml_scoring_snapshots.csv",
            labels_path=root / "ml_labels.csv",
            manifest_path=root / "ml_split_manifest.csv",
            scores_path=root / "ml_candidate_scores.csv",
        )

    def copy_profile(self, directory: Path) -> Path:
        target = directory / "tiny"
        shutil.copytree(DATA_ROOT, target)
        return target

    def test_valid_metric_policy_selects_threshold_on_validation(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["model_id"], "candidate_risk_score_v0")
        self.assertEqual(report["summary"]["selected_threshold"], 0.6)
        self.assertEqual(report["summary"]["threshold_selected_on"], "validation")
        self.assertEqual(report["summary"]["offer_budget"], 2)
        self.assertEqual(report["summary"]["blocking_errors"], [])
        self.assertEqual(report["summary"]["warnings"], ["tiny_metric_sample_expected"])
        self.assertEqual(
            report["summary"]["readiness_status"], "ready_for_preprocessing_and_baselines"
        )

    def test_confusion_metrics_match_manual_control(self) -> None:
        report = self.audit()
        validation = report["summary"]["metrics_at_selected_threshold"]["validation"]
        test = report["summary"]["metrics_at_selected_threshold"]["test"]

        self.assertEqual(
            {key: validation[key] for key in ("tp", "fp", "tn", "fn")},
            {"tp": 1, "fp": 1, "tn": 1, "fn": 0},
        )
        self.assertEqual(validation["precision"], 0.5)
        self.assertEqual(validation["recall"], 1.0)
        self.assertEqual(validation["fpr"], 0.5)
        self.assertEqual(validation["total_error_cost"], 1.0)
        self.assertEqual(
            {key: test[key] for key in ("tp", "fp", "tn", "fn")},
            {"tp": 1, "fp": 1, "tn": 3, "fn": 0},
        )
        self.assertEqual(test["precision"], 0.5)
        self.assertEqual(test["recall"], 1.0)
        self.assertEqual(test["fpr"], 0.25)

    def test_ranking_metrics_are_pr_oriented_and_accuracy_is_diagnostic(self) -> None:
        report = self.audit()

        self.assertEqual(report["summary"]["accuracy_role"], "diagnostic_only")
        self.assertEqual(
            report["summary"]["ranking_metrics_by_split"]["validation"]["average_precision"],
            0.5,
        )
        self.assertEqual(
            report["summary"]["ranking_metrics_by_split"]["validation"]["roc_auc"],
            0.5,
        )
        self.assertEqual(
            report["summary"]["ranking_metrics_by_split"]["test"]["average_precision"],
            1.0,
        )

    def test_code_example_writes_metric_report(self) -> None:
        output = LESSON_ROOT / "outputs" / "classification_metric_report.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["selected_threshold"], 0.6)
        self.assertEqual(payload["test_precision"], 0.5)
        self.assertEqual(payload["warnings"], ["tiny_metric_sample_expected"])
        self.assertEqual(read_json(output)["summary"]["selected_threshold"], 0.6)

    def test_data_generator_check_rebuilds_committed_candidate_scores(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)

    def test_missing_score_blocks_metric_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = [
                row
                for row in read_csv(root / "ml_candidate_scores.csv")
                if row["snapshot_id"] != "S006"
            ]
            write_csv(root / "ml_candidate_scores.csv", rows)

            report = self.audit(root)

        coverage = check(report, "score_schema_and_coverage")
        self.assertFalse(report["valid"])
        self.assertFalse(coverage["valid"])
        self.assertEqual(coverage["sample"][0]["reason"], "split rows missing scores")
        self.assertIn("S006", coverage["sample"][0]["sample"])

    def test_duplicate_score_row_blocks_metric_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_candidate_scores.csv")
            rows.append(dict(rows[0]))
            write_csv(root / "ml_candidate_scores.csv", rows)

            report = self.audit(root)

        coverage = check(report, "score_schema_and_coverage")
        self.assertFalse(report["valid"])
        self.assertEqual(coverage["sample"][0]["reason"], "duplicate score rows")

    def test_ineligible_snapshot_score_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            scores = read_csv(root / "ml_candidate_scores.csv")
            scores.append(
                {
                    "snapshot_id": "S008",
                    "model_id": "candidate_risk_score_v0",
                    "score": "0.99",
                    "score_type": "churn_risk_probability",
                    "trained_on_split": "train",
                    "generated_at": "2026-06-08T09:00:00+03:00",
                }
            )
            write_csv(root / "ml_candidate_scores.csv", scores)

            report = self.audit(root)

        coverage = check(report, "score_schema_and_coverage")
        self.assertFalse(report["valid"])
        self.assertEqual(coverage["sample"][0]["reason"], "scores for rows outside split manifest")
        self.assertIn("S008", coverage["sample"][0]["sample"])

    def test_score_must_be_probability(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_candidate_scores.csv")
            rows[0]["score"] = "1.2"
            write_csv(root / "ml_candidate_scores.csv", rows)

            report = self.audit(root)

        coverage = check(report, "score_schema_and_coverage")
        self.assertFalse(report["valid"])
        self.assertEqual(coverage["sample"][0]["field"], "score")

    def test_scores_must_be_declared_as_train_fitted_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_candidate_scores.csv")
            rows[0]["trained_on_split"] = "validation"
            write_csv(root / "ml_candidate_scores.csv", rows)

            report = self.audit(root)

        coverage = check(report, "score_schema_and_coverage")
        self.assertFalse(report["valid"])
        self.assertEqual(coverage["sample"][0]["field"], "trained_on_split")

    def test_threshold_policy_must_not_select_on_test(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "problem_spec.json")
            spec["threshold_policy"]["selection_data"] = "test"
            write_json(root / "problem_spec.json", spec)

            report = self.audit(root)

        policy = check(report, "metric_and_threshold_policy_are_declared")
        self.assertFalse(report["valid"])
        self.assertFalse(policy["valid"])
        self.assertEqual(policy["sample"][0]["field"], "threshold_policy.selection_data")

    def test_cost_weights_are_required_and_non_negative(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "problem_spec.json")
            spec["metric_policy"]["cost_weights"]["false_negative"] = -1
            write_json(root / "problem_spec.json", spec)

            report = self.audit(root)

        policy = check(report, "metric_and_threshold_policy_are_declared")
        self.assertFalse(report["valid"])
        self.assertFalse(policy["valid"])
        self.assertEqual(policy["sample"][0]["field"], "metric_policy.cost_weights.false_negative")

    def test_validation_split_needs_both_classes_for_pr_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            labels = read_csv(root / "ml_labels.csv")
            for row in labels:
                if row["snapshot_id"] == "S006":
                    row["churned_14d"] = "false"
            write_csv(root / "ml_labels.csv", labels)

            report = self.audit(root)

        roles = check(report, "labels_and_split_roles_support_metrics")
        self.assertFalse(report["valid"])
        self.assertFalse(roles["valid"])
        self.assertEqual(roles["sample"][0]["split"], "validation")

    def test_test_split_role_cannot_be_threshold_selection(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            manifest = read_csv(root / "ml_split_manifest.csv")
            for row in manifest:
                if row["snapshot_id"] == "S010":
                    row["role"] = "model_selection_and_threshold_selection"
            write_csv(root / "ml_split_manifest.csv", manifest)

            report = self.audit(root)

        roles = check(report, "labels_and_split_roles_support_metrics")
        self.assertFalse(report["valid"])
        self.assertEqual(roles["sample"][0]["field"], "role")
        self.assertEqual(roles["sample"][0]["split"], "test")

    def test_over_budget_threshold_is_visible_but_not_selected(self) -> None:
        report = self.audit()

        sweep = report["summary"]["validation_threshold_sweep"]
        over_budget = next(row for row in sweep if row["threshold"] == 0.3)
        self.assertEqual(over_budget["budget_status"], "over_budget")
        self.assertEqual(over_budget["offer_count"], 3)
        self.assertEqual(report["summary"]["selected_threshold"], 0.6)

    def test_cli_writes_report_and_returns_nonzero_for_invalid_scores(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_candidate_scores.csv")
            rows[0]["score"] = "bad"
            write_csv(root / "ml_candidate_scores.csv", rows)
            output = Path(directory) / "report.json"

            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--spec",
                    root / "problem_spec.json",
                    "--snapshots",
                    root / "ml_scoring_snapshots.csv",
                    "--labels",
                    root / "ml_labels.csv",
                    "--manifest",
                    root / "ml_split_manifest.csv",
                    "--scores",
                    root / "ml_candidate_scores.csv",
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(report["valid"])
        self.assertIn("score_schema_and_coverage", report["summary"]["blocking_errors"])

    def test_cli_can_fail_on_warning_for_strict_gate(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--spec",
                DATA_ROOT / "problem_spec.json",
                "--snapshots",
                DATA_ROOT / "ml_scoring_snapshots.csv",
                "--labels",
                DATA_ROOT / "ml_labels.csv",
                "--manifest",
                DATA_ROOT / "ml_split_manifest.csv",
                "--scores",
                DATA_ROOT / "ml_candidate_scores.csv",
                "--fail-on-warning",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("tiny_metric_sample_expected", result.stdout)
