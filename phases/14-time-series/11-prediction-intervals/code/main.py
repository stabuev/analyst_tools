from __future__ import annotations

import json
from pathlib import Path
import sys


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUTS_ROOT = LESSON_ROOT / "outputs"
BASELINE_ROOT = PHASE_ROOT / "06-forecast-baselines" / "outputs"
MODEL_ROOT = PHASE_ROOT / "08-ets-and-arima" / "outputs"
BACKTEST_ROOT = PHASE_ROOT / "09-backtesting" / "outputs"
METRIC_ROOT = PHASE_ROOT / "10-forecast-metrics" / "outputs"

sys.path.insert(0, str(OUTPUTS_ROOT))

from prediction_interval_calibrator import build_prediction_interval_package, write_package  # noqa: E402


def main() -> None:
    package = build_prediction_interval_package(
        errors_path=BACKTEST_ROOT / "backtest_errors.csv",
        final_baseline_forecasts_path=BASELINE_ROOT / "baseline_forecasts.csv",
        final_candidate_forecasts_path=MODEL_ROOT / "candidate_forecasts.csv",
        backtest_report_path=BACKTEST_ROOT / "backtest_report.json",
        metric_report_path=METRIC_ROOT / "metric_report.json",
        spec_path=DATA_ROOT / "prediction_interval_spec.json",
    )
    write_package(package, OUTPUTS_ROOT)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "interval_forecast_rows": report["outputs"]["interval_forecast_rows"],
                "coverage_rows": report["outputs"]["coverage_rows"],
                "primary_interval_method": report["outputs"]["primary_interval_method"],
                "primary_interval_min_coverage": report["outputs"]["primary_interval_min_coverage"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
