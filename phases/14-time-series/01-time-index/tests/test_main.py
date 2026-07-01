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

from time_index_auditor import audit_time_index  # noqa: E402


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class TimeIndexAuditorTest(TestCase):
    def audit(self, root: Path = DATA_ROOT) -> dict:
        return audit_time_index(
            metrics_path=root / "metric_observations.csv",
            calendar_path=root / "calendar.csv",
            scenario_path=root / "forecast_scenario.json",
            revisions_path=root / "data_revisions.csv",
        )

    def test_tiny_profile_is_valid_with_explicit_warnings(self) -> None:
        report = self.audit()

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(
            report["summary"]["warnings"],
            ["incomplete_rows_after_complete_through", "revisions_after_forecast_origin"],
        )
        self.assertEqual({row["segment_id"] for row in report["series"]}, {"all", "android"})
        self.assertTrue(all(row["missing_complete_dates"] == [] for row in report["series"]))

    def test_data_generator_check_rebuilds_committed_tiny_profile(self) -> None:
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

    def test_duplicate_metric_segment_date_blocks_forecast(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = read_csv(root / "metric_observations.csv")
            rows.append(rows[0].copy())
            write_csv(root / "metric_observations.csv", rows)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn("metric_segment_date_unique", report["summary"]["blocking_errors"])
        self.assertEqual(check(report, "metric_segment_date_unique")["observed"], 1)

    def test_missing_complete_date_is_blocking_even_when_later_dates_exist(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = [
                row
                for row in read_csv(root / "metric_observations.csv")
                if not (row["segment_id"] == "android" and row["observed_date"] == "2026-03-05")
            ]
            write_csv(root / "metric_observations.csv", rows)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        failure = check(report, "complete_history_has_no_missing_dates")
        self.assertEqual(failure["sample"][0]["segment_id"], "android")
        self.assertIn("2026-03-05", failure["sample"][0]["missing_dates"])

    def test_timezone_bucket_mismatch_is_reported_with_local_date(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = read_csv(root / "metric_observations.csv")
            rows[0]["period_start_at"] = "2026-03-02T21:00:00Z"
            write_csv(root / "metric_observations.csv", rows)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        failure = check(report, "timezone_bucket_matches_observed_date")
        self.assertEqual(failure["sample"][0]["observed_date"], "2026-03-02")
        self.assertEqual(failure["sample"][0]["local_date"], "2026-03-03")

    def test_complete_date_cannot_be_marked_incomplete(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = read_csv(root / "metric_observations.csv")
            for row in rows:
                if row["segment_id"] == "all" and row["observed_date"] == "2026-03-10":
                    row["is_complete_period"] = "false"
            write_csv(root / "metric_observations.csv", rows)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn("complete_dates_marked_complete", report["summary"]["blocking_errors"])

    def test_calendar_must_cover_history_and_forecast_horizon(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = [row for row in read_csv(root / "calendar.csv") if row["date"] != "2026-04-14"]
            write_csv(root / "calendar.csv", rows)

            report = self.audit(root)

        self.assertFalse(report["valid"])
        failure = check(report, "calendar_covers_history_and_horizon")
        self.assertIn("2026-04-14", failure["sample"])

    def test_late_revision_is_warning_not_blocking_by_default(self) -> None:
        report = self.audit()

        revision_check = check(report, "revisions_after_forecast_origin")
        self.assertEqual(revision_check["severity"], "warning")
        self.assertFalse(revision_check["valid"])
        self.assertTrue(report["valid"])

    def test_cli_writes_report_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "time_index_auditor.py"),
                "--metrics",
                str(DATA_ROOT / "metric_observations.csv"),
                "--calendar",
                str(DATA_ROOT / "calendar.csv"),
                "--scenario",
                str(DATA_ROOT / "forecast_scenario.json"),
                "--revisions",
                str(DATA_ROOT / "data_revisions.csv"),
                "--output",
                str(output),
            ]
            ok = subprocess.run(command, check=True, capture_output=True, text=True)
            strict = subprocess.run(
                [*command, "--fail-on-warning"],
                check=False,
                capture_output=True,
                text=True,
            )
            report_written = output.is_file()

        self.assertEqual(json.loads(ok.stdout)["valid"], True)
        self.assertTrue(report_written)
        self.assertEqual(strict.returncode, 1)

    def test_scenario_missing_required_field_is_blocking(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            scenario = json.loads((root / "forecast_scenario.json").read_text(encoding="utf-8"))
            scenario.pop("forecast_origin")
            (root / "forecast_scenario.json").write_text(
                json.dumps(scenario, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            report = self.audit(root)

        self.assertFalse(report["valid"])
        self.assertIn("scenario_required_fields", report["summary"]["blocking_errors"])
