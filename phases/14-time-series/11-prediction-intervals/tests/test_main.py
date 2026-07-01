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
BASELINE_ROOT = PHASE_ROOT / "06-forecast-baselines" / "outputs"
MODEL_ROOT = PHASE_ROOT / "08-ets-and-arima" / "outputs"
BACKTEST_ROOT = PHASE_ROOT / "09-backtesting" / "outputs"
METRIC_ROOT = PHASE_ROOT / "10-forecast-metrics" / "outputs"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from prediction_interval_calibrator import build_prediction_interval_package  # noqa: E402


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


class PredictionIntervalCalibratorTest(TestCase):
    def build(
        self,
        *,
        root: Path = DATA_ROOT,
        errors_path: Path = BACKTEST_ROOT / "backtest_errors.csv",
        baseline_path: Path = BASELINE_ROOT / "baseline_forecasts.csv",
        candidate_path: Path = MODEL_ROOT / "candidate_forecasts.csv",
        backtest_report_path: Path = BACKTEST_ROOT / "backtest_report.json",
        metric_report_path: Path = METRIC_ROOT / "metric_report.json",
    ) -> dict:
        return build_prediction_interval_package(
            errors_path=errors_path,
            final_baseline_forecasts_path=baseline_path,
            final_candidate_forecasts_path=candidate_path,
            backtest_report_path=backtest_report_path,
            metric_report_path=metric_report_path,
            spec_path=root / "prediction_interval_spec.json",
        )

    def test_tiny_profile_builds_intervals_with_expected_warnings(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(
            report["summary"]["warnings"],
            [
                "small_origin_count_blocks_interval_sla_claim",
                "interval_horizon_shorter_than_final_forecast",
                "upstream_warnings_limit_interval_claim",
                "diagnostic_model_based_undercoverage_is_warned",
            ],
        )
        self.assertEqual(report["outputs"]["calibration_rows"], 54)
        self.assertEqual(report["outputs"]["backtest_interval_rows"], 216)
        self.assertEqual(report["outputs"]["coverage_rows"], 54)
        self.assertEqual(report["outputs"]["interval_forecast_rows"], 504)
        self.assertEqual(report["outputs"]["primary_interval_method"], "residual_quantile")
        self.assertEqual(report["outputs"]["primary_interval_min_coverage"], "1")

    def test_data_generator_check_rebuilds_committed_interval_spec(self) -> None:
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

    def test_calibration_audit_contains_residual_bootstrap_and_model_based_parameters(self) -> None:
        rows = self.build()["calibration_rows"]
        baseline_abs = row_for(
            rows,
            model_id="seasonal_naive_7",
            segment_id="all",
            horizon_step="1",
            method_id="residual_quantile",
        )
        baseline_bootstrap = row_for(
            rows,
            model_id="seasonal_naive_7",
            segment_id="all",
            horizon_step="3",
            method_id="residual_bootstrap",
        )
        ets_model_based = row_for(
            rows,
            model_id="ets_additive_trend_seasonal_7",
            segment_id="all",
            horizon_step="3",
            method_id="model_based_normal",
        )

        self.assertEqual(baseline_abs["lower_residual"], "-75")
        self.assertEqual(baseline_abs["upper_residual"], "75")
        self.assertEqual(baseline_bootstrap["lower_residual"], "51")
        self.assertEqual(baseline_bootstrap["upper_residual"], "75")
        self.assertEqual(ets_model_based["residual_stddev"], "11.489255")
        self.assertEqual(ets_model_based["interval_half_width"], "18.898142")

    def test_coverage_report_separates_primary_coverage_from_model_based_undercoverage(self) -> None:
        rows = self.build()["coverage_rows"]
        residual = row_for(
            rows,
            aggregation_level="overall",
            method_id="residual_quantile",
            model_id="ets_additive_trend_seasonal_7",
        )
        model_based_baseline = row_for(
            rows,
            aggregation_level="overall",
            method_id="model_based_normal",
            model_id="seasonal_naive_7",
        )
        model_based_ets = row_for(
            rows,
            aggregation_level="overall",
            method_id="model_based_normal",
            model_id="ets_additive_trend_seasonal_7",
        )

        self.assertEqual(residual["empirical_coverage"], "1")
        self.assertEqual(residual["coverage_status"], "meets_target")
        self.assertEqual(model_based_baseline["empirical_coverage"], "0")
        self.assertEqual(model_based_baseline["coverage_status"], "diagnostic_undercoverage")
        self.assertEqual(model_based_ets["empirical_coverage"], "0.916667")

    def test_final_interval_forecasts_include_uncertainty_statement_and_horizon_extrapolation(self) -> None:
        rows = self.build()["interval_forecast_rows"]
        exact = row_for(
            rows,
            model_id="ets_additive_trend_seasonal_7",
            segment_id="all",
            horizon_step="3",
            method_id="residual_quantile",
        )
        extrapolated = row_for(
            rows,
            model_id="ets_additive_trend_seasonal_7",
            segment_id="all",
            horizon_step="4",
            method_id="residual_quantile",
        )
        arima_bootstrap = row_for(
            rows,
            model_id="arima_1_1_0",
            segment_id="all",
            horizon_step="3",
            method_id="residual_bootstrap",
        )

        self.assertEqual(exact["point_forecast"], "1160.000044")
        self.assertEqual(exact["lower_bound"], "1143.999739")
        self.assertEqual(exact["upper_bound"], "1176.000349")
        self.assertEqual(exact["horizon_policy_status"], "exact")
        self.assertEqual(extrapolated["horizon_policy_status"], "extrapolated_from_step_3")
        self.assertIn("90% prediction interval", extrapolated["uncertainty_statement"])
        self.assertEqual(arima_bootstrap["lower_bound"], "1151.268777")
        self.assertEqual(arima_bootstrap["upper_bound"], "1216.18614")

    def test_backtest_interval_rows_mark_primary_intervals_as_covered(self) -> None:
        rows = self.build()["backtest_interval_rows"]
        primary_rows = [row for row in rows if row["method_id"] == "residual_quantile"]

        self.assertEqual(len(primary_rows), 72)
        self.assertTrue(all(row["covered"] == "true" for row in primary_rows))

    def test_low_primary_quantile_blocks_coverage_claim(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "prediction_interval_spec.json")
            spec["methods"][0]["absolute_error_quantile"] = 0.25
            write_json(root / "prediction_interval_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("primary_interval_coverage_meets_target", report["summary"]["blocking_errors"])

    def test_interval_methods_must_be_declared(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "prediction_interval_spec.json")
            spec["methods"] = spec["methods"][:2]
            write_json(root / "prediction_interval_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("interval_methods_declared", report["summary"]["blocking_errors"])

    def test_confidence_interval_flag_cannot_replace_prediction_interval_policy(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "prediction_interval_spec.json")
            spec["interval_policy"]["prediction_interval_not_confidence_interval"] = False
            write_json(root / "prediction_interval_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("prediction_interval_not_confidence_interval", report["summary"]["blocking_errors"])

    def test_invalid_metric_report_blocks_interval_package(self) -> None:
        with TemporaryDirectory() as directory:
            metric_report_path = Path(directory) / "metric_report.json"
            report = read_json(METRIC_ROOT / "metric_report.json")
            report["valid"] = False
            write_json(metric_report_path, report)

            result = self.build(metric_report_path=metric_report_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("metric_report_is_valid", result["summary"]["blocking_errors"])

    def test_duplicate_backtest_error_grain_blocks_calibration(self) -> None:
        with TemporaryDirectory() as directory:
            errors_path = Path(directory) / "backtest_errors.csv"
            rows = read_csv(BACKTEST_ROOT / "backtest_errors.csv")
            rows.append(rows[0].copy())
            write_csv(errors_path, rows)

            report = self.build(errors_path=errors_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("backtest_error_grain_unique", report["summary"]["blocking_errors"])

    def test_final_forecast_table_must_have_full_horizon(self) -> None:
        with TemporaryDirectory() as directory:
            candidate_path = Path(directory) / "candidate_forecasts.csv"
            rows = read_csv(MODEL_ROOT / "candidate_forecasts.csv")
            write_csv(candidate_path, rows[:-1])

            report = self.build(candidate_path=candidate_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("final_forecast_table_has_full_horizon", report["summary"]["blocking_errors"])

    def test_duplicate_final_forecast_grain_blocks_package(self) -> None:
        with TemporaryDirectory() as directory:
            candidate_path = Path(directory) / "candidate_forecasts.csv"
            rows = read_csv(MODEL_ROOT / "candidate_forecasts.csv")
            rows.append(rows[0].copy())
            write_csv(candidate_path, rows)

            report = self.build(candidate_path=candidate_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("final_forecast_grain_unique", report["summary"]["blocking_errors"])

    def test_calibration_group_minimum_is_enforced(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "prediction_interval_spec.json")
            spec["minimum_backtest_rows_per_group"] = 5
            write_json(root / "prediction_interval_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("calibration_groups_have_minimum_rows", report["summary"]["blocking_errors"])

    def test_cli_writes_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "prediction_interval_calibrator.py"),
                "--errors",
                str(BACKTEST_ROOT / "backtest_errors.csv"),
                "--final-baseline-forecasts",
                str(BASELINE_ROOT / "baseline_forecasts.csv"),
                "--final-candidate-forecasts",
                str(MODEL_ROOT / "candidate_forecasts.csv"),
                "--backtest-report",
                str(BACKTEST_ROOT / "backtest_report.json"),
                "--metric-report",
                str(METRIC_ROOT / "metric_report.json"),
                "--spec",
                str(DATA_ROOT / "prediction_interval_spec.json"),
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
                "interval_backtest_predictions.csv",
                "interval_calibration_audit.csv",
                "interval_coverage.csv",
                "interval_forecasts.csv",
                "interval_report.json",
            ],
        )
