from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from window_feature_builder import build_window_feature_package, write_package  # noqa: E402


def main() -> None:
    package = build_window_feature_package(
        series_path=PHASE_ROOT / "02-resampling" / "outputs" / "daily_resampled.csv",
        scenario_path=DATA_ROOT / "forecast_scenario.json",
        spec_path=DATA_ROOT / "window_feature_spec.json",
    )
    write_package(LESSON_ROOT / "outputs", package)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "feature_rows": report["outputs"]["feature_rows"],
                "training_feature_rows": report["outputs"]["training_feature_rows"],
            },
            ensure_ascii=False,
        )
    )
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
