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
BACKTEST_ROOT = PHASE_ROOT / "09-backtesting" / "outputs"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from forecast_metric_evaluator import build_forecast_metric_package  # noqa: E402


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
    return next(row for row in rows if all(str(row[key]) == value for key, value in criteria.items()))


class ForecastMetricEvaluatorTest(TestCase):
    def build(
        self,
        *,
        root: Path = DATA_ROOT,
        errors_path: Path = BACKTEST_ROOT / "backtest_errors.csv",
        split_manifest_path: Path = BACKTEST_ROOT / "split_manifest.csv",
        series_path: Path | None = None,
        backtest_report_path: Path = BACKTEST_ROOT / "backtest_report.json",
    ) -> dict:
        return build_forecast_metric_package(
            errors_path=errors_path,
            split_manifest_path=split_manifest_path,
            series_path=series_path or root / "backtest_observations.csv",
            backtest_report_path=backtest_report_path,
            spec_path=root / "forecast_metric_spec.json",
        )

    def test_tiny_profile_builds_metric_tables_with_expected_warning(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(report["summary"]["warnings"], ["backtest_warnings_limit_model_selection"])
        self.assertEqual(report["outputs"]["metric_rows"], 18)
        self.assertEqual(report["outputs"]["leaderboard_rows"], 3)
        self.assertEqual(report["outputs"]["suitability_rows"], 6)
        self.assertEqual(report["outputs"]["mase_denominator_rows"], 8)
        self.assertEqual(report["outputs"]["primary_metric"], "weighted_mase")
        self.assertEqual(report["outputs"]["top_model_id"], "ets_additive_trend_seasonal_7")
        self.assertEqual(report["outputs"]["top_model_decision_status"], "diagnostic_leaderboard_not_production_selection")

    def test_data_generator_check_rebuilds_committed_metric_spec(self) -> None:
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

    def test_mase_denominators_match_tiny_seasonal_naive_scales(self) -> None:
        denominators = self.build()["denominator_rows"]

        self.assertEqual(
            row_for(denominators, split_id="bt-expanding-2026-02-24", segment_id="all")["mase_denominator"],
            "63",
        )
        self.assertEqual(
            row_for(denominators, split_id="bt-expanding-2026-02-24", segment_id="android")["mase_denominator"],
            "28",
        )
        self.assertEqual(
            row_for(denominators, split_id="bt-rolling-2026-03-14", segment_id="all")["mase_denominator"],
            "66.428571",
        )

    def test_overall_segment_and_horizon_metrics_match_locked_values(self) -> None:
        rows = self.build()["metric_rows"]
        baseline = row_for(rows, aggregation_level="overall", model_id="seasonal_naive_7")
        ets_segment = row_for(rows, aggregation_level="segment", segment_id="all", model_id="ets_additive_trend_seasonal_7")
        ets_horizon = row_for(rows, aggregation_level="horizon", horizon_step="3", model_id="ets_additive_trend_seasonal_7")
        arima_android = row_for(rows, aggregation_level="segment", segment_id="android", model_id="arima_1_1_0")

        self.assertEqual(baseline["mae"], "46.5")
        self.assertEqual(baseline["rmse"], "50.264301")
        self.assertEqual(baseline["wape"], "6.782133")
        self.assertEqual(baseline["mase"], "1.009831")
        self.assertEqual(ets_segment["mae"], "6.333388")
        self.assertEqual(ets_segment["mase"], "0.097799")
        self.assertEqual(ets_horizon["mase"], "0.053918")
        self.assertEqual(arima_android["mase"], "0.855441")

    def test_suitability_audit_keeps_percentage_metrics_diagnostic_only(self) -> None:
        rows = self.build()["suitability_rows"]
        mape = row_for(rows, metric_name="mape")
        smape = row_for(rows, metric_name="smape")
        mase = row_for(rows, metric_name="mase")

        self.assertEqual(mape["decision_role"], "diagnostic_only")
        self.assertEqual(mape["status"], "diagnostic_only")
        self.assertEqual(smape["status"], "diagnostic_only")
        self.assertEqual(mase["decision_role"], "primary")
        self.assertEqual(mase["status"], "allowed")
        self.assertEqual(mase["observed_min_actual"], "294")

    def test_leaderboard_uses_weighted_mase_but_blocks_selection_on_backtest_warnings(self) -> None:
        rows = self.build()["leaderboard_rows"]
        top = row_for(rows, rank="1")
        arima = row_for(rows, model_id="arima_1_1_0")
        baseline = row_for(rows, model_id="seasonal_naive_7")

        self.assertEqual(top["model_id"], "ets_additive_trend_seasonal_7")
        self.assertEqual(top["primary_metric_value"], "0.068459")
        self.assertEqual(top["baseline_metric_value"], "1.013763")
        self.assertEqual(top["relative_improvement_vs_baseline"], "0.93247")
        self.assertEqual(top["eligible_for_model_selection"], "false")
        self.assertEqual(top["decision_status"], "diagnostic_leaderboard_not_production_selection")
        self.assertIn("small_origin_count_blocks_model_selection_claim", top["warning_ids"])
        self.assertEqual(arima["rank"], 2)
        self.assertEqual(arima["primary_metric_value"], "0.914565")
        self.assertEqual(baseline["rank"], 3)

    def test_zero_actual_blocks_percentage_metrics_without_invalidating_primary_mase(self) -> None:
        with TemporaryDirectory() as directory:
            errors_path = Path(directory) / "backtest_errors.csv"
            rows = read_csv(BACKTEST_ROOT / "backtest_errors.csv")
            rows[0]["actual_value"] = "0"
            write_csv(errors_path, rows)

            package = self.build(errors_path=errors_path)

        report = package["report"]
        suitability = package["suitability_rows"]
        mape = row_for(suitability, metric_name="mape")
        mase = row_for(suitability, metric_name="mase")

        self.assertTrue(report["valid"])
        self.assertIn("percentage_denominators_are_safe_or_blocked", report["summary"]["warnings"])
        self.assertEqual(mape["status"], "blocked")
        self.assertEqual(mape["observed_zero_actual_count"], 1)
        self.assertEqual(mase["status"], "allowed")

    def test_percentage_metric_cannot_be_primary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "forecast_metric_spec.json")
            spec["primary_metric"] = "mape"
            write_json(root / "forecast_metric_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("percentage_metrics_not_primary_decision_metric", report["summary"]["blocking_errors"])

    def test_segment_weights_must_cover_targets_and_sum_to_one(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "forecast_metric_spec.json")
            spec["segment_weights"] = {"all": 1.0}
            write_json(root / "forecast_metric_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("segment_weights_cover_targets_and_sum_to_one", report["summary"]["blocking_errors"])

    def test_missing_horizon_error_row_blocks_metric_table(self) -> None:
        with TemporaryDirectory() as directory:
            errors_path = Path(directory) / "backtest_errors.csv"
            rows = read_csv(BACKTEST_ROOT / "backtest_errors.csv")
            write_csv(errors_path, rows[:-1])

            report = self.build(errors_path=errors_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("backtest_error_rows_match_report", report["summary"]["blocking_errors"])

    def test_duplicate_error_grain_blocks_report(self) -> None:
        with TemporaryDirectory() as directory:
            errors_path = Path(directory) / "backtest_errors.csv"
            rows = read_csv(BACKTEST_ROOT / "backtest_errors.csv")
            rows.append(rows[0].copy())
            write_csv(errors_path, rows)

            report = self.build(errors_path=errors_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("backtest_error_grain_unique", report["summary"]["blocking_errors"])

    def test_invalid_upstream_backtest_report_blocks_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            backtest_report_path = Path(directory) / "backtest_report.json"
            report = read_json(BACKTEST_ROOT / "backtest_report.json")
            report["valid"] = False
            write_json(backtest_report_path, report)

            result = self.build(backtest_report_path=backtest_report_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("backtest_report_is_valid", result["summary"]["blocking_errors"])

    def test_zero_mase_denominator_blocks_scaled_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            series_path = Path(directory) / "backtest_observations.csv"
            rows = read_csv(DATA_ROOT / "backtest_observations.csv")
            for row in rows:
                if row["segment_id"] == "android":
                    row["value"] = "100"
            write_csv(series_path, rows)

            report = self.build(series_path=series_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("mase_denominator_positive", report["summary"]["blocking_errors"])

    def test_cli_writes_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "forecast_metric_evaluator.py"),
                "--errors",
                str(BACKTEST_ROOT / "backtest_errors.csv"),
                "--split-manifest",
                str(BACKTEST_ROOT / "split_manifest.csv"),
                "--series",
                str(DATA_ROOT / "backtest_observations.csv"),
                "--backtest-report",
                str(BACKTEST_ROOT / "backtest_report.json"),
                "--spec",
                str(DATA_ROOT / "forecast_metric_spec.json"),
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
                "forecast_metrics.csv",
                "mase_denominators.csv",
                "metric_leaderboard.csv",
                "metric_report.json",
                "metric_suitability_audit.csv",
            ],
        )
