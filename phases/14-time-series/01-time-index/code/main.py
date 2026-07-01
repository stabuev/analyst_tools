from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from time_index_auditor import audit_time_index  # noqa: E402


def main() -> None:
    report = audit_time_index(
        metrics_path=PHASE_ROOT / "data" / "tiny" / "metric_observations.csv",
        calendar_path=PHASE_ROOT / "data" / "tiny" / "calendar.csv",
        scenario_path=PHASE_ROOT / "data" / "tiny" / "forecast_scenario.json",
        revisions_path=PHASE_ROOT / "data" / "tiny" / "data_revisions.csv",
    )
    output = LESSON_ROOT / "outputs" / "time_index_audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": report["valid"], "warnings": report["summary"]["warnings"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
