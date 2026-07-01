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
BASELINE_REPORT = PHASE_ROOT / "06-forecast-baselines" / "outputs" / "baseline_report.json"
BASELINE_FORECASTS = PHASE_ROOT / "06-forecast-baselines" / "outputs" / "baseline_forecasts.csv"
DECOMPOSITION_REPORT = PHASE_ROOT / "07-decomposition" / "outputs" / "decomposition_report.json"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from statsmodels_forecast_runner import build_statsmodels_forecast_package  # noqa: E402


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


class StatsmodelsForecastRunnerTest(TestCase):
    def build(
        self,
        *,
        root: Path = DATA_ROOT,
        series_path: Path = SOURCE_SERIES,
        baseline_report_path: Path = BASELINE_REPORT,
        baseline_forecasts_path: Path = BASELINE_FORECASTS,
        decomposition_report_path: Path = DECOMPOSITION_REPORT,
    ) -> dict:
        return build_statsmodels_forecast_package(
            series_path=series_path,
            calendar_path=root / "calendar.csv",
            scenario_path=root / "forecast_scenario.json",
            cutoff_contract_path=CUTOFF_CONTRACT,
            baseline_report_path=baseline_report_path,
            baseline_forecasts_path=baseline_forecasts_path,
            decomposition_report_path=decomposition_report_path,
            spec_path=root / "statsmodels_model_spec.json",
        )

    def test_tiny_profile_builds_declared_candidates_with_expected_warnings(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "short_history_blocks_model_selection_claim",
                "known_future_calendar_effects_not_modeled_by_candidates",
                "embargo_gap_skipped_before_forecast",
            ],
        )
        self.assertEqual(report["outputs"]["forecast_rows"], 112)
        self.assertEqual(report["outputs"]["diagnostics_rows"], 4)
        self.assertEqual(report["outputs"]["comparison_rows"], 112)
        self.assertEqual(report["outputs"]["candidate_models"], ["ets_additive_trend_seasonal_7", "arima_1_1_0"])
        self.assertEqual(report["outputs"]["primary_baseline_model"], "seasonal_naive_7")

    def test_data_generator_check_rebuilds_committed_statsmodels_spec(self) -> None:
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

    def test_first_horizon_forecasts_match_locked_statsmodels_values(self) -> None:
        rows = self.build()["forecast_rows"]

        self.assertEqual(
            row_for(
                rows,
                segment_id="all",
                model_id="ets_additive_trend_seasonal_7",
                forecast_date="2026-03-18",
            )["forecast_value"],
            "1141.999814",
        )
        self.assertEqual(
            row_for(rows, segment_id="all", model_id="arima_1_1_0", forecast_date="2026-03-18")["forecast_value"],
            "1129.062333",
        )
        self.assertEqual(
            row_for(
                rows,
                segment_id="android",
                model_id="ets_additive_trend_seasonal_7",
                forecast_date="2026-03-18",
            )["forecast_value"],
            "381.999999",
        )
        self.assertEqual(
            row_for(rows, segment_id="android", model_id="arima_1_1_0", forecast_date="2026-03-18")["forecast_value"],
            "377.597805",
        )

    def test_forecasts_skip_embargo_gap_and_preserve_horizon(self) -> None:
        rows = self.build()["forecast_rows"]
        dates = {row["forecast_date"] for row in rows}
        first_rows = [row for row in rows if row["forecast_date"] == "2026-03-18"]

        self.assertNotIn("2026-03-17", dates)
        self.assertEqual(len(first_rows), 4)
        self.assertTrue(all(row["horizon_step"] == 1 for row in first_rows))
        self.assertTrue(all(row["raw_step"] == 2 for row in first_rows))
        self.assertTrue(all(row["skipped_embargo_dates"] == "2026-03-17" for row in rows))

    def test_diagnostics_capture_model_spec_residuals_and_convergence(self) -> None:
        diagnostics = self.build()["diagnostics_rows"]
        ets = row_for(diagnostics, segment_id="all", model_id="ets_additive_trend_seasonal_7")
        arima = row_for(diagnostics, segment_id="all", model_id="arima_1_1_0")
        android_arima = row_for(diagnostics, segment_id="android", model_id="arima_1_1_0")

        self.assertEqual(ets["statsmodels_class"], "ExponentialSmoothing")
        self.assertEqual(ets["trend"], "add")
        self.assertEqual(ets["seasonal"], "add")
        self.assertEqual(ets["initialization_method"], "estimated")
        self.assertEqual(ets["convergence_status"], "converged")
        self.assertEqual(ets["statsmodels_warning_count"], 0)
        self.assertEqual(arima["order"], "1,1,0")
        self.assertEqual(arima["seasonal_order"], "0,0,0,0")
        self.assertEqual(arima["residual_burn_in_rows"], 1)
        self.assertEqual(arima["residual_mean"], "5.11606")
        self.assertEqual(android_arima["lag1_autocorrelation"], "-0.028809")
        self.assertTrue(all(row["decision_status"] == "diagnostic_only_short_history" for row in diagnostics))

    def test_library_vs_baseline_comparison_is_shape_only(self) -> None:
        comparisons = self.build()["comparison_rows"]
        ets_first = row_for(
            comparisons,
            segment_id="all",
            candidate_model_id="ets_additive_trend_seasonal_7",
            forecast_date="2026-03-18",
        )
        arima_anchor = row_for(
            comparisons,
            segment_id="all",
            candidate_model_id="arima_1_1_0",
            forecast_date="2026-03-23",
        )

        self.assertEqual(ets_first["baseline_model_id"], "seasonal_naive_7")
        self.assertEqual(ets_first["baseline_forecast"], "1091")
        self.assertEqual(ets_first["candidate_minus_baseline"], "50.999814")
        self.assertEqual(arima_anchor["candidate_minus_baseline"], "5.107852")
        self.assertTrue(all(row["comparison_status"] == "shape_only_pending_backtest_metrics" for row in comparisons))

    def test_invalid_upstream_baseline_report_blocks_model_run(self) -> None:
        with TemporaryDirectory() as directory:
            baseline_path = Path(directory) / "baseline_report.json"
            report = read_json(BASELINE_REPORT)
            report["valid"] = False
            write_json(baseline_path, report)

            result = self.build(baseline_report_path=baseline_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("baseline_and_decomposition_reports_are_valid", result["summary"]["blocking_errors"])

    def test_auto_model_search_policy_is_blocked(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "statsmodels_model_spec.json")
            spec["selection_policy"]["no_auto_model_search"] = False
            spec["candidate_models"][1]["auto_model_search"] = True
            write_json(root / "statsmodels_model_spec.json", spec)

            result = self.build(root=root)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("no_auto_model_search", result["summary"]["blocking_errors"])

    def test_candidate_families_must_include_ets_and_arima(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "statsmodels_model_spec.json")
            spec["candidate_models"] = [model for model in spec["candidate_models"] if model["family"] != "ARIMA"]
            write_json(root / "statsmodels_model_spec.json", spec)

            result = self.build(root=root)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("ets_and_arima_families_present", result["summary"]["blocking_errors"])

    def test_arima_order_must_stay_explicit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "statsmodels_model_spec.json")
            for model in spec["candidate_models"]:
                if model["model_id"] == "arima_1_1_0":
                    model["order"] = [1, 1]
            write_json(root / "statsmodels_model_spec.json", spec)

            result = self.build(root=root)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("orders_and_initialization_are_explicit", result["summary"]["blocking_errors"])

    def test_training_rows_after_cutoff_block_model_run(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            for row in rows:
                if row["observed_date"] == "2026-03-17":
                    row["include_in_training"] = "true"
            write_csv(series_path, rows)

            result = self.build(series_path=series_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("training_rows_match_cutoff", result["summary"]["blocking_errors"])
        self.assertIn("model_uses_training_window_only", result["summary"]["blocking_errors"])

    def test_duplicate_source_segment_date_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "daily_resampled.csv"
            rows = read_csv(SOURCE_SERIES)
            rows.append(rows[0].copy())
            write_csv(series_path, rows)

            result = self.build(series_path=series_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("source_segment_date_unique", result["summary"]["blocking_errors"])

    def test_missing_primary_baseline_forecast_blocks_comparison(self) -> None:
        with TemporaryDirectory() as directory:
            baseline_path = Path(directory) / "baseline_forecasts.csv"
            rows = [
                row
                for row in read_csv(BASELINE_FORECASTS)
                if not (
                    row["segment_id"] == "all"
                    and row["model_id"] == "seasonal_naive_7"
                    and row["forecast_date"] == "2026-03-18"
                )
            ]
            write_csv(baseline_path, rows)

            result = self.build(baseline_forecasts_path=baseline_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("baseline_forecasts_have_primary_shape", result["summary"]["blocking_errors"])

    def test_minimum_history_policy_blocks_overdemanding_candidate(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "statsmodels_model_spec.json")
            spec["candidate_models"][0]["minimum_training_points"] = 30
            write_json(root / "statsmodels_model_spec.json", spec)

            result = self.build(root=root)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("enough_history_for_declared_candidates", result["summary"]["blocking_errors"])

    def test_cli_writes_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "statsmodels_forecast_runner.py"),
                "--series",
                str(SOURCE_SERIES),
                "--calendar",
                str(DATA_ROOT / "calendar.csv"),
                "--scenario",
                str(DATA_ROOT / "forecast_scenario.json"),
                "--cutoff-contract",
                str(CUTOFF_CONTRACT),
                "--baseline-report",
                str(BASELINE_REPORT),
                "--baseline-forecasts",
                str(BASELINE_FORECASTS),
                "--decomposition-report",
                str(DECOMPOSITION_REPORT),
                "--spec",
                str(DATA_ROOT / "statsmodels_model_spec.json"),
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
            ["candidate_forecasts.csv", "library_vs_baseline.csv", "model_diagnostics.csv", "model_report.json"],
        )
