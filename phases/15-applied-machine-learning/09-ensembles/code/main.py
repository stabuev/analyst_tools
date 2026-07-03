from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from tree_ensemble_comparator import json_ready, run  # noqa: E402


def main() -> None:
    report = run(
        spec_path=DATA_ROOT / "problem_spec.json",
        preprocessing_contract_path=DATA_ROOT / "preprocessing_contract.json",
        pipeline_spec_path=DATA_ROOT / "pipeline_spec.json",
        column_transformer_spec_path=DATA_ROOT / "column_transformer_spec.json",
        linear_baseline_spec_path=DATA_ROOT / "linear_baseline_spec.json",
        tree_diagnostic_spec_path=DATA_ROOT / "tree_diagnostic_spec.json",
        tree_ensemble_spec_path=DATA_ROOT / "tree_ensemble_spec.json",
        features_path=DATA_ROOT / "ml_raw_features.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        report_output_path=OUTPUT_ROOT / "ensemble_report.json",
        comparison_output_path=OUTPUT_ROOT / "ensemble_comparison.csv",
        stability_output_path=OUTPUT_ROOT / "ensemble_stability_report.csv",
        feature_importance_output_path=OUTPUT_ROOT / "ensemble_feature_importance.csv",
        slice_metrics_output_path=OUTPUT_ROOT / "ensemble_slice_metrics.csv",
        predictions_output_path=OUTPUT_ROOT / "ensemble_predictions.csv",
        serialized_spec_output_path=OUTPUT_ROOT / "ensemble_serialized_spec.json",
    )
    summary = {
        "audit_valid": report["valid"],
        "problem_id": report["problem_id"],
        "tree_ensemble_id": report["summary"]["tree_ensemble_id"],
        "sklearn_version": report["summary"]["sklearn_version"],
        "fit_split": report["summary"]["fit_split"],
        "fit_row_count": report["summary"]["fit_row_count"],
        "model_id": report["summary"]["model_id"],
        "n_estimators": report["summary"]["n_estimators"],
        "max_depth_limit": report["summary"]["max_depth_limit"],
        "selected_model_id": report["summary"]["selected_model_id"],
        "selected_model_source": report["summary"]["selected_model_source"],
        "ensemble_validation_precision_at_budget": report["summary"][
            "ensemble_validation_precision_at_budget"
        ],
        "tree_validation_precision_at_budget": report["summary"][
            "tree_validation_precision_at_budget"
        ],
        "stability_range": report["summary"]["stability_range"],
        "top_mdi_feature": report["summary"]["top_mdi_feature"],
        "top_permutation_feature": report["summary"]["top_permutation_feature"],
        "small_n_slice_count": report["summary"]["small_n_slice_count"],
        "warnings": report["summary"]["warnings"],
        "readiness_status": report["summary"]["readiness_status"],
    }
    print(json.dumps(json_ready(summary), ensure_ascii=False))


if __name__ == "__main__":
    main()
