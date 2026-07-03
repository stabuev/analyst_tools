from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from linear_baseline_trainer import run  # noqa: E402


def main() -> None:
    report = run(
        spec_path=DATA_ROOT / "problem_spec.json",
        preprocessing_contract_path=DATA_ROOT / "preprocessing_contract.json",
        pipeline_spec_path=DATA_ROOT / "pipeline_spec.json",
        column_transformer_spec_path=DATA_ROOT / "column_transformer_spec.json",
        linear_baseline_spec_path=DATA_ROOT / "linear_baseline_spec.json",
        features_path=DATA_ROOT / "ml_raw_features.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        report_output_path=OUTPUT_ROOT / "baseline_report.json",
        comparison_output_path=OUTPUT_ROOT / "baseline_comparison.csv",
        coefficients_output_path=OUTPUT_ROOT / "coefficient_table.csv",
        predictions_output_path=OUTPUT_ROOT / "baseline_predictions.csv",
        serialized_spec_output_path=OUTPUT_ROOT / "linear_baseline_serialized_spec.json",
    )
    summary = {
        "audit_valid": report["valid"],
        "problem_id": report["problem_id"],
        "linear_baseline_id": report["summary"]["linear_baseline_id"],
        "sklearn_version": report["summary"]["sklearn_version"],
        "fit_split": report["summary"]["fit_split"],
        "fit_row_count": report["summary"]["fit_row_count"],
        "selection_split": report["summary"]["selection_split"],
        "selected_model_id": report["summary"]["selected_model_id"],
        "candidate_model_ids": report["summary"]["candidate_model_ids"],
        "selection_budget": report["summary"]["selection_budget"],
        "transformed_feature_count": report["summary"]["transformed_feature_count"],
        "coefficient_row_count": report["summary"]["coefficient_row_count"],
        "prediction_row_count": report["summary"]["prediction_row_count"],
        "validation_precision_at_budget": report["summary"]["validation_metrics"][
            "precision_at_budget"
        ],
        "validation_log_loss": report["summary"]["validation_metrics"]["log_loss"],
        "warnings": report["summary"]["warnings"],
        "readiness_status": report["summary"]["readiness_status"],
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
