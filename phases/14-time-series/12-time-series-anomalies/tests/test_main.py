from __future__ import annotations

import csv
import hashlib
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
METRIC_ROOT = PHASE_ROOT / "10-forecast-metrics" / "outputs"
INTERVAL_ROOT = PHASE_ROOT / "11-prediction-intervals" / "outputs"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from time_series_forecast_packager import build_forecast_package  # noqa: E402


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


def report_paths(*, metric_report: Path | None = None, interval_report: Path | None = None) -> dict[str, Path]:
    return {
        "time_index_report": PHASE_ROOT / "01-time-index" / "outputs" / "time_index_audit.json",
        "resampling_report": PHASE_ROOT / "02-resampling" / "outputs" / "resampling_report.json",
        "window_feature_report": PHASE_ROOT / "03-rolling" / "outputs" / "window_feature_report.json",
        "seasonality_report": PHASE_ROOT / "04-trend-and-seasonality" / "outputs" / "seasonality_report.json",
        "temporal_leakage_report": PHASE_ROOT / "05-temporal-leakage" / "outputs" / "temporal_leakage_report.json",
        "baseline_report": PHASE_ROOT / "06-forecast-baselines" / "outputs" / "baseline_report.json",
        "model_report": PHASE_ROOT / "08-ets-and-arima" / "outputs" / "model_report.json",
        "backtest_report": PHASE_ROOT / "09-backtesting" / "outputs" / "backtest_report.json",
        "metric_report": metric_report or METRIC_ROOT / "metric_report.json",
        "interval_report": interval_report or INTERVAL_ROOT / "interval_report.json",
    }


class ForecastPackageTest(TestCase):
    def build(
        self,
        *,
        root: Path = DATA_ROOT,
        spec_path: Path | None = None,
        metric_report_path: Path | None = None,
        interval_report_path: Path | None = None,
        interval_forecasts_path: Path = INTERVAL_ROOT / "interval_forecasts.csv",
    ) -> dict:
        return build_forecast_package(
            spec_path=spec_path or root / "forecast_package_spec.json",
            scenario_path=root / "forecast_scenario.json",
            metric_observations_path=root / "metric_observations.csv",
            calendar_path=root / "calendar.csv",
            data_revisions_path=root / "data_revisions.csv",
            metric_leaderboard_path=METRIC_ROOT / "metric_leaderboard.csv",
            interval_forecasts_path=interval_forecasts_path,
            interval_coverage_path=INTERVAL_ROOT / "interval_coverage.csv",
            report_paths=report_paths(metric_report=metric_report_path, interval_report=interval_report_path),
        )

    def test_tiny_profile_builds_integrated_forecast_package(self) -> None:
        package = self.build()
        report = package["report"]

        self.assertTrue(report["valid"])
        self.assertEqual(report["error_count"], 0)
        self.assertEqual(report["summary"]["warnings"], ["upstream_warnings_propagated_to_decision"])
        self.assertEqual(report["outputs"]["primary_model_id"], "ets_additive_trend_seasonal_7")
        self.assertEqual(report["outputs"]["primary_interval_method"], "residual_quantile")
        self.assertEqual(report["outputs"]["labels"]["data_quality"], 3)
        self.assertEqual(report["outputs"]["labels"]["calendar_expected"], 8)
        self.assertEqual(report["outputs"]["labels"]["model_misspecification"], 14)
        self.assertEqual(report["outputs"]["labels"]["product_signal_candidate"], 0)
        self.assertEqual(report["outputs"]["labels"]["inconclusive"], 16)

    def test_data_generator_check_rebuilds_committed_package_spec(self) -> None:
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

    def test_partial_rows_and_revisions_are_data_quality_not_product_signals(self) -> None:
        rows = self.build()["anomaly_rows"]
        partial_all = row_for(rows, case_id="dq-source-all-2026-03-17")
        revision = row_for(rows, case_id="dq-revision-all-2026-03-12")

        self.assertEqual(partial_all["label"], "data_quality")
        self.assertEqual(partial_all["gate"], "data_quality")
        self.assertIn("source_status=partial", partial_all["evidence"])
        self.assertEqual(revision["label"], "data_quality")
        self.assertTrue(all(row["label"] != "product_signal_candidate" for row in rows if row["gate"] == "data_quality"))

    def test_holiday_release_and_future_campaign_contexts_are_not_product_signals(self) -> None:
        rows = self.build()["anomaly_rows"]
        holiday = row_for(rows, case_id="calendar-all-2026-03-08")
        release = row_for(rows, case_id="calendar-android-2026-03-11")
        campaign = row_for(rows, case_id="future-context-all-2026-03-20")

        self.assertEqual(holiday["label"], "calendar_expected")
        self.assertIn("holiday:spring_promo_day", holiday["evidence"])
        self.assertEqual(release["label"], "calendar_expected")
        self.assertIn("release_active", release["evidence"])
        self.assertEqual(campaign["label"], "inconclusive")
        self.assertIn("campaign_active", campaign["evidence"])

    def test_model_based_undercoverage_is_flagged_as_model_misspecification(self) -> None:
        rows = self.build()["anomaly_rows"]
        misspec_rows = [row for row in rows if row["label"] == "model_misspecification"]

        self.assertEqual(len(misspec_rows), 14)
        self.assertTrue(all("model_based_normal" in row["evidence"] for row in misspec_rows))

    def test_manifest_hashes_existing_inputs_and_generated_outputs(self) -> None:
        package = self.build()
        manifest = package["manifest"]
        spec_hash = hashlib.sha256((DATA_ROOT / "forecast_package_spec.json").read_bytes()).hexdigest()

        self.assertEqual(manifest["inputs"]["spec"]["sha256"], spec_hash)
        self.assertEqual(set(manifest["outputs"]), {
            "anomaly_flags.csv",
            "anomaly_policy.json",
            "decision_report.md",
            "forecast_package_report.json",
            "quality_gate_summary.csv",
        })
        self.assertEqual(manifest["outputs"]["decision_report.md"]["bytes"], len(package["decision_report"].encode("utf-8")))

    def test_decision_report_preserves_interpretation_boundary(self) -> None:
        decision = self.build()["decision_report"]

        self.assertIn("does not make a causal claim", decision)
        self.assertIn("not a production SLA release", decision)

    def test_missing_anomaly_label_blocks_package(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "forecast_package_spec.json")
            spec["anomaly_policy"]["labels"] = spec["anomaly_policy"]["labels"][:-1]
            write_json(root / "forecast_package_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("anomaly_policy_contains_all_labels", report["summary"]["blocking_errors"])

    def test_primary_model_must_match_metric_leaderboard(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "forecast_package_spec.json")
            spec["primary_model_id"] = "seasonal_naive_7"
            write_json(root / "forecast_package_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("primary_model_matches_metric_leaderboard", report["summary"]["blocking_errors"])

    def test_invalid_upstream_report_blocks_package(self) -> None:
        with TemporaryDirectory() as directory:
            metric_report_path = Path(directory) / "metric_report.json"
            report = read_json(METRIC_ROOT / "metric_report.json")
            report["valid"] = False
            write_json(metric_report_path, report)

            result = self.build(metric_report_path=metric_report_path)["report"]

        self.assertFalse(result["valid"])
        self.assertIn("upstream_reports_are_valid", result["summary"]["blocking_errors"])

    def test_primary_interval_method_must_match_interval_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(DATA_ROOT, root, dirs_exist_ok=True)
            spec = read_json(root / "forecast_package_spec.json")
            spec["primary_interval_method"] = "residual_bootstrap"
            write_json(root / "forecast_package_spec.json", spec)

            report = self.build(root=root)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("primary_interval_method_matches_interval_report", report["summary"]["blocking_errors"])

    def test_primary_interval_forecast_rows_are_required(self) -> None:
        with TemporaryDirectory() as directory:
            interval_path = Path(directory) / "interval_forecasts.csv"
            rows = [
                row
                for row in read_csv(INTERVAL_ROOT / "interval_forecasts.csv")
                if not (row["model_id"] == "ets_additive_trend_seasonal_7" and row["method_id"] == "residual_quantile")
            ]
            write_csv(interval_path, rows)

            report = self.build(interval_forecasts_path=interval_path)["report"]

        self.assertFalse(report["valid"])
        self.assertIn("primary_interval_forecasts_exist", report["summary"]["blocking_errors"])

    def test_cli_writes_package_and_can_fail_on_warning(self) -> None:
        with TemporaryDirectory() as directory:
            output_dir = Path(directory) / "package"
            command = [
                sys.executable,
                str(LESSON_ROOT / "outputs" / "time_series_forecast_packager.py"),
                "--spec",
                str(DATA_ROOT / "forecast_package_spec.json"),
                "--scenario",
                str(DATA_ROOT / "forecast_scenario.json"),
                "--metric-observations",
                str(DATA_ROOT / "metric_observations.csv"),
                "--calendar",
                str(DATA_ROOT / "calendar.csv"),
                "--data-revisions",
                str(DATA_ROOT / "data_revisions.csv"),
                "--metric-leaderboard",
                str(METRIC_ROOT / "metric_leaderboard.csv"),
                "--interval-forecasts",
                str(INTERVAL_ROOT / "interval_forecasts.csv"),
                "--interval-coverage",
                str(INTERVAL_ROOT / "interval_coverage.csv"),
                "--time-index-report",
                str(PHASE_ROOT / "01-time-index" / "outputs" / "time_index_audit.json"),
                "--resampling-report",
                str(PHASE_ROOT / "02-resampling" / "outputs" / "resampling_report.json"),
                "--window-feature-report",
                str(PHASE_ROOT / "03-rolling" / "outputs" / "window_feature_report.json"),
                "--seasonality-report",
                str(PHASE_ROOT / "04-trend-and-seasonality" / "outputs" / "seasonality_report.json"),
                "--temporal-leakage-report",
                str(PHASE_ROOT / "05-temporal-leakage" / "outputs" / "temporal_leakage_report.json"),
                "--baseline-report",
                str(PHASE_ROOT / "06-forecast-baselines" / "outputs" / "baseline_report.json"),
                "--model-report",
                str(PHASE_ROOT / "08-ets-and-arima" / "outputs" / "model_report.json"),
                "--backtest-report",
                str(PHASE_ROOT / "09-backtesting" / "outputs" / "backtest_report.json"),
                "--metric-report",
                str(METRIC_ROOT / "metric_report.json"),
                "--interval-report",
                str(INTERVAL_ROOT / "interval_report.json"),
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
                "anomaly_flags.csv",
                "anomaly_policy.json",
                "decision_report.md",
                "forecast_package_manifest.json",
                "forecast_package_report.json",
                "quality_gate_summary.csv",
            ],
        )
