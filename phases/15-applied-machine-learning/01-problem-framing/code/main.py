from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from ml_problem_spec_validator import run  # noqa: E402


def main() -> None:
    report = run(
        spec_path=DATA_ROOT / "problem_spec.json",
        snapshots_path=DATA_ROOT / "ml_scoring_snapshots.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        feature_sources_path=DATA_ROOT / "feature_source_inventory.csv",
    )
    output = LESSON_ROOT / "outputs" / "ml_problem_readiness_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload = {
        "audit_valid": report["valid"],
        "problem_id": report["summary"]["problem_id"],
        "eligible_prediction_rows": report["summary"]["eligible_prediction_rows"],
        "positive_labels": report["summary"]["positive_labels"],
        "blocking_errors": report["summary"]["blocking_errors"],
        "warnings": report["summary"]["warnings"],
        "readiness_status": report["summary"]["readiness_status"],
    }
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
