from __future__ import annotations

import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from statsmodels_forecast_runner import build_statsmodels_forecast_package, write_package  # noqa: E402


def main() -> None:
    package = build_statsmodels_forecast_package(
        series_path=PHASE_ROOT / "02-resampling" / "outputs" / "daily_resampled.csv",
        calendar_path=PHASE_ROOT / "data" / "tiny" / "calendar.csv",
        scenario_path=PHASE_ROOT / "data" / "tiny" / "forecast_scenario.json",
        cutoff_contract_path=PHASE_ROOT / "05-temporal-leakage" / "outputs" / "cutoff_contract.json",
        baseline_report_path=PHASE_ROOT / "06-forecast-baselines" / "outputs" / "baseline_report.json",
        baseline_forecasts_path=PHASE_ROOT / "06-forecast-baselines" / "outputs" / "baseline_forecasts.csv",
        decomposition_report_path=PHASE_ROOT / "07-decomposition" / "outputs" / "decomposition_report.json",
        spec_path=PHASE_ROOT / "data" / "tiny" / "statsmodels_model_spec.json",
    )
    write_package(package, LESSON_ROOT / "outputs")
    report = package["report"]
    print(
        {
            "valid": report["valid"],
            "warnings": report["summary"]["warnings"],
            "forecast_rows": report["outputs"]["forecast_rows"],
            "diagnostics_rows": report["outputs"]["diagnostics_rows"],
            "comparison_rows": report["outputs"]["comparison_rows"],
            "candidate_models": report["outputs"]["candidate_models"],
        }
    )


if __name__ == "__main__":
    main()
