from __future__ import annotations

import json
from pathlib import Path
import sys


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUTS_ROOT = LESSON_ROOT / "outputs"
BACKTEST_ROOT = PHASE_ROOT / "09-backtesting" / "outputs"

sys.path.insert(0, str(OUTPUTS_ROOT))

from forecast_metric_evaluator import build_forecast_metric_package, write_package  # noqa: E402


def main() -> None:
    package = build_forecast_metric_package(
        errors_path=BACKTEST_ROOT / "backtest_errors.csv",
        split_manifest_path=BACKTEST_ROOT / "split_manifest.csv",
        series_path=DATA_ROOT / "backtest_observations.csv",
        backtest_report_path=BACKTEST_ROOT / "backtest_report.json",
        spec_path=DATA_ROOT / "forecast_metric_spec.json",
    )
    write_package(package, OUTPUTS_ROOT)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "metric_rows": report["outputs"]["metric_rows"],
                "leaderboard_rows": report["outputs"]["leaderboard_rows"],
                "primary_metric": report["outputs"]["primary_metric"],
                "top_model_id": report["outputs"]["top_model_id"],
                "top_model_decision_status": report["outputs"]["top_model_decision_status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
