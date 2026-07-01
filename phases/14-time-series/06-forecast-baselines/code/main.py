from __future__ import annotations

import json
from pathlib import Path
import sys


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUTS_ROOT = LESSON_ROOT / "outputs"
SOURCE_SERIES = PHASE_ROOT / "02-resampling" / "outputs" / "daily_resampled.csv"
CUTOFF_CONTRACT = PHASE_ROOT / "05-temporal-leakage" / "outputs" / "cutoff_contract.json"

sys.path.insert(0, str(OUTPUTS_ROOT))

from baseline_forecaster import build_baseline_forecast_package, write_package  # noqa: E402


def main() -> None:
    package = build_baseline_forecast_package(
        series_path=SOURCE_SERIES,
        calendar_path=DATA_ROOT / "calendar.csv",
        scenario_path=DATA_ROOT / "forecast_scenario.json",
        cutoff_contract_path=CUTOFF_CONTRACT,
        spec_path=DATA_ROOT / "baseline_forecast_spec.json",
    )
    write_package(OUTPUTS_ROOT, package)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "forecast_rows": report["outputs"]["forecast_rows"],
                "models": report["outputs"]["models"],
                "primary_baseline_model": report["outputs"]["primary_baseline_model"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
