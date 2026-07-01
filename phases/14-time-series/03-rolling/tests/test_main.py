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
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from window_feature_builder import build_window_feature_package  # noqa: E402


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


def row_for(rows: list[dict], segment_id: str, observed_date: str) -> dict:
    return next(row for row in rows if row["segment_id"] == segment_id and row["observed_date"] == observed_date)


class WindowFeatureBuilderTest(TestCase):
    def build(self, series_path: Path = SOURCE_SERIES, root: Path = DATA_ROOT) -> dict:
        return build_window_feature_package(
            series_path=series_path,
            scenario_path=root / "forecast_scenario.json",
            spec_path=root / "window_feature_spec.json",
        )

    def test_tiny_profile_builds_features_with_explicit_warnings(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(
            report["summary"]["warnings"],
            ["warmup_rows_excluded_from_training", "partial_source_rows_excluded_from_training"],
        )
        self.assertEqual(report["outputs"]["feature_rows"], 32)
        self.assertEqual(report["outputs"]["training_feature_rows"], 16)
        self.assertEqual(report["outputs"]["warmup_rows"], 14)
        self.assertEqual(report["outputs"]["partial_rows"], 2)

    def test_data_generator_check_rebuilds_committed_window_spec(self) -> None:
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

    def test_manual_rolling_values_use_only_previous_dates(self) -> None:
        package = self.build()
        all_monday = row_for(package["feature_rows"], "all", "2026-03-09")
        audit_row = next(
            row
            for row in package["leakage_audit_rows"]
            if row["segment_id"] == "all"
            and row["feature_date"] == "2026-03-09"
            and row["feature_name"] == "rolling_7_mean_lag1"
        )

        self.assertEqual(all_monday["value_lag_1"], "1012")
        self.assertEqual(all_monday["delta_lag_1"], "9")
        self.assertEqual(all_monday["rolling_3_mean_lag1"], "1016.333333")
        self.assertEqual(all_monday["rolling_7_mean_lag1"], "1013.571429")
        self.assertEqual(all_monday["include_in_training"], "true")
        self.assertEqual(audit_row["latest_source_date_used"], "2026-03-08")
        self.assertEqual(audit_row["valid"], "true")

    def test_first_training_date_requires_full_required_history(self) -> None:
        report = self.build()["report"]

        self.assertEqual(
            {row["segment_id"]: row["first_training_date"] for row in report["series"]},
            {"all": "2026-03-09", "android": "2026-03-09"},
        )

    def test_partial_source_row_is_visible_but_not_used_for_training(self) -> None:
        package = self.build()
        all_partial = row_for(package["feature_rows"], "all", "2026-03-17")
        warning = check(package["report"], "partial_source_rows_excluded_from_training")

        self.assertEqual(all_partial["source_is_complete"], "false")
        self.assertEqual(all_partial["feature_complete"], "true")
        self.assertEqual(all_partial["include_in_training"], "false")
        self.assertEqual(warning["severity"], "warning")

    def test_duplicate_source_segment_date_blocks_feature_building(self) -> None:
        with TemporaryDirectory() as directory:
            series = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            rows.append(rows[0].copy())
            write_csv(series, rows)

            report = self.build(series_path=series)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("source_segment_date_unique", report["summary"]["blocking_errors"])

    def test_missing_complete_date_blocks_feature_building(self) -> None:
        with TemporaryDirectory() as directory:
            series = Path(directory) / "daily_resampled.csv"
            rows = [
                row
                for row in read_csv(SOURCE_SERIES)
                if not (row["segment_id"] == "android" and row["observed_date"] == "2026-03-05")
            ]
            write_csv(series, rows)

            report = self.build(series_path=series)["report"]

        self.assertFalse(report["valid"])
        failure = check(report, "complete_history_has_no_missing_dates")
        self.assertEqual(failure["sample"][0]["segment_id"], "android")
        self.assertIn("2026-03-05", failure["sample"][0]["missing_dates"])

    def test_lag_zero_rule_is_rejected_as_temporal_leakage(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "window_feature_spec.json")
            spec["rules"][0]["lag"] = 0
            write_json(root / "window_feature_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("feature_rules_are_past_only", report["summary"]["blocking_errors"])
        failure = check(report, "feature_rules_are_past_only")
        self.assertEqual(failure["sample"][0]["field"], "lag")

    def test_centered_rolling_rule_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "window_feature_spec.json")
            spec["rules"][2]["center"] = True
            write_json(root / "window_feature_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("feature_rules_are_past_only", report["summary"]["blocking_errors"])

    def test_missing_feature_input_column_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            series = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            for row in rows:
                row.pop("delta_active")
            write_csv(series, rows)

            report = self.build(series_path=series)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("source_columns_present", report["summary"]["blocking_errors"])

    def test_scenario_and_window_spec_must_align(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            scenario = read_json(root / "forecast_scenario.json")
            scenario["frequency"] = "W"
            write_json(root / "forecast_scenario.json", scenario)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("scenario_and_window_spec_align", report["summary"]["blocking_errors"])

    def test_cli_writes_feature_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "window_feature_builder.py"),
                "--series",
                str(SOURCE_SERIES),
                "--scenario",
                str(DATA_ROOT / "forecast_scenario.json"),
                "--spec",
                str(DATA_ROOT / "window_feature_spec.json"),
                "--output-dir",
                str(output_dir),
            ]
            ok = subprocess.run(command, check=True, capture_output=True, text=True)
            strict = subprocess.run([*command, "--fail-on-warning"], check=False, capture_output=True, text=True)
            written_files = sorted(path.name for path in output_dir.iterdir())

        self.assertTrue(json.loads(ok.stdout)["valid"])
        self.assertEqual(strict.returncode, 1)
        self.assertEqual(written_files, ["leakage_audit.csv", "window_feature_report.json", "window_features.csv"])
