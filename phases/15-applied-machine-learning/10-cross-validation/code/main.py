from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from cross_validation_planner import json_ready, run  # noqa: E402


def main() -> None:
    report = run(
        spec_path=DATA_ROOT / "problem_spec.json",
        preprocessing_contract_path=DATA_ROOT / "preprocessing_contract.json",
        pipeline_spec_path=DATA_ROOT / "pipeline_spec.json",
        column_transformer_spec_path=DATA_ROOT / "column_transformer_spec.json",
        linear_baseline_spec_path=DATA_ROOT / "linear_baseline_spec.json",
        tree_diagnostic_spec_path=DATA_ROOT / "tree_diagnostic_spec.json",
        tree_ensemble_spec_path=DATA_ROOT / "tree_ensemble_spec.json",
        cv_plan_spec_path=DATA_ROOT / "cv_plan_spec.json",
        features_path=DATA_ROOT / "ml_raw_features.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        cv_fold_manifest_path=DATA_ROOT / "ml_cv_fold_manifest.csv",
        report_output_path=OUTPUT_ROOT / "cv_report.json",
        fold_manifest_output_path=OUTPUT_ROOT / "cv_fold_manifest.csv",
        score_output_path=OUTPUT_ROOT / "cv_score_report.csv",
        predictions_output_path=OUTPUT_ROOT / "cv_predictions.csv",
        audit_output_path=OUTPUT_ROOT / "cv_no_peeking_audit.csv",
        serialized_spec_output_path=OUTPUT_ROOT / "cv_serialized_spec.json",
    )
    summary = {
        "audit_valid": report["valid"],
        "problem_id": report["problem_id"],
        "cv_plan_id": report["summary"]["cv_plan_id"],
        "sklearn_version": report["summary"]["sklearn_version"],
        "fold_count": report["summary"]["fold_count"],
        "model_id": report["summary"]["model_id"],
        "primary_metric": report["summary"]["primary_metric"],
        "mean_precision_at_budget": report["summary"]["mean_precision_at_budget"],
        "mean_log_loss": report["summary"]["mean_log_loss"],
        "cv_validation_row_count": report["summary"]["cv_validation_row_count"],
        "final_holdout_split": report["summary"]["final_holdout_split"],
        "test_used_in_cv": report["summary"]["test_used_in_cv"],
        "warnings": report["summary"]["warnings"],
        "readiness_status": report["summary"]["readiness_status"],
    }
    print(json.dumps(json_ready(summary), ensure_ascii=False))


if __name__ == "__main__":
    main()
