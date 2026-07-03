from __future__ import annotations

import csv
import hashlib
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
ARTIFACT = LESSON_ROOT / "outputs" / "ml_baseline_packager.py"
CODE = LESSON_ROOT / "code" / "main.py"
GENERATOR = PHASE_ROOT / "data" / "generate_data.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from ml_baseline_packager import (  # noqa: E402
    DEFAULT_REPORT_PATHS,
    DEFAULT_TABLE_PATHS,
    build_ml_baseline_package,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class MLBaselinePackagerTest(TestCase):
    def build(
        self,
        *,
        spec_path: Path | None = None,
        report_paths: dict[str, Path] | None = None,
        table_paths: dict[str, Path] | None = None,
    ) -> dict:
        return build_ml_baseline_package(
            package_spec_path=spec_path or DATA_ROOT / "ml_baseline_package_spec.json",
            problem_spec_path=DATA_ROOT / "problem_spec.json",
            report_paths=report_paths or DEFAULT_REPORT_PATHS,
            table_paths=table_paths or DEFAULT_TABLE_PATHS,
        )

    def test_valid_package_summary_closes_phase_without_production_claim(self) -> None:
        result = self.build()
        report = result["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["package_id"], "trial-churn-ml-baseline-package-v0")
        self.assertEqual(report["summary"]["model_card_id"], "trial-churn-risk-model-card-v0")
        self.assertEqual(report["decision_status"], "review_required_before_production")
        self.assertEqual(report["summary"]["evidence_row_count"], 14)
        self.assertEqual(report["summary"]["risk_row_count"], 8)
        self.assertEqual(report["summary"]["upstream_warning_count"], 37)
        self.assertEqual(report["summary"]["hidden_failure_slice_count"], 4)
        self.assertFalse(report["summary"]["production_ready"])
        self.assertEqual(report["summary"]["blocking_errors"], [])
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "upstream_warnings_propagated_to_model_card",
                "segment_hidden_failures_block_production_claim",
                "small_n_segment_claims_are_diagnostic_only",
                "model_card_requires_human_review_before_production",
            ],
        )
        self.assertEqual(
            report["summary"]["readiness_status"],
            "phase_15_complete_baseline_package",
        )

    def test_code_example_writes_package_outputs(self) -> None:
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["package_valid"])
        self.assertEqual(payload["decision_status"], "review_required_before_production")
        self.assertEqual(payload["evidence_row_count"], 14)
        self.assertEqual(payload["risk_row_count"], 8)
        self.assertFalse(payload["production_ready"])
        for filename in [
            "ml_baseline_package.json",
            "ml_baseline_package_report.json",
            "model_card.md",
            "decision_report.md",
            "evidence_matrix.csv",
            "risk_register.csv",
            "model_card_policy_audit.csv",
            "ml_baseline_package_manifest.json",
        ]:
            self.assertTrue((LESSON_ROOT / "outputs" / filename).exists(), filename)

    def test_model_card_contains_required_sections_and_boundaries(self) -> None:
        result = self.build()
        card = result["package"]["model_card"]
        markdown = result["model_card_markdown"]

        for section in read_json(DATA_ROOT / "ml_baseline_package_spec.json")["model_card_sections"]:
            self.assertIn(section, card)
        self.assertIn("causal_effect_of_offer", card["out_of_scope_uses"])
        self.assertIn("automatic_account_action", card["out_of_scope_uses"])
        self.assertIn("does not estimate the causal effect", markdown)
        self.assertIn("review_required_before_production", markdown)
        self.assertIn("platform=android", markdown)
        self.assertFalse(card["ethical_considerations"]["automated_action_allowed"])

    def test_evidence_matrix_preserves_upstream_warnings_and_no_peeking(self) -> None:
        result = self.build()
        rows = {row["evidence_id"]: row for row in result["evidence_matrix"]}

        self.assertEqual(len(rows), 14)
        self.assertTrue(all(row["valid"] for row in rows.values()))
        self.assertEqual(rows["error_analysis_report"]["warning_count"], 3)
        self.assertEqual(rows["error_analysis_report"]["key_summary"]["overall_precision"], 0.5)
        self.assertEqual(rows["leakage_report"]["key_summary"]["test_used_for_model_selection"], False)
        self.assertTrue(check(result["report"], "final_holdout_not_used_for_selection")["valid"])
        warning = check(result["report"], "upstream_warnings_propagated_to_model_card")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])

    def test_risk_register_blocks_segment_and_causal_overclaims(self) -> None:
        result = self.build()
        rows = {row["risk_id"]: row for row in result["risk_register"]}

        self.assertEqual(rows["hidden_segment_failure"]["status"], "blocks_production_claim")
        self.assertEqual(rows["small_n_segment_metrics"]["status"], "diagnostic_only")
        self.assertEqual(rows["no_causal_offer_effect"]["status"], "out_of_scope")
        self.assertEqual(rows["forbidden_features_rejected"]["status"], "control_passed")
        self.assertEqual(rows["model_artifact_security"]["status"], "requires_secure_serving_review")
        self.assertFalse(result["package"]["decision"]["production_ready"])
        self.assertIn("auto_deploy_model", result["package"]["decision"]["blocked_actions"])

    def test_manifest_hashes_inputs_and_generated_outputs(self) -> None:
        result = self.build()
        manifest = result["manifest"]
        spec_hash = hashlib.sha256((DATA_ROOT / "ml_baseline_package_spec.json").read_bytes()).hexdigest()

        self.assertEqual(manifest["hash_algorithm"], "sha256")
        self.assertEqual(manifest["inputs"]["package_spec"]["sha256"], spec_hash)
        self.assertEqual(len(manifest["inputs"]), 29)
        self.assertEqual(set(manifest["outputs"]), {
            "decision_report.md",
            "evidence_matrix.csv",
            "ml_baseline_package.json",
            "ml_baseline_package_report.json",
            "model_card.md",
            "model_card_policy_audit.csv",
            "risk_register.csv",
        })
        self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["outputs"].values()))

    def test_data_generator_check_rebuilds_committed_package_spec(self) -> None:
        result = subprocess.run(
            [sys.executable, GENERATOR, "--check", "--output", DATA_ROOT],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)
        self.assertTrue((DATA_ROOT / "ml_baseline_package_spec.json").exists())

    def test_invalid_upstream_report_blocks_package(self) -> None:
        with TemporaryDirectory() as directory:
            report_path = Path(directory) / "error_analysis_report.json"
            report = read_json(DEFAULT_REPORT_PATHS["error_analysis_report"])
            report["valid"] = False
            report["summary"]["blocking_errors"] = ["synthetic_failure"]
            write_json(report_path, report)
            report_paths = dict(DEFAULT_REPORT_PATHS)
            report_paths["error_analysis_report"] = report_path

            result = self.build(report_paths=report_paths)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("upstream_reports_are_structurally_valid", result["summary"]["blocking_errors"])

    def test_missing_model_card_section_blocks_package(self) -> None:
        with TemporaryDirectory() as directory:
            spec_path = Path(directory) / "ml_baseline_package_spec.json"
            spec = read_json(DATA_ROOT / "ml_baseline_package_spec.json")
            spec["model_card_sections"].remove("limitations")
            write_json(spec_path, spec)

            result = self.build(spec_path=spec_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("model_card_sections_complete", result["summary"]["blocking_errors"])

    def test_production_ready_policy_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            spec_path = Path(directory) / "ml_baseline_package_spec.json"
            spec = read_json(DATA_ROOT / "ml_baseline_package_spec.json")
            spec["decision_policy"]["valid_with_warnings_status"] = "production_ready"
            write_json(spec_path, spec)

            result = self.build(spec_path=spec_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn(
            "decision_policy_blocks_production_and_causal_claims",
            result["summary"]["blocking_errors"],
        )

    def test_hidden_failure_table_cannot_be_dropped(self) -> None:
        with TemporaryDirectory() as directory:
            hidden_path = Path(directory) / "hidden_failure_slices.csv"
            _rows, fields = read_csv(DEFAULT_TABLE_PATHS["hidden_failure_slices"])
            write_csv(hidden_path, [], fields)
            table_paths = dict(DEFAULT_TABLE_PATHS)
            table_paths["hidden_failure_slices"] = hidden_path

            result = self.build(table_paths=table_paths)["report"]

        self.assertFalse(result["valid"])
        self.assertIn(
            "error_analysis_evidence_counts_match_report",
            result["summary"]["blocking_errors"],
        )

    def test_cli_writes_output_dir_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            write_result = subprocess.run(
                [sys.executable, ARTIFACT, "--output-dir", output_dir],
                check=True,
                capture_output=True,
                text=True,
            )
            strict_result = subprocess.run(
                [sys.executable, ARTIFACT, "--fail-on-warning"],
                check=False,
                capture_output=True,
                text=True,
            )
            model_card_exists = (output_dir / "model_card.md").exists()
            manifest_exists = (output_dir / "ml_baseline_package_manifest.json").exists()

        payload = json.loads(write_result.stdout)
        self.assertEqual(payload["decision_status"], "review_required_before_production")
        self.assertTrue(model_card_exists)
        self.assertTrue(manifest_exists)
        self.assertEqual(strict_result.returncode, 1)
        strict_payload = json.loads(strict_result.stdout)
        self.assertEqual(strict_payload["blocking_errors"], [])
        self.assertIn("model_card_requires_human_review_before_production", strict_payload["warnings"])

    def test_missing_problem_spec_is_structured_cli_failure(self) -> None:
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--problem-spec",
                    Path(directory) / "missing_problem_spec.json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["blocking_errors"], ["ml_baseline_package_runtime_error"])
