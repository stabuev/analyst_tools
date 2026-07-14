from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
ARTIFACT = LESSON_ROOT / "outputs" / "tabular_ml_interpretation_packager.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from tabular_ml_interpretation_packager import (  # noqa: E402
    DEFAULT_REPORT_PATHS,
    DEFAULT_TABLE_PATHS,
    build_tabular_ml_package,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class TabularMLInterpretationPackagerTest(TestCase):
    def build(
        self,
        *,
        spec_path: Path | None = None,
        report_paths: dict[str, Path] | None = None,
        table_paths: dict[str, Path] | None = None,
    ) -> dict:
        return build_tabular_ml_package(
            spec_path=spec_path or DATA_ROOT / "tabular_ml_package_spec.json",
            report_paths=report_paths or DEFAULT_REPORT_PATHS,
            table_paths=table_paths or DEFAULT_TABLE_PATHS,
        )

    def test_valid_package_keeps_baseline_and_closes_phase(self) -> None:
        result = self.build()
        report = result["report"]
        summary = report["summary"]

        self.assertTrue(report["valid"])
        self.assertEqual(summary["package_id"], "trial-churn-tabular-ml-interpretation-package-v0")
        self.assertEqual(report["decision_status"], "keep_baseline")
        self.assertEqual(summary["monitoring_status"], "drift_watch_required")
        self.assertEqual(summary["evidence_row_count"], 16)
        self.assertEqual(summary["upstream_report_count"], 11)
        self.assertEqual(summary["upstream_warning_count"], 49)
        self.assertEqual(summary["feature_drift_watch_count"], 1)
        self.assertEqual(summary["importance_stability_watch_count"], 4)
        self.assertEqual(summary["hidden_failure_slice_count"], 13)
        self.assertEqual(summary["failed_promotion_gate_count"], 4)
        self.assertFalse(summary["production_ready"])
        self.assertEqual(summary["blocking_errors"], [])
        self.assertEqual(
            summary["warnings"],
            [
                "feature_drift_watch_required",
                "unstable_explanations_require_review",
                "segment_hidden_failures_block_candidate_promotion",
                "candidate_not_promoted_due_to_cost_and_segment_gate",
                "local_tracking_store_not_serving_release",
            ],
        )
        self.assertEqual(summary["readiness_status"], "phase_16_complete_tabular_ml_interpretation_package")

    def test_score_drift_is_separate_from_feature_drift(self) -> None:
        rows = {row["split"]: row for row in self.build()["score_drift"]}

        self.assertEqual(rows["train"]["mean_score"], 0.5)
        self.assertEqual(rows["validation"]["mean_score"], 0.498333)
        self.assertEqual(rows["validation"]["mean_delta_vs_reference"], -0.001667)
        self.assertEqual(rows["validation"]["ks_like_gap_vs_reference"], 0.166667)
        self.assertEqual(rows["test"]["positive_rate"], 0.2)
        self.assertTrue(all(row["stability_status"] == "stable" for row in rows.values()))

    def test_feature_drift_flags_unseen_acquisition_channel(self) -> None:
        rows = {row["feature_name"]: row for row in self.build()["feature_drift"]}
        acquisition = rows["acquisition_channel"]

        self.assertEqual(acquisition["after_train_row_count"], 8)
        self.assertEqual(acquisition["unseen_after_train_count"], 3)
        self.assertEqual(acquisition["unseen_after_train_rate"], 0.375)
        self.assertEqual(acquisition["missing_after_train_count"], 1)
        self.assertTrue(acquisition["high_cardinality_feature"])
        self.assertEqual(acquisition["stability_status"], "watch")
        self.assertEqual(rows["platform"]["stability_status"], "stable")
        self.assertFalse(check(self.build()["report"], "feature_drift_watch_required")["valid"])

    def test_importance_stability_preserves_method_disagreement(self) -> None:
        rows = self.build()["importance_stability"]

        self.assertEqual(len(rows), 4)
        self.assertTrue(all(row["top_feature_name"] == "platform" for row in rows))
        self.assertTrue(all(row["same_top_feature_across_methods"] for row in rows))
        self.assertEqual(rows[0]["direction_set"], "loss_decrease_when_permuted,mixed,negative,positive")
        self.assertTrue(all(row["stability_status"] == "watch" for row in rows))
        methods = {row["method"] for row in rows}
        self.assertIn("CatBoost PredictionValuesChange", methods)
        self.assertIn("Permutation importance", methods)
        self.assertIn("Tree SHAP mean_abs", methods)

    def test_segment_stability_carries_hidden_failures_and_blocks_promotion(self) -> None:
        result = self.build()
        rows = result["segment_stability"]
        hidden = [row for row in rows if row["hidden_failure_candidate"]]
        overall = next(row for row in rows if row["dimension"] == "overall")

        self.assertEqual(len(rows), 19)
        self.assertEqual(len(hidden), 13)
        self.assertEqual(overall["stability_status"], "watch")
        self.assertTrue(overall["candidate_worse_than_baseline"])
        self.assertIn("new_false_negative_ids:S006", overall["hidden_failure_reasons"])
        self.assertFalse(check(result["report"], "segment_hidden_failures_block_candidate_promotion")["valid"])

    def test_evidence_matrix_links_upstream_and_generated_diagnostics(self) -> None:
        rows = {row["evidence_id"]: row for row in self.build()["evidence_matrix"]}

        self.assertEqual(len(rows), 16)
        self.assertTrue(rows["baseline_package_manifest"]["valid"])
        self.assertEqual(rows["mlflow_report"]["warning_count"], 3)
        self.assertEqual(rows["mlflow_report"]["package_section"], "upstream")
        self.assertEqual(rows["feature_drift"]["warning_count"], 1)
        self.assertEqual(rows["segment_stability"]["key_summary"]["hidden_failure_count"], 13)
        self.assertIn("phases/16-tabular-ml/10-mlflow", rows["mlflow_report"]["source_path"])

    def test_reports_preserve_interpretation_and_serving_boundaries(self) -> None:
        result = self.build()
        interpretation = result["interpretation_report"]
        decision = result["decision_report"]

        self.assertIn("CatBoost built-in importance, permutation importance and Tree SHAP", interpretation)
        self.assertIn("`platform`", interpretation)
        self.assertIn("model behavior evidence, not a causal claim", interpretation)
        self.assertIn("Decision status: `keep_baseline`", decision)
        self.assertIn("does not make a causal claim", decision)
        self.assertIn("not a production serving release", decision)
        self.assertIn("not online monitoring", decision)

    def test_manifest_hashes_inputs_and_generated_outputs(self) -> None:
        result = self.build()
        manifest = result["manifest"]
        spec_hash = hashlib.sha256((DATA_ROOT / "tabular_ml_package_spec.json").read_bytes()).hexdigest()

        self.assertEqual(manifest["hash_algorithm"], "sha256")
        self.assertEqual(manifest["inputs"]["package_spec"]["sha256"], spec_hash)
        self.assertEqual(len(manifest["inputs"]), 37)
        self.assertEqual(set(manifest["outputs"]), {
            "decision_report.md",
            "feature_drift.csv",
            "importance_stability.csv",
            "interpretation_report.md",
            "score_drift.csv",
            "segment_stability.csv",
            "stability_report.json",
            "tabular_ml_evidence_matrix.csv",
            "tabular_ml_package.json",
            "tabular_ml_package_report.json",
        })
        self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest["outputs"].values()))
        self.assertTrue(check(result["report"], "manifest_hashes_inputs_and_generated_outputs")["valid"])

    def test_invalid_upstream_report_blocks_package(self) -> None:
        with TemporaryDirectory() as directory:
            report_path = Path(directory) / "mlflow_experiment_report.json"
            report = read_json(DEFAULT_REPORT_PATHS["mlflow_report"])
            report["valid"] = False
            report["summary"]["blocking_errors"] = ["synthetic_tracking_failure"]
            write_json(report_path, report)
            report_paths = dict(DEFAULT_REPORT_PATHS)
            report_paths["mlflow_report"] = report_path

            result = self.build(report_paths=report_paths)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("upstream_reports_are_valid", result["summary"]["blocking_errors"])

    def test_promotion_status_is_rejected_when_decision_gates_fail(self) -> None:
        with TemporaryDirectory() as directory:
            spec_path = Path(directory) / "tabular_ml_package_spec.json"
            spec = read_json(DATA_ROOT / "tabular_ml_package_spec.json")
            spec["decision_policy"]["candidate_failed_gate_status"] = "promote_candidate_with_limits"
            write_json(spec_path, spec)

            result = self.build(spec_path=spec_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn(
            "candidate_cannot_be_promoted_when_required_decision_gates_fail",
            result["summary"]["blocking_errors"],
        )

    def test_production_or_causal_policy_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            spec_path = Path(directory) / "tabular_ml_package_spec.json"
            spec = read_json(DATA_ROOT / "tabular_ml_package_spec.json")
            spec["decision_policy"]["production_ready_allowed"] = True
            write_json(spec_path, spec)

            result = self.build(spec_path=spec_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn(
            "decision_policy_blocks_production_causal_and_serving_claims",
            result["summary"]["blocking_errors"],
        )

    def test_missing_required_evidence_file_blocks_before_package_build(self) -> None:
        with TemporaryDirectory() as directory:
            missing_path = Path(directory) / "missing_mlflow_run_table.csv"
            table_paths = dict(DEFAULT_TABLE_PATHS)
            table_paths["mlflow_run_table"] = missing_path

            result = self.build(table_paths=table_paths)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("required_upstream_evidence_files_exist", result["summary"]["blocking_errors"])

    def test_code_example_and_artifact_cli_write_expected_outputs(self) -> None:
        completed = subprocess.run([sys.executable, str(CODE)], check=True, capture_output=True, text=True)
        payload = json.loads(completed.stdout)

        self.assertTrue(payload["package_valid"])
        self.assertEqual(payload["decision_status"], "keep_baseline")
        self.assertEqual(payload["feature_drift_watch_count"], 1)
        self.assertEqual(payload["importance_stability_watch_count"], 4)
        self.assertFalse(payload["production_ready"])
        for filename in [
            "tabular_ml_package.json",
            "tabular_ml_package_report.json",
            "tabular_ml_evidence_matrix.csv",
            "score_drift.csv",
            "feature_drift.csv",
            "importance_stability.csv",
            "segment_stability.csv",
            "stability_report.json",
            "interpretation_report.md",
            "decision_report.md",
            "tabular_ml_package_manifest.json",
        ]:
            self.assertTrue((LESSON_ROOT / "outputs" / filename).is_file(), filename)

        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            normal = subprocess.run(
                [sys.executable, str(ARTIFACT), "--output-dir", str(output_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
            strict = subprocess.run(
                [sys.executable, str(ARTIFACT), "--output-dir", str(output_dir), "--fail-on-warning"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertTrue((output_dir / "tabular_ml_package_manifest.json").is_file())

        self.assertEqual(normal.stdout, "")
        self.assertEqual(strict.returncode, 2)
