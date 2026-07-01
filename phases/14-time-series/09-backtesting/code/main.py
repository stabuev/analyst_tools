from __future__ import annotations

import json
from pathlib import Path
import sys


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUTS_ROOT = LESSON_ROOT / "outputs"
MODEL_REPORT = PHASE_ROOT / "08-ets-and-arima" / "outputs" / "model_report.json"

sys.path.insert(0, str(OUTPUTS_ROOT))

from rolling_backtester import build_backtest_package, write_package  # noqa: E402


def main() -> None:
    package = build_backtest_package(
        series_path=DATA_ROOT / "backtest_observations.csv",
        scenario_path=DATA_ROOT / "forecast_scenario.json",
        model_spec_path=DATA_ROOT / "statsmodels_model_spec.json",
        model_report_path=MODEL_REPORT,
        spec_path=DATA_ROOT / "backtesting_spec.json",
    )
    write_package(package, OUTPUTS_ROOT)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "split_rows": report["outputs"]["split_rows"],
                "forecast_rows": report["outputs"]["forecast_rows"],
                "error_rows": report["outputs"]["error_rows"],
                "models": report["outputs"]["models"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
