from __future__ import annotations

import copy
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
ARTIFACT = LESSON_ROOT / "outputs" / "ml_problem_spec_validator.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from ml_problem_spec_validator import run  # noqa: E402


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


class MLProblemSpecValidatorTest(TestCase):
    def audit(self, root: Path = DATA_ROOT) -> dict:
        return run(
            spec_path=root / "problem_spec.json",
            snapshots_path=root / "ml_scoring_snapshots.csv",
            labels_path=root / "ml_labels.csv",
            feature_sources_path=root / "feature_source_inventory.csv",
        )

    def copy_profile(self, root: Path) -> Path:
        target = root / "tiny"
        shutil.copytree(DATA_ROOT, target)
        return target

    def test_valid_problem_is_ready_for_split_design_with_imbalance_warning(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_split_design")
        self.assertEqual(report["summary"]["eligible_prediction_rows"], 12)
        self.assertEqual(report["summary"]["positive_labels"], 4)
        self.assertEqual(report["summary"]["negative_labels"], 8)
        self.assertEqual(report["summary"]["blocking_errors"], [])
        self.assertEqual(report["summary"]["warnings"], ["class_imbalance_expected"])
        self.assertEqual(
            check(report, "target_has_horizon_and_classes")["observed"]["horizon_days"], 14
        )

    def test_code_example_writes_readiness_report(self) -> None:
        output = LESSON_ROOT / "outputs" / "ml_problem_readiness_report.json"
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["eligible_prediction_rows"], 12)
        self.assertEqual(payload["warnings"], ["class_imbalance_expected"])
        self.assertEqual(
            read_json(output)["summary"]["problem_id"], "trial-churn-risk-7d-before-end"
        )

    def test_data_generator_check_rebuilds_committed_tiny_profile(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)

    def test_duplicate_snapshot_id_blocks_prediction_unit(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_scoring_snapshots.csv")
            rows.append(dict(rows[0]))
            write_csv(root / "ml_scoring_snapshots.csv", rows)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn("prediction_unit_is_snapshot", report["summary"]["blocking_errors"])
        self.assertFalse(check(report, "prediction_unit_is_snapshot")["valid"])

    def test_label_before_horizon_blocks_target_contract(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_labels.csv")
            rows[0]["label_observed_at"] = "2026-05-12T12:00:00+03:00"
            write_csv(root / "ml_labels.csv", rows)

            report = self.audit(root)

        target = check(report, "target_has_horizon_and_classes")
        self.assertFalse(report["valid"])
        self.assertFalse(target["valid"])
        self.assertEqual(target["sample"][0]["field"], "label_observed_at")

    def test_missing_negative_class_is_not_a_binary_problem(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "problem_spec.json")
            spec.pop("negative_class")
            write_json(root / "problem_spec.json", spec)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn("problem_spec_required_fields", report["summary"]["blocking_errors"])

    def test_allowed_feature_source_cannot_use_post_prediction_information(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "problem_spec.json")
            spec["allowed_feature_sources"].append("cancellation_events_after_prediction")
            spec["forbidden_feature_sources"].remove("cancellation_events_after_prediction")
            write_json(root / "problem_spec.json", spec)

            report = self.audit(root)

        leakage = check(report, "feature_sources_available_before_prediction")
        self.assertFalse(report["valid"])
        self.assertFalse(leakage["valid"])
        self.assertEqual(leakage["sample"][0]["source_id"], "cancellation_events_after_prediction")

    def test_threshold_policy_must_use_validation_not_test(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "problem_spec.json")
            spec["threshold_policy"]["selection_data"] = "test"
            write_json(root / "problem_spec.json", spec)

            report = self.audit(root)

        policies = check(report, "evaluation_policies_predeclared")
        self.assertFalse(report["valid"])
        self.assertFalse(policies["valid"])
        self.assertEqual(policies["sample"][0]["field"], "threshold_policy")

    def test_problem_card_must_block_causal_offer_effect_claim(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "problem_spec.json")
            spec["model_card_policy"]["claim_boundary"] = "The offer will reduce churn."
            spec["model_card_policy"]["out_of_scope_uses"] = ["automatic_account_action"]
            write_json(root / "problem_spec.json", spec)

            report = self.audit(root)

        boundary = check(report, "no_causal_claim_boundary")
        self.assertFalse(report["valid"])
        self.assertFalse(boundary["valid"])

    def test_unknown_label_snapshot_is_blocking(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_labels.csv")
            rows.append({**rows[0], "snapshot_id": "S999"})
            write_csv(root / "ml_labels.csv", rows)

            report = self.audit(root)

        target = check(report, "target_has_horizon_and_classes")
        self.assertFalse(report["valid"])
        self.assertFalse(target["valid"])
        self.assertEqual(target["sample"][0]["field"], "ml_labels.snapshot_id")

    def test_target_must_contain_positive_and_negative_classes(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            rows = read_csv(root / "ml_labels.csv")
            for row in rows:
                if row["snapshot_id"] != "S008":
                    row["churned_14d"] = "true"
            write_csv(root / "ml_labels.csv", rows)

            report = self.audit(root)

        target = check(report, "target_has_horizon_and_classes")
        self.assertFalse(report["valid"])
        self.assertFalse(target["valid"])
        self.assertEqual(target["sample"][-1]["field"], "churned_14d")

    def test_cli_writes_report_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = self.copy_profile(Path(directory))
            spec = read_json(root / "problem_spec.json")
            spec["prediction_unit"] = copy.deepcopy(spec["prediction_unit"])
            spec["prediction_unit"]["key"] = "user_id"
            write_json(root / "problem_spec.json", spec)
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
                    "--feature-sources",
                    root / "feature_source_inventory.csv",
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
                "--feature-sources",
                DATA_ROOT / "feature_source_inventory.csv",
                "--fail-on-warning",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertTrue(json.loads(result.stdout)["valid"])
