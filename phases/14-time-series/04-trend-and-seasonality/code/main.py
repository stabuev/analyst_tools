from __future__ import annotations

import json
from pathlib import Path
import sys


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUTS_ROOT = LESSON_ROOT / "outputs"
SOURCE_SERIES = PHASE_ROOT / "02-resampling" / "outputs" / "daily_resampled.csv"

sys.path.insert(0, str(OUTPUTS_ROOT))

from seasonality_profiler import build_seasonality_profile_package, write_package  # noqa: E402


def main() -> None:
    package = build_seasonality_profile_package(
        series_path=SOURCE_SERIES,
        calendar_path=DATA_ROOT / "calendar.csv",
        campaign_path=DATA_ROOT / "campaign_calendar.csv",
        release_path=DATA_ROOT / "release_calendar.csv",
        scenario_path=DATA_ROOT / "forecast_scenario.json",
        spec_path=DATA_ROOT / "seasonality_profile_spec.json",
    )
    write_package(OUTPUTS_ROOT, package)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "trend_rows": report["outputs"]["trend_rows"],
                "seasonality_rows": report["outputs"]["seasonality_rows"],
                "calendar_effect_rows": report["outputs"]["calendar_effect_rows"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
