from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"


def main() -> None:
    output_dir = LESSON_ROOT / "outputs"
    command = [
        sys.executable,
        str(output_dir / "time_series_forecast_packager.py"),
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
        str(PHASE_ROOT / "10-forecast-metrics" / "outputs" / "metric_leaderboard.csv"),
        "--interval-forecasts",
        str(PHASE_ROOT / "11-prediction-intervals" / "outputs" / "interval_forecasts.csv"),
        "--interval-coverage",
        str(PHASE_ROOT / "11-prediction-intervals" / "outputs" / "interval_coverage.csv"),
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
        str(PHASE_ROOT / "10-forecast-metrics" / "outputs" / "metric_report.json"),
        "--interval-report",
        str(PHASE_ROOT / "11-prediction-intervals" / "outputs" / "interval_report.json"),
        "--output-dir",
        str(output_dir),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    print(json.dumps(json.loads(result.stdout), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
