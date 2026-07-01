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
CUTOFF_CONTRACT = PHASE_ROOT / "05-temporal-leakage" / "outputs" / "cutoff_contract.json"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from baseline_forecaster import build_baseline_forecast_package  # noqa: E402


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


def row_for(rows: list[dict[str, str]], **criteria: str) -> dict[str, str]:
    return next(row for row in rows if all(row[key] == value for key, value in criteria.items()))


class BaselineForecasterTest(TestCase):
    def build(
        self,
        *,
        root: Path = DATA_ROOT,
        series_path: Path = SOURCE_SERIES,
        cutoff_contract_path: Path = CUTOFF_CONTRACT,
    ) -> dict:
        return build_baseline_forecast_package(
            series_path=series_path,
            calendar_path=root / "calendar.csv",
            scenario_path=root / "forecast_scenario.json",
            cutoff_contract_path=cutoff_contract_path,
            spec_path=root / "baseline_forecast_spec.json",
        )

    def test_tiny_profile_builds_all_baselines_with_expected_warnings(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(
            report["summary"]["warnings"],
            ["known_future_calendar_effects_not_modeled", "embargo_gap_skipped_before_forecast"],
        )
        self.assertEqual(report["outputs"]["forecast_rows"], 224)
        self.assertEqual(report["outputs"]["trace_rows"], 8)
        self.assertEqual(report["outputs"]["primary_baseline_model"], "seasonal_naive_7")

    def test_data_generator_check_rebuilds_committed_baseline_spec(self) -> None:
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

    def test_manual_first_horizon_forecasts_match_tiny_calculations(self) -> None:
        rows = self.build()["forecast_rows"]

        self.assertEqual(row_for(rows, segment_id="all", model_id="naive", forecast_date="2026-03-18")["forecast_value"], "1124")
        self.assertEqual(row_for(rows, segment_id="all", model_id="seasonal_naive_7", forecast_date="2026-03-18")["forecast_value"], "1091")
        self.assertEqual(row_for(rows, segment_id="all", model_id="drift", forecast_date="2026-03-18")["forecast_value"], "1142")
        self.assertEqual(row_for(rows, segment_id="all", model_id="moving_average_7", forecast_date="2026-03-18")["forecast_value"], "1092.428571")
        self.assertEqual(row_for(rows, segment_id="android", model_id="seasonal_naive_7", forecast_date="2026-03-18")["forecast_value"], "354")
        self.assertEqual(row_for(rows, segment_id="android", model_id="drift", forecast_date="2026-03-18")["forecast_value"], "382")

    def test_seasonal_naive_skips_embargo_day_as_anchor(self) -> None:
        rows = self.build()["forecast_rows"]
        tuesday = row_for(rows, segment_id="all", model_id="seasonal_naive_7", forecast_date="2026-03-24")

        self.assertEqual(tuesday["forecast_value"], "1082")
        self.assertEqual(tuesday["anchor_dates"], "2026-03-10")
        self.assertNotIn("2026-03-17", tuesday["anchor_dates"])

    def test_trace_rows_explain_policy_and_primary_baseline(self) -> None:
        trace = self.build()["trace_rows"]
        seasonal = row_for(trace, segment_id="all", model_id="seasonal_naive_7")
        drift = row_for(trace, segment_id="android", model_id="drift")

        self.assertEqual(seasonal["primary_baseline"], "true")
        self.assertEqual(seasonal["seasonal_period_days"], "7")
        self.assertEqual(seasonal["anchor_dates"], "2026-03-10;2026-03-11;2026-03-12;2026-03-13;2026-03-14;2026-03-15;2026-03-16")
        self.assertEqual(drift["drift_per_day"], "4")

    def test_missing_required_baseline_model_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "baseline_forecast_spec.json")
            spec["models"] = [model for model in spec["models"] if model["model_id"] != "seasonal_naive_7"]
            write_json(root / "baseline_forecast_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("baseline_models_declared", report["summary"]["blocking_errors"])

    def test_seasonal_period_is_precommitted_to_weekly_cycle(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "baseline_forecast_spec.json")
            spec["seasonal_period_days"] = 14
            write_json(root / "baseline_forecast_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("seasonal_period_is_precommitted", report["summary"]["blocking_errors"])

    def test_primary_baseline_must_be_seasonal_naive(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "baseline_forecast_spec.json")
            spec["primary_baseline_model"] = "naive"
            write_json(root / "baseline_forecast_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("primary_baseline_declared", report["summary"]["blocking_errors"])

    def test_training_rows_after_cutoff_and_embargo_rows_block_report(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            for row in rows:
                if row["observed_date"] == "2026-03-17":
                    row["include_in_training"] = "true"
            write_csv(series_path, rows)

            report = self.build(series_path=series_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("no_training_rows_after_cutoff", report["summary"]["blocking_errors"])
        self.assertIn("embargo_dates_are_not_training_rows", report["summary"]["blocking_errors"])

    def test_duplicate_source_segment_date_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            rows.append(rows[0].copy())
            write_csv(series_path, rows)

            report = self.build(series_path=series_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("source_segment_date_unique", report["summary"]["blocking_errors"])

    def test_missing_calendar_horizon_date_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            rows = [row for row in read_csv(root / "calendar.csv") if row["date"] != "2026-04-14"]
            write_csv(root / "calendar.csv", rows)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("calendar_covers_forecast_horizon", report["summary"]["blocking_errors"])

    def test_cutoff_contract_must_align_with_baseline_spec(self) -> None:
        with TemporaryDirectory() as directory:
            cutoff_path = Path(directory) / "cutoff_contract.json"
            cutoff = read_json(CUTOFF_CONTRACT)
            cutoff["training_end"] = "2026-03-15"
            write_json(cutoff_path, cutoff)

            report = self.build(cutoff_contract_path=cutoff_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("scenario_cutoff_and_baseline_spec_align", report["summary"]["blocking_errors"])

    def test_horizon_mismatch_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "baseline_forecast_spec.json")
            spec["horizon_end"] = "2026-04-13"
            write_json(root / "baseline_forecast_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("scenario_cutoff_and_baseline_spec_align", report["summary"]["blocking_errors"])
        self.assertIn("forecast_horizon_matches_contract", report["summary"]["blocking_errors"])

    def test_minimum_history_policy_blocks_overdemanding_model(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "baseline_forecast_spec.json")
            for model in spec["models"]:
                if model["model_id"] == "moving_average_7":
                    model["minimum_training_points"] = 30
            write_json(root / "baseline_forecast_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("enough_history_for_declared_models", report["summary"]["blocking_errors"])

    def test_cli_writes_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "baseline_forecaster.py"),
                "--series",
                str(SOURCE_SERIES),
                "--calendar",
                str(DATA_ROOT / "calendar.csv"),
                "--scenario",
                str(DATA_ROOT / "forecast_scenario.json"),
                "--cutoff-contract",
                str(CUTOFF_CONTRACT),
                "--spec",
                str(DATA_ROOT / "baseline_forecast_spec.json"),
                "--output-dir",
                str(output_dir),
            ]
            ok = subprocess.run(command, check=True, capture_output=True, text=True)
            strict = subprocess.run([*command, "--fail-on-warning"], check=False, capture_output=True, text=True)
            written_files = sorted(path.name for path in output_dir.iterdir())

        self.assertTrue(json.loads(ok.stdout)["valid"])
        self.assertEqual(strict.returncode, 1)
        self.assertEqual(written_files, ["baseline_forecasts.csv", "baseline_report.json", "baseline_trace.csv"])
