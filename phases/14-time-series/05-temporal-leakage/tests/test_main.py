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
SOURCE_SERIES = PHASE_ROOT / "02-resampling" / "outputs" / "daily_resampled.csv"
SOURCE_FEATURES = PHASE_ROOT / "03-rolling" / "outputs" / "window_features.csv"
SOURCE_FEATURE_AUDIT = PHASE_ROOT / "03-rolling" / "outputs" / "leakage_audit.csv"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from temporal_leakage_auditor import build_temporal_leakage_package  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class TemporalLeakageAuditorTest(TestCase):
    def build(
        self,
        *,
        root: Path = DATA_ROOT,
        series_path: Path = SOURCE_SERIES,
        features_path: Path = SOURCE_FEATURES,
        feature_audit_path: Path = SOURCE_FEATURE_AUDIT,
    ) -> dict:
        return build_temporal_leakage_package(
            series_path=series_path,
            features_path=features_path,
            feature_audit_path=feature_audit_path,
            calendar_path=root / "calendar.csv",
            revisions_path=root / "data_revisions.csv",
            scenario_path=root / "forecast_scenario.json",
            spec_path=root / "temporal_leakage_spec.json",
        )

    def test_tiny_profile_builds_valid_cutoff_contract_with_expected_warnings(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(
            report["summary"]["warnings"],
            ["forbidden_feature_candidates_rejected", "revisions_after_origin_are_excluded"],
        )
        self.assertEqual(report["outputs"]["selected_features"], 4)
        self.assertEqual(report["outputs"]["rejected_feature_candidates"], 6)
        self.assertEqual(
            package["cutoff_contract"]["selected_features"],
            ["value_lag_1", "rolling_7_mean_lag1", "day_of_week", "campaign_active"],
        )

    def test_data_generator_check_rebuilds_committed_temporal_leakage_spec(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(PHASE_ROOT / "data" / "generate_data.py"),
                "--check",
                "--output",
                str(DATA_ROOT),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("reproducible", result.stdout)

    def test_cutoff_contract_fixes_origin_embargo_and_horizon(self) -> None:
        contract = self.build()["cutoff_contract"]

        self.assertEqual(contract["training_end"], "2026-03-16")
        self.assertEqual(contract["first_forecast_date"], "2026-03-18")
        self.assertEqual(contract["embargo_dates"], ["2026-03-17"])
        self.assertEqual(contract["horizon_end"], "2026-04-14")
        self.assertEqual(contract["split_type"], "time_ordered_cutoff")

    def test_forbidden_feature_report_allows_only_cutoff_safe_selected_features(self) -> None:
        rows = {row["feature_name"]: row for row in self.build()["forbidden_feature_rows"]}

        self.assertEqual(rows["value_lag_1"]["decision"], "allow")
        self.assertEqual(rows["rolling_7_mean_lag1"]["evidence_status"], "past_only_audit_passed")
        self.assertEqual(rows["day_of_week"]["evidence_status"], "known_before_origin")
        self.assertEqual(rows["current_value"]["decision"], "reject")
        self.assertEqual(rows["random_split_fold"]["availability_type"], "random_split")
        self.assertEqual(rows["revised_value_after_origin"]["decision"], "reject")

    def test_selected_target_at_feature_date_blocks_audit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "temporal_leakage_spec.json")
            for feature in spec["candidate_features"]:
                if feature["name"] == "current_value":
                    feature["selected"] = True
            write_json(root / "temporal_leakage_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("selected_features_do_not_use_forbidden_availability", report["summary"]["blocking_errors"])

    def test_random_split_plan_blocks_audit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "temporal_leakage_spec.json")
            spec["split_plan"]["split_type"] = "random"
            write_json(root / "temporal_leakage_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("split_plan_is_time_ordered", report["summary"]["blocking_errors"])

    def test_training_end_must_match_complete_through(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "temporal_leakage_spec.json")
            spec["split_plan"]["training_end"] = "2026-03-17"
            write_json(root / "temporal_leakage_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("training_end_matches_complete_through", report["summary"]["blocking_errors"])

    def test_training_rows_after_cutoff_and_embargo_rows_block_audit(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            for row in rows:
                if row["observed_date"] == "2026-03-17":
                    row["include_in_training"] = "true"
            write_csv(series_path, rows)

            report = self.build(series_path=series_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("training_rows_end_at_complete_through", report["summary"]["blocking_errors"])
        self.assertIn("embargo_dates_are_not_training_rows", report["summary"]["blocking_errors"])

    def test_window_feature_audit_must_prove_past_only_sources(self) -> None:
        with TemporaryDirectory() as directory:
            audit_path = Path(directory) / "leakage_audit.csv"
            rows = read_csv(SOURCE_FEATURE_AUDIT)
            for row in rows:
                if row["feature_name"] == "rolling_7_mean_lag1" and row["feature_date"] == "2026-03-12":
                    row["latest_source_date_used"] = "2026-03-12"
                    row["valid"] = "false"
                    break
            write_csv(audit_path, rows)

            report = self.build(feature_audit_path=audit_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("window_features_have_past_only_audit", report["summary"]["blocking_errors"])

    def test_known_future_calendar_feature_must_be_known_before_origin(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = read_csv(root / "calendar.csv")
            for row in rows:
                if row["date"] == "2026-03-20":
                    row["known_before_date"] = "2026-03-19"
            write_csv(root / "calendar.csv", rows)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        failure = check(report, "known_future_features_known_before_origin")
        self.assertEqual(failure["sample"][0]["feature_name"], "campaign_active")

    def test_missing_selected_feature_column_blocks_audit(self) -> None:
        with TemporaryDirectory() as directory:
            features_path = Path(directory) / "window_features.csv"
            rows = read_csv(SOURCE_FEATURES)
            for row in rows:
                row.pop("rolling_7_mean_lag1")
            write_csv(features_path, rows)

            report = self.build(features_path=features_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("selected_features_are_available_at_cutoff", report["summary"]["blocking_errors"])

    def test_scenario_and_spec_must_align(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            scenario = read_json(root / "forecast_scenario.json")
            scenario["frequency"] = "W"
            write_json(root / "forecast_scenario.json", scenario)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("scenario_and_leakage_spec_align", report["summary"]["blocking_errors"])

    def test_revision_policy_must_exclude_revisions_after_origin(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "temporal_leakage_spec.json")
            spec["revision_policy"] = "use_latest_revision"
            write_json(root / "temporal_leakage_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("revision_policy_excludes_after_origin", report["summary"]["blocking_errors"])

    def test_cli_writes_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "temporal_leakage_auditor.py"),
                "--series",
                str(SOURCE_SERIES),
                "--features",
                str(SOURCE_FEATURES),
                "--feature-audit",
                str(SOURCE_FEATURE_AUDIT),
                "--calendar",
                str(DATA_ROOT / "calendar.csv"),
                "--revisions",
                str(DATA_ROOT / "data_revisions.csv"),
                "--scenario",
                str(DATA_ROOT / "forecast_scenario.json"),
                "--spec",
                str(DATA_ROOT / "temporal_leakage_spec.json"),
                "--output-dir",
                str(output_dir),
            ]
            ok = subprocess.run(command, check=True, capture_output=True, text=True)
            strict = subprocess.run([*command, "--fail-on-warning"], check=False, capture_output=True, text=True)
            written_files = sorted(path.name for path in output_dir.iterdir())

        self.assertTrue(json.loads(ok.stdout)["valid"])
        self.assertEqual(strict.returncode, 1)
        self.assertEqual(
            written_files,
            ["cutoff_contract.json", "forbidden_feature_report.csv", "temporal_leakage_report.json"],
        )
