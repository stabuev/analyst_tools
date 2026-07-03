from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from imbalance_policy_evaluator import json_ready, run  # noqa: E402


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
        features_path=DATA_ROOT / "ml_raw_features.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        cv_fold_manifest_path=DATA_ROOT / "ml_cv_fold_manifest.csv",
        report_output_path=OUTPUT_ROOT / "imbalance_report.json",
        distribution_output_path=OUTPUT_ROOT / "class_distribution.csv",
        baseline_trap_output_path=OUTPUT_ROOT / "baseline_trap_report.csv",
        threshold_output_path=OUTPUT_ROOT / "imbalance_threshold_report.csv",
        predictions_output_path=OUTPUT_ROOT / "imbalance_predictions.csv",
        audit_output_path=OUTPUT_ROOT / "imbalance_policy_audit.csv",
        serialized_spec_output_path=OUTPUT_ROOT / "imbalance_serialized_spec.json",
    )
    summary = {
        "audit_valid": report["valid"],
        "problem_id": report["problem_id"],
        "imbalance_policy_id": report["summary"]["imbalance_policy_id"],
        "sklearn_version": report["summary"]["sklearn_version"],
        "selected_model_id": report["summary"]["selected_model_id"],
        "primary_metric": report["summary"]["primary_metric"],
        "test_positive_rate": report["summary"]["test_positive_rate"],
        "always_negative_test_accuracy": report["summary"]["always_negative_test_accuracy"],
        "always_negative_test_positive_recall": report["summary"][
            "always_negative_test_positive_recall"
        ],
        "validation_precision_at_budget": report["summary"]["validation_precision_at_budget"],
        "test_precision_at_budget": report["summary"]["test_precision_at_budget"],
        "test_fixed_threshold_0_5_action_count": report["summary"][
            "test_fixed_threshold_0_5_action_count"
        ],
        "warnings": report["summary"]["warnings"],
        "readiness_status": report["summary"]["readiness_status"],
    }
    print(json.dumps(json_ready(summary), ensure_ascii=False))


if __name__ == "__main__":
    main()
