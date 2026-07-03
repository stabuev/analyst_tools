from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from segment_error_analyzer import run  # noqa: E402


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
        imbalance_policy_spec_path=DATA_ROOT / "imbalance_policy_spec.json",
        calibration_policy_spec_path=DATA_ROOT / "calibration_policy_spec.json",
        leakage_policy_spec_path=DATA_ROOT / "leakage_policy_spec.json",
        error_analysis_policy_spec_path=DATA_ROOT / "error_analysis_policy_spec.json",
        feature_source_inventory_path=DATA_ROOT / "feature_source_inventory.csv",
        feature_availability_path=DATA_ROOT / "ml_feature_availability.csv",
        feature_selection_log_path=DATA_ROOT / "ml_feature_selection_log.csv",
        model_selection_log_path=DATA_ROOT / "ml_model_selection_log.csv",
        features_path=DATA_ROOT / "ml_raw_features.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        cv_fold_manifest_path=DATA_ROOT / "ml_cv_fold_manifest.csv",
        snapshots_path=DATA_ROOT / "ml_scoring_snapshots.csv",
        report_output_path=OUTPUT_ROOT / "error_analysis_report.json",
        confusion_row_output_path=OUTPUT_ROOT / "confusion_rows.csv",
        slice_metric_output_path=OUTPUT_ROOT / "slice_metrics.csv",
        small_n_warning_output_path=OUTPUT_ROOT / "small_n_warnings.csv",
        hidden_failure_output_path=OUTPUT_ROOT / "hidden_failure_slices.csv",
        error_example_output_path=OUTPUT_ROOT / "error_examples.csv",
        audit_output_path=OUTPUT_ROOT / "error_analysis_policy_audit.csv",
        serialized_spec_output_path=OUTPUT_ROOT / "error_analysis_serialized_spec.json",
    )
    summary = report["summary"]
    print(
        json.dumps(
            {
                "audit_valid": report["valid"],
                "error_analysis_policy_id": summary["error_analysis_policy_id"],
                "analysis_split": summary["analysis_split"],
                "row_count": summary["row_count"],
                "overall_precision": summary["overall_precision"],
                "overall_recall": summary["overall_recall"],
                "false_positive_count": summary["false_positive_count"],
                "false_negative_count": summary["false_negative_count"],
                "small_n_slice_count": summary["small_n_slice_count"],
                "hidden_failure_slice_count": summary["hidden_failure_slice_count"],
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
