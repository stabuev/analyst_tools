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

from seasonality_profiler import build_seasonality_profile_package  # noqa: E402


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


def row_for(rows: list[dict], **criteria: str) -> dict:
    return next(row for row in rows if all(row[key] == value for key, value in criteria.items()))


class SeasonalityProfilerTest(TestCase):
    def build(self, series_path: Path = SOURCE_SERIES, root: Path = DATA_ROOT) -> dict:
        return build_seasonality_profile_package(
            series_path=series_path,
            calendar_path=root / "calendar.csv",
            campaign_path=root / "campaign_calendar.csv",
            release_path=root / "release_calendar.csv",
            scenario_path=root / "forecast_scenario.json",
            spec_path=root / "seasonality_profile_spec.json",
        )

    def test_tiny_profile_builds_trend_seasonality_and_calendar_inventory(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "partial_rows_excluded_from_profiles",
                "future_calendar_effect_has_no_training_examples",
                "monthly_profile_has_single_cycle",
            ],
        )
        self.assertEqual(report["outputs"]["trend_rows"], 2)
        self.assertEqual(report["outputs"]["seasonality_rows"], 16)
        self.assertEqual(report["outputs"]["calendar_effect_rows"], 4)
        self.assertEqual(report["outputs"]["known_future_effect_rows"], 1)

    def test_data_generator_check_rebuilds_committed_seasonality_spec(self) -> None:
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

    def test_manual_weekly_profile_matches_hand_calculation(self) -> None:
        package = self.build()
        monday = row_for(
            package["seasonality_rows"],
            segment_id="all",
            seasonality_type="day_of_week",
            seasonal_key="Monday",
        )
        saturday = row_for(
            package["seasonality_rows"],
            segment_id="all",
            seasonality_type="day_of_week",
            seasonal_key="Saturday",
        )

        self.assertEqual(monday["observations"], 3)
        self.assertEqual(monday["mean_value"], "1065")
        self.assertEqual(monday["seasonal_index"], "10.666667")
        self.assertEqual(saturday["mean_value"], "1034.5")
        self.assertEqual(saturday["seasonal_index"], "-19.833333")
        self.assertEqual(saturday["enough_history"], "true")

    def test_trend_summary_uses_complete_history_only(self) -> None:
        package = self.build()
        all_trend = row_for(package["trend_rows"], segment_id="all")
        android_trend = row_for(package["trend_rows"], segment_id="android")

        self.assertEqual(all_trend["first_observed_date"], "2026-03-02")
        self.assertEqual(all_trend["last_observed_date"], "2026-03-16")
        self.assertEqual(all_trend["first_last_change_per_day"], "9")
        self.assertEqual(all_trend["trend_direction"], "up")
        self.assertEqual(android_trend["first_last_change_per_day"], "4")

    def test_calendar_inventory_marks_future_campaign_without_history(self) -> None:
        package = self.build()
        campaign = row_for(package["calendar_effect_rows"], effect_type="campaign")

        self.assertEqual(campaign["effect_id"], "spring-marketplace-push")
        self.assertEqual(campaign["segment_id"], "all")
        self.assertEqual(campaign["future_horizon_days"], 8)
        self.assertEqual(campaign["observed_training_days"], 0)
        self.assertEqual(campaign["known_before_origin"], "true")
        self.assertEqual(campaign["status"], "known_future_effect_without_training_examples")

    def test_release_lift_is_segment_specific(self) -> None:
        package = self.build()
        release = row_for(package["calendar_effect_rows"], effect_type="release")

        self.assertEqual(release["segment_id"], "android")
        self.assertEqual(release["observed_training_days"], 3)
        self.assertEqual(release["baseline_mean"], "326")
        self.assertEqual(release["observed_mean"], "354")
        self.assertEqual(release["effect_lift_vs_seasonal_profile"], "28")

    def test_missing_calendar_date_blocks_profile(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = [row for row in read_csv(root / "calendar.csv") if row["date"] != "2026-04-14"]
            write_csv(root / "calendar.csv", rows)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("calendar_covers_history_and_horizon", report["summary"]["blocking_errors"])

    def test_duplicate_source_segment_date_blocks_profile(self) -> None:
        with TemporaryDirectory() as directory:
            series = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            rows.append(rows[0].copy())
            write_csv(series, rows)

            report = self.build(series_path=series)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("source_segment_date_unique", report["summary"]["blocking_errors"])

    def test_campaign_calendar_flag_must_cover_declared_event_range(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = read_csv(root / "calendar.csv")
            for row in rows:
                if row["date"] == "2026-03-20":
                    row["campaign_active"] = "false"
            write_csv(root / "calendar.csv", rows)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("calendar_flags_cover_declared_events", report["summary"]["blocking_errors"])

    def test_calendar_effect_must_be_known_before_forecast_origin(self) -> None:
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
        failure = check(report, "calendar_effects_known_before_origin")
        self.assertEqual(failure["sample"][0]["date"], "2026-03-20")

    def test_scenario_and_spec_must_align(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            scenario = read_json(root / "forecast_scenario.json")
            scenario["frequency"] = "W"
            write_json(root / "forecast_scenario.json", scenario)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("scenario_and_seasonality_spec_align", report["summary"]["blocking_errors"])

    def test_missing_source_column_blocks_profile(self) -> None:
        with TemporaryDirectory() as directory:
            series = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            for row in rows:
                row.pop("value")
            write_csv(series, rows)

            report = self.build(series_path=series)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("source_columns_present", report["summary"]["blocking_errors"])

    def test_cli_writes_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "seasonality_profiler.py"),
                "--series",
                str(SOURCE_SERIES),
                "--calendar",
                str(DATA_ROOT / "calendar.csv"),
                "--campaign-calendar",
                str(DATA_ROOT / "campaign_calendar.csv"),
                "--release-calendar",
                str(DATA_ROOT / "release_calendar.csv"),
                "--scenario",
                str(DATA_ROOT / "forecast_scenario.json"),
                "--spec",
                str(DATA_ROOT / "seasonality_profile_spec.json"),
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
            [
                "calendar_effect_inventory.csv",
                "seasonality_profile.csv",
                "seasonality_report.json",
                "trend_summary.csv",
            ],
        )
