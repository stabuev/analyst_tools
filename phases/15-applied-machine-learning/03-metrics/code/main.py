from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from classification_metric_evaluator import run  # noqa: E402


def main() -> None:
    report = run(
        spec_path=DATA_ROOT / "problem_spec.json",
        snapshots_path=DATA_ROOT / "ml_scoring_snapshots.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        scores_path=DATA_ROOT / "ml_candidate_scores.csv",
    )
    output = OUTPUT_ROOT / "classification_metric_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "audit_valid": report["valid"],
        "problem_id": report["problem_id"],
        "model_id": report["summary"]["model_id"],
        "selected_threshold": report["summary"]["selected_threshold"],
        "threshold_selected_on": report["summary"]["threshold_selected_on"],
        "validation_precision": report["summary"]["metrics_at_selected_threshold"]["validation"][
            "precision"
        ],
        "test_precision": report["summary"]["metrics_at_selected_threshold"]["test"]["precision"],
        "test_recall": report["summary"]["metrics_at_selected_threshold"]["test"]["recall"],
        "blocking_errors": report["summary"]["blocking_errors"],
        "warnings": report["summary"]["warnings"],
        "readiness_status": report["summary"]["readiness_status"],
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
