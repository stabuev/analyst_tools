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
REPO_ROOT = LESSON_ROOT.parents[2]
PHASE_15_ROOT = REPO_ROOT / "phases" / "15-applied-machine-learning"
PHASE_16_ROOT = REPO_ROOT / "phases" / "16-tabular-ml"
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
UPSTREAM_DATA_ROOT = PHASE_15_ROOT / "data" / "tiny"
ARTIFACT = LESSON_ROOT / "outputs" / "categorical_feature_auditor.py"
CODE = LESSON_ROOT / "code" / "main.py"

sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from categorical_feature_auditor import (  # noqa: E402
    DEFAULT_CATBOOST_REPORT_PATH,
    DEFAULT_FEATURE_AVAILABILITY_PATH,
    run,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class CategoricalFeatureAuditorTest(TestCase):
    def audit(
        self,
        root: Path = DATA_ROOT,
        upstream_root: Path = UPSTREAM_DATA_ROOT,
        **paths: Path,
    ) -> dict:
        return run(
            contract_path=paths.get("contract_path", root / "categorical_feature_contract.json"),
            catboost_spec_path=paths.get("catboost_spec_path", root / "catboost_model_spec.json"),
            catboost_report_path=paths.get("catboost_report_path", DEFAULT_CATBOOST_REPORT_PATH),
            features_path=paths.get("features_path", upstream_root / "ml_raw_features.csv"),
            manifest_path=paths.get("manifest_path", upstream_root / "ml_split_manifest.csv"),
            feature_availability_path=paths.get(
                "feature_availability_path",
                DEFAULT_FEATURE_AVAILABILITY_PATH,
            ),
        )

    def copy_inputs(self, directory: Path) -> tuple[Path, Path, Path]:
        phase16 = directory / "phase16"
        upstream = directory / "upstream"
        reports = directory / "reports"
        phase16.mkdir()
        upstream.mkdir()
        reports.mkdir()

        for filename in ("categorical_feature_contract.json", "catboost_model_spec.json"):
            shutil.copy2(DATA_ROOT / filename, phase16 / filename)
        for filename in ("ml_raw_features.csv", "ml_split_manifest.csv"):
            shutil.copy2(UPSTREAM_DATA_ROOT / filename, upstream / filename)
        shutil.copy2(DEFAULT_CATBOOST_REPORT_PATH, reports / "catboost_report.json")
        shutil.copy2(DEFAULT_FEATURE_AVAILABILITY_PATH, reports / "feature_availability_report.csv")
        return phase16, upstream, reports

    def test_valid_categorical_audit_exports_inventory_and_policy_summary(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["categorical_audit_id"], "trial-churn-categorical-feature-audit-v0")
        self.assertEqual(report["summary"]["catboost_model_id"], "catboost_depth2_native_categories")
        self.assertEqual(
            report["summary"]["cat_features"],
            ["plan_id", "platform", "country", "acquisition_channel"],
        )
        self.assertEqual(report["summary"]["feature_count"], 4)
        self.assertEqual(report["summary"]["inventory_row_count"], 13)
        self.assertEqual(report["summary"]["unknown_category_row_count"], 3)
        self.assertEqual(report["summary"]["unknown_feature_count"], 1)
        self.assertEqual(report["summary"]["missing_category_row_count"], 1)
        self.assertEqual(report["summary"]["high_cardinality_feature_count"], 1)
        self.assertEqual(report["summary"]["rare_level_count"], 6)
        self.assertEqual(report["summary"]["selected_leaky_feature_count"], 0)
        self.assertEqual(report["summary"]["readiness_status"], "ready_for_early_stopping_lesson")

    def test_inventory_tracks_train_validation_test_counts_and_high_cardinality(self) -> None:
        report = self.audit()
        rows = {(row["feature_name"], row["category_value"]): row for row in report["inventory"]}

        self.assertEqual(rows[("plan_id", "trial_basic")]["train_count"], 3)
        self.assertEqual(rows[("plan_id", "trial_basic")]["validation_count"], 2)
        self.assertEqual(rows[("plan_id", "trial_basic")]["test_count"], 3)
        self.assertFalse(rows[("plan_id", "trial_basic")]["rare_in_train"])
        self.assertTrue(rows[("plan_id", "trial_pro")]["rare_in_train"])
        self.assertEqual(rows[("acquisition_channel", "organic")]["train_count"], 2)
        self.assertTrue(rows[("acquisition_channel", "influencer")]["unseen_in_train"])
        self.assertTrue(rows[("acquisition_channel", "__MISSING__")]["missing_value"])
        self.assertTrue(rows[("acquisition_channel", "partnership")]["high_cardinality_feature"])
        self.assertEqual(
            check(report, "high_cardinality_features_are_flagged")["observed"],
            ["acquisition_channel"],
        )

    def test_unknown_categories_are_rows_not_hidden_feature_flags(self) -> None:
        report = self.audit()
        rows = {(row["snapshot_id"], row["feature_name"]): row for row in report["unknowns"]}

        self.assertEqual(set(rows), {("S006", "acquisition_channel"), ("S007", "acquisition_channel"), ("S010", "acquisition_channel")})
        self.assertEqual(rows[("S006", "acquisition_channel")]["category_value"], "influencer")
        self.assertEqual(rows[("S007", "acquisition_channel")]["category_value"], "__MISSING__")
        self.assertTrue(rows[("S007", "acquisition_channel")]["missing_value"])
        self.assertEqual(rows[("S010", "acquisition_channel")]["category_value"], "partnership")
        self.assertEqual(
            {row["policy_action"] for row in report["unknowns"]},
            {"allow_native_catboost_unseen_value_and_monitor"},
        )

    def test_leakage_audit_allows_selected_features_and_rejects_known_bad_candidates(self) -> None:
        report = self.audit()
        rows = {row["feature_name"]: row for row in report["leakage_audit"]}

        self.assertEqual(rows["plan_id"]["decision"], "allowed_delivery_cat_feature")
        self.assertEqual(rows["acquisition_channel"]["timing"], "known_before_prediction_time")
        self.assertFalse(rows["acquisition_channel"]["blocking_if_selected"])
        self.assertEqual(
            rows["segment_churn_rate_full_dataset"]["risk_type"],
            "full_sample_target_encoding",
        )
        self.assertEqual(rows["segment_churn_rate_full_dataset"]["decision"], "rejected_known_bad_candidate")
        self.assertEqual(rows["churned_14d"]["risk_type"], "target_leakage")
        self.assertEqual(rows["retention_offer_accepted"]["risk_type"], "post_intervention_outcome_leakage")

    def test_serialized_contract_records_handoff_and_category_summary(self) -> None:
        report = self.audit()
        serialized = report["serialized_contract"]

        self.assertEqual(serialized["catboost_baseline_id"], "trial-churn-catboost-baseline-v0")
        self.assertEqual(serialized["catboost_model_id"], "catboost_depth2_native_categories")
        self.assertEqual(serialized["missing_category_token"], "__MISSING__")
        self.assertEqual(serialized["category_summary"]["inventory_rows"], 13)
        self.assertEqual(serialized["category_summary"]["unknown_category_row_count"], 3)
        self.assertEqual(serialized["category_summary"]["high_cardinality_features"], ["acquisition_channel"])
        self.assertEqual(serialized["leakage_summary"]["blocked_selected_feature_count"], 0)
        self.assertEqual(
            serialized["upstream_handoff"]["catboost_readiness_status"],
            "ready_for_categorical_feature_lesson",
        )

    def test_code_example_writes_all_categorical_outputs(self) -> None:
        result = subprocess.run([sys.executable, CODE], check=True, capture_output=True, text=True)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["feature_count"], 4)
        self.assertEqual(payload["unknown_category_row_count"], 3)
        self.assertEqual(payload["selected_leaky_feature_count"], 0)
        self.assertEqual(read_json(LESSON_ROOT / "outputs" / "categorical_feature_report.json")["summary"]["inventory_row_count"], 13)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "categorical_inventory.csv")), 13)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "categorical_unknowns.csv")), 3)
        self.assertEqual(len(read_csv(LESSON_ROOT / "outputs" / "categorical_leakage_audit.csv")), 7)
        self.assertEqual(
            read_json(LESSON_ROOT / "outputs" / "categorical_serialized_contract.json")["cat_features"],
            ["plan_id", "platform", "country", "acquisition_channel"],
        )

    def test_invalid_upstream_catboost_report_blocks_handoff(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            catboost_report = read_json(reports / "catboost_report.json")
            catboost_report["valid"] = False
            write_json(reports / "catboost_report.json", catboost_report)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                feature_availability_path=reports / "feature_availability_report.csv",
            )

        self.assertFalse(report["valid"])
        handoff = check(report, "categorical_contract_matches_catboost_handoff")
        self.assertFalse(handoff["valid"])
        self.assertIn("categorical_contract_matches_catboost_handoff", report["summary"]["blocking_errors"])

    def test_contract_features_must_match_catboost_model_spec(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            contract = read_json(phase16 / "categorical_feature_contract.json")
            contract["categorical_features"] = [
                item for item in contract["categorical_features"] if item["feature_name"] != "platform"
            ]
            write_json(phase16 / "categorical_feature_contract.json", contract)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                feature_availability_path=reports / "feature_availability_report.csv",
            )

        self.assertFalse(report["valid"])
        handoff = check(report, "categorical_contract_matches_catboost_handoff")
        self.assertFalse(handoff["valid"])
        self.assertEqual(handoff["observed"][0]["field"], "categorical_features")

    def test_selected_full_sample_target_encoding_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            contract = read_json(phase16 / "categorical_feature_contract.json")
            bad_feature = dict(contract["categorical_features"][-1])
            bad_feature["feature_name"] = "segment_churn_rate_full_dataset"
            bad_feature["semantic_type"] = "forbidden_full_sample_target_encoding"
            contract["categorical_features"].append(bad_feature)
            write_json(phase16 / "categorical_feature_contract.json", contract)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                feature_availability_path=reports / "feature_availability_report.csv",
            )

        self.assertFalse(report["valid"])
        leakage = check(report, "selected_categorical_features_pass_leakage_policy")
        self.assertFalse(leakage["valid"])
        self.assertEqual(leakage["observed"][0]["feature_name"], "segment_churn_rate_full_dataset")

    def test_feature_available_after_prediction_time_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            availability = read_csv(reports / "feature_availability_report.csv")
            for row in availability:
                if row["feature_name"] == "platform":
                    row["timing_allowed_by_policy"] = "False"
                    row["timing"] = "post_prediction_time"
                    row["risk_type"] = "future_behavior_leakage"
            write_csv(reports / "feature_availability_report.csv", availability)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                feature_availability_path=reports / "feature_availability_report.csv",
            )

        self.assertFalse(report["valid"])
        leakage = check(report, "selected_categorical_features_pass_leakage_policy")
        self.assertFalse(leakage["valid"])
        self.assertEqual(leakage["observed"][0]["feature_name"], "platform")
        self.assertIn("timing after prediction time", leakage["observed"][0]["reasons"])

    def test_missing_unknown_policy_blocks_contract(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            contract = read_json(phase16 / "categorical_feature_contract.json")
            del contract["categorical_features"][0]["unknown_category_policy"]
            write_json(phase16 / "categorical_feature_contract.json", contract)

            report = self.audit(
                phase16,
                upstream,
                catboost_report_path=reports / "catboost_report.json",
                feature_availability_path=reports / "feature_availability_report.csv",
            )

        self.assertFalse(report["valid"])
        handoff = check(report, "categorical_contract_matches_catboost_handoff")
        self.assertFalse(handoff["valid"])
        self.assertEqual(handoff["observed"][0]["field"], "feature policies")

    def test_cli_fail_on_warning_exits_after_writing_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "outputs"
            result = subprocess.run(
                [sys.executable, ARTIFACT, "--output-dir", output_dir, "--fail-on-warning"],
                check=False,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)
            report_exists = (output_dir / "categorical_feature_report.json").exists()
            unknowns_exists = (output_dir / "categorical_unknowns.csv").exists()

        self.assertEqual(result.returncode, 2)
        self.assertTrue(payload["audit_valid"])
        self.assertGreater(payload["warning_count"], 0)
        self.assertTrue(report_exists)
        self.assertTrue(unknowns_exists)

    def test_missing_contract_returns_structured_failure(self) -> None:
        with TemporaryDirectory() as directory:
            phase16, upstream, reports = self.copy_inputs(Path(directory))
            missing_contract = phase16 / "missing_categorical_feature_contract.json"

            report = self.audit(
                phase16,
                upstream,
                contract_path=missing_contract,
                catboost_report_path=reports / "catboost_report.json",
                feature_availability_path=reports / "feature_availability_report.csv",
            )

        self.assertFalse(report["valid"])
        self.assertEqual(report["summary"]["blocking_errors"], ["input_files_are_present"])
        self.assertEqual(report["checks"][0]["id"], "input_files_are_present")
