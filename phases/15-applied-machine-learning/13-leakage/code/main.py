from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from ml_leakage_auditor import run  # noqa: E402


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
        feature_source_inventory_path=DATA_ROOT / "feature_source_inventory.csv",
        feature_availability_path=DATA_ROOT / "ml_feature_availability.csv",
        feature_selection_log_path=DATA_ROOT / "ml_feature_selection_log.csv",
        model_selection_log_path=DATA_ROOT / "ml_model_selection_log.csv",
        features_path=DATA_ROOT / "ml_raw_features.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        cv_fold_manifest_path=DATA_ROOT / "ml_cv_fold_manifest.csv",
        report_output_path=OUTPUT_ROOT / "leakage_report.json",
        feature_availability_output_path=OUTPUT_ROOT / "feature_availability_report.csv",
        forbidden_feature_output_path=OUTPUT_ROOT / "forbidden_feature_report.csv",
        preprocessing_scope_output_path=OUTPUT_ROOT / "preprocessing_scope_audit.csv",
        feature_selection_output_path=OUTPUT_ROOT / "feature_selection_audit.csv",
        model_selection_output_path=OUTPUT_ROOT / "model_selection_audit.csv",
        audit_output_path=OUTPUT_ROOT / "leakage_policy_audit.csv",
        serialized_spec_output_path=OUTPUT_ROOT / "leakage_serialized_spec.json",
    )
    summary = report["summary"]
    print(
        json.dumps(
            {
                "audit_valid": report["valid"],
                "leakage_policy_id": summary["leakage_policy_id"],
                "source_model_id": summary["source_model_id"],
                "selected_model_id": summary["selected_model_id"],
                "delivery_feature_count": summary["delivery_feature_count"],
                "forbidden_candidate_count": summary["forbidden_candidate_count"],
                "blocked_delivery_feature_count": summary["blocked_delivery_feature_count"],
                "test_used_for_model_selection": summary["test_used_for_model_selection"],
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
