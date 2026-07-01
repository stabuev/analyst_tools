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
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from resampling_pipeline import build_resampling_package  # noqa: E402


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


class ResamplingPipelineTest(TestCase):
    def build(self, root: Path = DATA_ROOT) -> dict:
        return build_resampling_package(
            events_path=root / "subscription_events.csv",
            metrics_path=root / "metric_observations.csv",
            calendar_path=root / "calendar.csv",
            scenario_path=root / "forecast_scenario.json",
            spec_path=root / "resampling_spec.json",
        )

    def test_tiny_profile_resamples_and_reconciles_with_explicit_warnings(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(
            report["summary"]["warnings"],
            ["partial_daily_rows_excluded_from_training", "incomplete_weeks_excluded_from_training"],
        )
        self.assertEqual(report["outputs"]["daily_rows"], 32)
        self.assertEqual(report["outputs"]["weekly_rows"], 6)
        self.assertEqual(report["outputs"]["training_daily_rows"], 30)
        self.assertEqual(report["outputs"]["training_weekly_rows"], 4)
        self.assertTrue(all(row["difference"] == 0 for row in package["reconciliation_rows"]))

    def test_data_generator_check_rebuilds_committed_resampling_inputs(self) -> None:
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

    def test_timezone_normalization_buckets_utc_previous_day_into_business_date(self) -> None:
        package = self.build()
        timezone_check = check(package["report"], "timezone_normalized_business_date")

        self.assertTrue(timezone_check["valid"])
        self.assertEqual(timezone_check["sample"][0]["utc_date"], "2026-03-01")
        self.assertEqual(timezone_check["sample"][0]["business_date"], "2026-03-02")
        first_daily = package["daily_rows"][0]
        self.assertEqual(first_daily["observed_date"], "2026-03-02")
        self.assertEqual(first_daily["value"], 998)

    def test_duplicate_event_id_blocks_resampling(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = read_csv(root / "subscription_events.csv")
            rows[1]["event_id"] = rows[0]["event_id"]
            write_csv(root / "subscription_events.csv", rows)

            report = self.build(root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("event_id_unique", report["summary"]["blocking_errors"])

    def test_missing_resampling_spec_field_is_blocking(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "resampling_spec.json")
            spec.pop("opening_balances")
            write_json(root / "resampling_spec.json", spec)

            report = self.build(root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("resampling_spec_required_fields", report["summary"]["blocking_errors"])

    def test_weekly_label_and_closed_policy_are_enforced(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "resampling_spec.json")
            spec["weekly_label"] = "right"
            write_json(root / "resampling_spec.json", spec)

            report = self.build(root)["report"]

        self.assertFalse(report["valid"])
        failure = check(report, "resampling_policies_supported")
        self.assertEqual(failure["sample"][0]["field"], "weekly_label")

    def test_published_metric_mismatch_blocks_complete_period_reconciliation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = read_csv(root / "metric_observations.csv")
            for row in rows:
                if row["segment_id"] == "all" and row["observed_date"] == "2026-03-12":
                    row["value"] = str(int(row["value"]) + 5)
            write_csv(root / "metric_observations.csv", rows)

            report = self.build(root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("published_series_reconciles", report["summary"]["blocking_errors"])
        failure = check(report, "published_series_reconciles")
        self.assertEqual(failure["sample"][0]["difference"], -5)

    def test_complete_event_available_after_origin_blocks_training(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = read_csv(root / "subscription_events.csv")
            for row in rows:
                if row["segment_id"] == "android" and row["event_id"].endswith("2026-03-10"):
                    row["available_at"] = "2026-03-19T10:00:00+03:00"
            write_csv(root / "subscription_events.csv", rows)

            report = self.build(root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("complete_events_available_by_origin", report["summary"]["blocking_errors"])

    def test_partial_daily_and_weekly_rows_are_visible_but_not_training_rows(self) -> None:
        package = self.build()
        partial_daily = [row for row in package["daily_rows"] if row["observed_date"] == "2026-03-17"]
        partial_weekly = [row for row in package["weekly_rows"] if row["week_start"] == "2026-03-16"]

        self.assertEqual(len(partial_daily), 2)
        self.assertTrue(all(row["include_in_training"] == "false" for row in partial_daily))
        self.assertEqual(len(partial_weekly), 2)
        self.assertTrue(all(row["is_complete_week"] == "false" for row in partial_weekly))

    def test_missing_calendar_date_blocks_resampling_window(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = [row for row in read_csv(root / "calendar.csv") if row["date"] != "2026-03-10"]
            write_csv(root / "calendar.csv", rows)

            report = self.build(root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("calendar_dates_cover_resampling_window", report["summary"]["blocking_errors"])

    def test_cli_writes_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "resampling_pipeline.py"),
                "--events",
                str(DATA_ROOT / "subscription_events.csv"),
                "--metrics",
                str(DATA_ROOT / "metric_observations.csv"),
                "--calendar",
                str(DATA_ROOT / "calendar.csv"),
                "--scenario",
                str(DATA_ROOT / "forecast_scenario.json"),
                "--spec",
                str(DATA_ROOT / "resampling_spec.json"),
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
            ["daily_resampled.csv", "reconciliation.csv", "resampling_report.json", "weekly_resampled.csv"],
        )
