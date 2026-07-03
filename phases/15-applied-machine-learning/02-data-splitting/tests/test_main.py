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
ARTIFACT = LESSON_ROOT / "outputs" / "ml_split_auditor.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from ml_split_auditor import run  # noqa: E402


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


class MLSplitAuditorTest(TestCase):
    def audit(self, root: Path = DATA_ROOT) -> dict:
        return run(
            spec_path=root / "problem_spec.json",
            snapshots_path=root / "ml_scoring_snapshots.csv",
            labels_path=root / "ml_labels.csv",
            manifest_path=root / "ml_split_manifest.csv",
        )

    def copy_profile(self, directory: Path) -> Path:
        target = directory / "tiny"
        shutil.copytree(DATA_ROOT, target)
        return target

    def test_valid_split_is_ready_for_metric_policy_with_tiny_warning(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_metric_policy")
        self.assertEqual(
            report["summary"]["rows_by_split"], {"train": 4, "validation": 3, "test": 5}
        )
        self.assertEqual(
            report["summary"]["positives_by_split"], {"train": 2, "validation": 1, "test": 1}
        )
        self.assertEqual(report["summary"]["blocking_errors"], [])
        self.assertEqual(report["summary"]["warnings"], ["tiny_split_expected"])
        self.assertEqual(
            check(report, "prediction_time_order_respects_holdout")["observed"]["test"]["min"],
            "2026-05-24T09:00:00+03:00",
        )

    def test_code_example_writes_split_report(self) -> None:
        output = LESSON_ROOT / "outputs" / "ml_split_report.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["rows_by_split"], {"train": 4, "validation": 3, "test": 5})
        self.assertEqual(payload["warnings"], ["tiny_split_expected"])
        self.assertEqual(
            read_json(output)["summary"]["readiness_status"], "ready_for_metric_policy"
        )

    def test_data_generator_check_rebuilds_committed_split_manifest(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)

    def test_duplicate_manifest_snapshot_blocks_coverage(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_split_manifest.csv")
            rows.append(dict(rows[0]))
            write_csv(root / "ml_split_manifest.csv", rows)

            report = self.audit(root)

        coverage = check(report, "manifest_schema_and_coverage")
        self.assertFalse(report["valid"])
        self.assertFalse(coverage["valid"])
        self.assertIn("manifest_schema_and_coverage", report["summary"]["blocking_errors"])

    def test_missing_eligible_snapshot_blocks_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = [
                row
                for row in read_csv(root / "ml_split_manifest.csv")
                if row["snapshot_id"] != "S006"
            ]
            write_csv(root / "ml_split_manifest.csv", rows)

            report = self.audit(root)

        coverage = check(report, "manifest_schema_and_coverage")
        self.assertFalse(report["valid"])
        self.assertEqual(coverage["sample"][0]["reason"], "eligible rows missing")
        self.assertIn("S006", coverage["sample"][0]["sample"])

    def test_ineligible_snapshot_cannot_enter_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            manifest = read_csv(root / "ml_split_manifest.csv")
            snapshots = {
                row["snapshot_id"]: row for row in read_csv(root / "ml_scoring_snapshots.csv")
            }
            s008 = snapshots["S008"]
            manifest.append(
                {
                    "snapshot_id": "S008",
                    "user_id": s008["user_id"],
                    "prediction_time": s008["prediction_time"],
                    "split": "validation",
                    "split_order": "2",
                    "role": "model_selection_and_threshold_selection",
                    "assigned_by_policy": "chronological_group_holdout",
                }
            )
            write_csv(root / "ml_split_manifest.csv", manifest)

            report = self.audit(root)

        coverage = check(report, "manifest_schema_and_coverage")
        self.assertFalse(report["valid"])
        self.assertEqual(coverage["sample"][0]["reason"], "manifest contains ineligible rows")
        self.assertIn("S008", coverage["sample"][0]["sample"])

    def test_user_group_cannot_cross_train_and_test(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            snapshots = read_csv(root / "ml_scoring_snapshots.csv")
            manifest = read_csv(root / "ml_split_manifest.csv")
            for row in snapshots:
                if row["snapshot_id"] == "S009":
                    row["user_id"] = "U001"
            for row in manifest:
                if row["snapshot_id"] == "S009":
                    row["user_id"] = "U001"
            write_csv(root / "ml_scoring_snapshots.csv", snapshots)
            write_csv(root / "ml_split_manifest.csv", manifest)

            report = self.audit(root)

        group_check = check(report, "groups_do_not_cross_splits")
        self.assertFalse(report["valid"])
        self.assertFalse(group_check["valid"])
        self.assertEqual(group_check["sample"][0]["user_id"], "U001")

    def test_chronological_holdout_blocks_early_test_rows(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            manifest = read_csv(root / "ml_split_manifest.csv")
            for row in manifest:
                if row["snapshot_id"] == "S004":
                    row["split"] = "test"
                    row["split_order"] = "3"
                    row["role"] = "final_once_only_evaluation"
            write_csv(root / "ml_split_manifest.csv", manifest)

            report = self.audit(root)

        timing = check(report, "prediction_time_order_respects_holdout")
        self.assertFalse(report["valid"])
        self.assertFalse(timing["valid"])
        self.assertEqual(timing["sample"][0]["boundary"], "validation_before_test")

    def test_test_split_cannot_be_used_for_threshold_selection(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            manifest = read_csv(root / "ml_split_manifest.csv")
            for row in manifest:
                if row["snapshot_id"] == "S010":
                    row["role"] = "model_selection_and_threshold_selection"
            write_csv(root / "ml_split_manifest.csv", manifest)

            report = self.audit(root)

        role_check = check(report, "validation_and_test_roles_are_separate")
        self.assertFalse(report["valid"])
        self.assertFalse(role_check["valid"])
        self.assertEqual(role_check["sample"][0]["snapshot_id"], "S010")

    def test_incomplete_label_window_blocks_any_split(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            labels = read_csv(root / "ml_labels.csv")
            for row in labels:
                if row["snapshot_id"] == "S010":
                    row["label_window_complete"] = "false"
            write_csv(root / "ml_labels.csv", labels)

            report = self.audit(root)

        label_check = check(report, "labels_are_observed_after_horizon")
        self.assertFalse(report["valid"])
        self.assertFalse(label_check["valid"])
        self.assertEqual(label_check["sample"][0]["field"], "label_window_complete")

    def test_manifest_prediction_time_must_match_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            manifest = read_csv(root / "ml_split_manifest.csv")
            manifest[0]["prediction_time"] = "2026-05-11T09:00:00+03:00"
            write_csv(root / "ml_split_manifest.csv", manifest)

            report = self.audit(root)

        mirror = check(report, "manifest_matches_snapshot_rows")
        self.assertFalse(report["valid"])
        self.assertFalse(mirror["valid"])
        self.assertEqual(mirror["sample"][0]["field"], "prediction_time")

    def test_all_three_splits_are_required(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            manifest = read_csv(root / "ml_split_manifest.csv")
            for row in manifest:
                if row["split"] == "validation":
                    row["split"] = "train"
                    row["split_order"] = "1"
                    row["role"] = "fit_preprocessing_and_estimator"
            write_csv(root / "ml_split_manifest.csv", manifest)

            report = self.audit(root)

        coverage = check(report, "manifest_schema_and_coverage")
        self.assertFalse(report["valid"])
        self.assertFalse(coverage["valid"])
        self.assertIn("validation", coverage["sample"][-1]["missing"])

    def test_problem_split_policy_must_preserve_test_role(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "problem_spec.json")
            spec["split_policy"]["test_role"] = "model_and_threshold_selection"
            write_json(root / "problem_spec.json", spec)

            report = self.audit(root)

        policy = check(report, "split_policy_is_declared")
        self.assertFalse(report["valid"])
        self.assertFalse(policy["valid"])
        self.assertEqual(policy["sample"][0]["field"], "test_role")

    def test_cli_writes_report_and_returns_nonzero_for_invalid_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            manifest = read_csv(root / "ml_split_manifest.csv")
            manifest[0]["snapshot_id"] = "S999"
            write_csv(root / "ml_split_manifest.csv", manifest)
            output = Path(directory) / "split_report.json"

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
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            written_report = read_json(output)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["valid"])
        self.assertEqual(json.loads(result.stdout), written_report)

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
                "--fail-on-warning",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertTrue(json.loads(result.stdout)["valid"])
