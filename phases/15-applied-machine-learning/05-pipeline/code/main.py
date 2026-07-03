from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from pipeline_runner import run  # noqa: E402


def main() -> None:
    report = run(
        spec_path=DATA_ROOT / "problem_spec.json",
        preprocessing_contract_path=DATA_ROOT / "preprocessing_contract.json",
        pipeline_spec_path=DATA_ROOT / "pipeline_spec.json",
        features_path=DATA_ROOT / "ml_raw_features.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        predictions_output_path=OUTPUT_ROOT / "pipeline_predictions.csv",
        serialized_spec_output_path=OUTPUT_ROOT / "pipeline_serialized_spec.json",
    )
    output = OUTPUT_ROOT / "pipeline_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "audit_valid": report["valid"],
        "problem_id": report["problem_id"],
        "pipeline_id": report["summary"]["pipeline_id"],
        "sklearn_version": report["summary"]["sklearn_version"],
        "fit_split": report["summary"]["fit_split"],
        "fit_row_count": report["summary"]["fit_row_count"],
        "prediction_row_count": report["summary"]["prediction_row_count"],
        "transformed_feature_count": report["summary"]["transformed_feature_count"],
        "validation_score_mean": report["summary"]["score_summary_by_split"]["validation"]["mean"],
        "test_score_mean": report["summary"]["score_summary_by_split"]["test"]["mean"],
        "blocking_errors": report["summary"]["blocking_errors"],
        "warnings": report["summary"]["warnings"],
        "readiness_status": report["summary"]["readiness_status"],
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
