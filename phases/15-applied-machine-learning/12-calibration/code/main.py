from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from probability_calibration_auditor import run  # noqa: E402


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
        features_path=DATA_ROOT / "ml_raw_features.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        cv_fold_manifest_path=DATA_ROOT / "ml_cv_fold_manifest.csv",
        report_output_path=OUTPUT_ROOT / "calibration_report.json",
        bin_output_path=OUTPUT_ROOT / "calibration_bins.csv",
        metric_output_path=OUTPUT_ROOT / "calibration_metrics.csv",
        predictions_output_path=OUTPUT_ROOT / "calibrated_predictions.csv",
        threshold_output_path=OUTPUT_ROOT / "calibration_threshold_impact.csv",
        audit_output_path=OUTPUT_ROOT / "calibration_policy_audit.csv",
        serialized_spec_output_path=OUTPUT_ROOT / "calibration_serialized_spec.json",
    )
    summary = report["summary"]
    print(
        json.dumps(
            {
                "audit_valid": report["valid"],
                "calibration_policy_id": summary["calibration_policy_id"],
                "source_model_id": summary["source_model_id"],
                "uncalibrated_test_brier": summary["uncalibrated_test_brier"],
                "calibrated_test_brier": summary["calibrated_test_brier"],
                "test_fixed_threshold_0_5_action_count_uncalibrated": summary[
                    "test_fixed_threshold_0_5_action_count_uncalibrated"
                ],
                "test_fixed_threshold_0_5_action_count_calibrated": summary[
                    "test_fixed_threshold_0_5_action_count_calibrated"
                ],
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
