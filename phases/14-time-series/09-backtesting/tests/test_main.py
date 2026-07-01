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
MODEL_REPORT = PHASE_ROOT / "08-ets-and-arima" / "outputs" / "model_report.json"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from rolling_backtester import build_backtest_package  # noqa: E402


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


class RollingBacktesterTest(TestCase):
    def build(
        self,
        *,
        root: Path = DATA_ROOT,
        series_path: Path | None = None,
        model_report_path: Path = MODEL_REPORT,
    ) -> dict:
        return build_backtest_package(
            series_path=series_path or root / "backtest_observations.csv",
            scenario_path=root / "forecast_scenario.json",
            model_spec_path=root / "statsmodels_model_spec.json",
            model_report_path=model_report_path,
            spec_path=root / "backtesting_spec.json",
        )

    def test_tiny_profile_builds_rolling_origin_backtest_with_expected_warnings(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(
            report["summary"]["warnings"],
            ["small_origin_count_blocks_model_selection_claim", "backtest_horizon_shorter_than_final_forecast_horizon"],
        )
        self.assertEqual(report["outputs"]["split_rows"], 4)
        self.assertEqual(report["outputs"]["forecast_rows"], 72)
        self.assertEqual(report["outputs"]["error_rows"], 72)
        self.assertEqual(report["outputs"]["origins"], 4)
        self.assertEqual(report["outputs"]["segments"], ["all", "android"])
        self.assertEqual(
            report["outputs"]["models"],
            ["seasonal_naive_7", "ets_additive_trend_seasonal_7", "arima_1_1_0"],
        )

    def test_data_generator_check_rebuilds_committed_backtesting_spec(self) -> None:
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

    def test_split_manifest_declares_expanding_rolling_origins_and_gap(self) -> None:
        rows = self.build()["split_rows"]

        self.assertEqual([row["window_type"] for row in rows], ["expanding", "expanding", "rolling", "rolling"])
        self.assertEqual([row["origin_index"] for row in rows], [1, 2, 3, 4])
        first = rows[0]
        rolling = rows[2]
        self.assertEqual(first["forecast_origin"], "2026-02-24T09:00:00+03:00")
        self.assertEqual(first["training_start"], "2026-02-02")
        self.assertEqual(first["training_end"], "2026-02-22")
        self.assertEqual(first["embargo_dates"], "2026-02-23")
        self.assertEqual(first["first_forecast_date"], "2026-02-24")
        self.assertEqual(first["horizon_end"], "2026-02-26")
        self.assertEqual(first["horizon_days"], 3)
        self.assertEqual(rolling["training_start"], "2026-02-16")
        self.assertEqual(rolling["training_points"], 21)
        self.assertEqual(rolling["retraining_policy"], "refit_each_origin")

    def test_forecasts_skip_embargo_and_match_manual_baseline_values(self) -> None:
        rows = self.build()["forecast_rows"]
        all_first = row_for(
            rows,
            split_id="bt-expanding-2026-02-24",
            segment_id="all",
            model_id="seasonal_naive_7",
            forecast_date="2026-02-24",
        )
        android_first = row_for(
            rows,
            split_id="bt-expanding-2026-02-24",
            segment_id="android",
            model_id="seasonal_naive_7",
            forecast_date="2026-02-24",
        )

        self.assertEqual(all_first["forecast_value"], "881")
        self.assertEqual(all_first["anchor_dates"], "2026-02-17")
        self.assertEqual(all_first["raw_step"], 2)
        self.assertEqual(android_first["forecast_value"], "266")
        self.assertEqual(android_first["anchor_dates"], "2026-02-17")
        self.assertTrue(all(row["forecast_date"] != "2026-02-23" for row in rows))

    def test_candidate_forecasts_match_locked_values(self) -> None:
        rows = self.build()["forecast_rows"]

        self.assertEqual(
            row_for(
                rows,
                split_id="bt-expanding-2026-02-24",
                segment_id="all",
                model_id="ets_additive_trend_seasonal_7",
                forecast_date="2026-02-24",
            )["forecast_value"],
            "944.000002",
        )
        self.assertEqual(
            row_for(
                rows,
                split_id="bt-expanding-2026-02-24",
                segment_id="all",
                model_id="arima_1_1_0",
                forecast_date="2026-02-24",
            )["forecast_value"],
            "886.913429",
        )
        self.assertEqual(
            row_for(
                rows,
                split_id="bt-rolling-2026-03-14",
                segment_id="android",
                model_id="ets_additive_trend_seasonal_7",
                forecast_date="2026-03-16",
            )["forecast_value"],
            "374.000003",
        )
        self.assertEqual(
            row_for(
                rows,
                split_id="bt-rolling-2026-03-14",
                segment_id="android",
                model_id="arima_1_1_0",
                forecast_date="2026-03-16",
            )["forecast_value"],
            "358.892166",
        )

    def test_raw_error_rows_include_actual_error_abs_and_squared_error(self) -> None:
        errors = self.build()["error_rows"]
        baseline = row_for(
            errors,
            split_id="bt-expanding-2026-02-24",
            segment_id="all",
            model_id="seasonal_naive_7",
            forecast_date="2026-02-24",
        )
        arima = row_for(
            errors,
            split_id="bt-expanding-2026-02-24",
            segment_id="android",
            model_id="arima_1_1_0",
            forecast_date="2026-02-26",
        )

        self.assertEqual(baseline["actual_value"], "944")
        self.assertEqual(baseline["error"], "63")
        self.assertEqual(baseline["absolute_error"], "63")
        self.assertEqual(baseline["squared_error"], "3969")
        self.assertEqual(arima["actual_value"], "302")
        self.assertEqual(arima["error"], "32.535003")
        self.assertEqual(arima["squared_error"], "1058.52642")

    def test_random_split_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "backtesting_spec.json")
            spec["split_plan"][0]["window_type"] = "random"
            write_json(root / "backtesting_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("no_random_splits", report["summary"]["blocking_errors"])
        self.assertIn("split_plan_valid", report["summary"]["blocking_errors"])

    def test_horizon_mismatch_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "backtesting_spec.json")
            spec["split_plan"][0]["horizon_end"] = "2026-02-25"
            write_json(root / "backtesting_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("forecast_horizon_is_fixed", report["summary"]["blocking_errors"])

    def test_embargo_gap_mismatch_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "backtesting_spec.json")
            spec["split_plan"][0]["embargo_dates"] = []
            write_json(root / "backtesting_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("embargo_gap_is_respected", report["summary"]["blocking_errors"])

    def test_missing_actual_blocks_backtest_outputs(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "backtest_observations.csv"
            rows = [
                row
                for row in read_csv(DATA_ROOT / "backtest_observations.csv")
                if not (row["segment_id"] == "all" and row["observed_date"] == "2026-02-24")
            ]
            write_csv(series_path, rows)

            report = self.build(series_path=series_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("actuals_available_for_every_origin_horizon", report["summary"]["blocking_errors"])

    def test_duplicate_source_segment_date_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "backtest_observations.csv"
            rows = read_csv(DATA_ROOT / "backtest_observations.csv")
            rows.append(rows[0].copy())
            write_csv(series_path, rows)

            report = self.build(series_path=series_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("source_segment_date_unique", report["summary"]["blocking_errors"])

    def test_invalid_upstream_model_report_blocks_backtest(self) -> None:
        with TemporaryDirectory() as directory:
            model_report_path = Path(directory) / "model_report.json"
            report = read_json(MODEL_REPORT)
            report["valid"] = False
            write_json(model_report_path, report)

            result = self.build(model_report_path=model_report_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("scenario_model_and_backtest_spec_align", result["summary"]["blocking_errors"])

    def test_retraining_policy_must_refit_each_origin(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "backtesting_spec.json")
            spec["retraining_policy"]["refit_each_origin"] = False
            spec["retraining_policy"]["reuse_final_forecast_fit"] = True
            write_json(root / "backtesting_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("models_refit_each_origin", report["summary"]["blocking_errors"])

    def test_cli_writes_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "rolling_backtester.py"),
                "--series",
                str(DATA_ROOT / "backtest_observations.csv"),
                "--scenario",
                str(DATA_ROOT / "forecast_scenario.json"),
                "--model-spec",
                str(DATA_ROOT / "statsmodels_model_spec.json"),
                "--model-report",
                str(MODEL_REPORT),
                "--spec",
                str(DATA_ROOT / "backtesting_spec.json"),
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
            ["backtest_errors.csv", "backtest_forecasts.csv", "backtest_report.json", "split_manifest.csv"],
        )
