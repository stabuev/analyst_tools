from __future__ import annotations

import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from decomposition_reporter import build_decomposition_package, write_package  # noqa: E402


def main() -> None:
    package = build_decomposition_package(
        series_path=PHASE_ROOT / "02-resampling" / "outputs" / "daily_resampled.csv",
        scenario_path=PHASE_ROOT / "data" / "tiny" / "forecast_scenario.json",
        cutoff_contract_path=PHASE_ROOT / "05-temporal-leakage" / "outputs" / "cutoff_contract.json",
        baseline_report_path=PHASE_ROOT / "06-forecast-baselines" / "outputs" / "baseline_report.json",
        spec_path=PHASE_ROOT / "data" / "tiny" / "decomposition_spec.json",
    )
    write_package(package, LESSON_ROOT / "outputs")
    report = package["report"]
    print(
        {
            "valid": report["valid"],
            "warnings": report["summary"]["warnings"],
            "component_rows": report["outputs"]["component_rows"],
            "diagnostics_rows": report["outputs"]["diagnostics_rows"],
            "method_id": report["outputs"]["method_id"],
        }
    )


if __name__ == "__main__":
    main()
