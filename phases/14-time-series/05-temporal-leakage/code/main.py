from __future__ import annotations

import json
from pathlib import Path
import sys


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUTS_ROOT = LESSON_ROOT / "outputs"
SOURCE_SERIES = PHASE_ROOT / "02-resampling" / "outputs" / "daily_resampled.csv"
SOURCE_FEATURES = PHASE_ROOT / "03-rolling" / "outputs" / "window_features.csv"
SOURCE_FEATURE_AUDIT = PHASE_ROOT / "03-rolling" / "outputs" / "leakage_audit.csv"

sys.path.insert(0, str(OUTPUTS_ROOT))

from temporal_leakage_auditor import build_temporal_leakage_package, write_package  # noqa: E402


def main() -> None:
    package = build_temporal_leakage_package(
        series_path=SOURCE_SERIES,
        features_path=SOURCE_FEATURES,
        feature_audit_path=SOURCE_FEATURE_AUDIT,
        calendar_path=DATA_ROOT / "calendar.csv",
        revisions_path=DATA_ROOT / "data_revisions.csv",
        scenario_path=DATA_ROOT / "forecast_scenario.json",
        spec_path=DATA_ROOT / "temporal_leakage_spec.json",
    )
    write_package(OUTPUTS_ROOT, package)
    report = package["report"]
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warnings": report["summary"]["warnings"],
                "selected_features": report["outputs"]["selected_features"],
                "rejected_feature_candidates": report["outputs"]["rejected_feature_candidates"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
