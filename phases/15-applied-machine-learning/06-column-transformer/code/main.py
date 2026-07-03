from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from column_transformer_auditor import run  # noqa: E402


def main() -> None:
    report = run(
        spec_path=DATA_ROOT / "problem_spec.json",
        preprocessing_contract_path=DATA_ROOT / "preprocessing_contract.json",
        pipeline_spec_path=DATA_ROOT / "pipeline_spec.json",
        column_transformer_spec_path=DATA_ROOT / "column_transformer_spec.json",
        features_path=DATA_ROOT / "ml_raw_features.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        report_output_path=OUTPUT_ROOT / "column_transformer_report.json",
        routing_output_path=OUTPUT_ROOT / "column_transformer_routing.csv",
        feature_schema_output_path=OUTPUT_ROOT / "column_transformer_feature_schema.csv",
        predictions_output_path=OUTPUT_ROOT / "column_transformer_predictions.csv",
        serialized_spec_output_path=OUTPUT_ROOT / "column_transformer_serialized_spec.json",
    )
    summary = {
        "audit_valid": report["valid"],
        "problem_id": report["problem_id"],
        "column_transformer_id": report["summary"]["column_transformer_id"],
        "sklearn_version": report["summary"]["sklearn_version"],
        "fit_split": report["summary"]["fit_split"],
        "fit_row_count": report["summary"]["fit_row_count"],
        "routed_input_feature_count": report["summary"]["routed_input_feature_count"],
        "transformed_feature_count": report["summary"]["transformed_feature_count"],
        "prediction_row_count": report["summary"]["prediction_row_count"],
        "dropped_columns": report["summary"]["dropped_columns"],
        "validation_score_mean": report["summary"]["score_summary_by_split"]["validation"]["mean"],
        "test_score_mean": report["summary"]["score_summary_by_split"]["test"]["mean"],
        "blocking_errors": report["summary"]["blocking_errors"],
        "warnings": report["summary"]["warnings"],
        "readiness_status": report["summary"]["readiness_status"],
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
