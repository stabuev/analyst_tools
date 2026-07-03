from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from tree_diagnostic_trainer import json_ready, run  # noqa: E402


def main() -> None:
    report = run(
        spec_path=DATA_ROOT / "problem_spec.json",
        preprocessing_contract_path=DATA_ROOT / "preprocessing_contract.json",
        pipeline_spec_path=DATA_ROOT / "pipeline_spec.json",
        column_transformer_spec_path=DATA_ROOT / "column_transformer_spec.json",
        linear_baseline_spec_path=DATA_ROOT / "linear_baseline_spec.json",
        tree_diagnostic_spec_path=DATA_ROOT / "tree_diagnostic_spec.json",
        features_path=DATA_ROOT / "ml_raw_features.csv",
        labels_path=DATA_ROOT / "ml_labels.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        report_output_path=OUTPUT_ROOT / "tree_report.json",
        overfit_output_path=OUTPUT_ROOT / "tree_overfit_report.csv",
        node_output_path=OUTPUT_ROOT / "tree_node_report.csv",
        rules_output_path=OUTPUT_ROOT / "tree_rules.txt",
        predictions_output_path=OUTPUT_ROOT / "tree_predictions.csv",
        serialized_spec_output_path=OUTPUT_ROOT / "tree_serialized_spec.json",
    )
    summary = {
        "audit_valid": report["valid"],
        "problem_id": report["problem_id"],
        "tree_diagnostic_id": report["summary"]["tree_diagnostic_id"],
        "sklearn_version": report["summary"]["sklearn_version"],
        "fit_split": report["summary"]["fit_split"],
        "fit_row_count": report["summary"]["fit_row_count"],
        "model_id": report["summary"]["model_id"],
        "max_depth_limit": report["summary"]["max_depth_limit"],
        "actual_tree_depth": report["summary"]["actual_tree_depth"],
        "leaf_count": report["summary"]["leaf_count"],
        "split_features": report["summary"]["split_features"],
        "selected_linear_baseline_id": report["summary"]["selected_linear_baseline_id"],
        "tree_validation_precision_at_budget": report["summary"][
            "tree_validation_precision_at_budget"
        ],
        "baseline_validation_precision_at_budget": report["summary"][
            "baseline_validation_precision_at_budget"
        ],
        "train_validation_gaps": report["summary"]["train_validation_gaps"],
        "prediction_row_count": report["summary"]["prediction_row_count"],
        "rule_line_count": report["summary"]["rule_line_count"],
        "warnings": report["summary"]["warnings"],
        "readiness_status": report["summary"]["readiness_status"],
    }
    print(json.dumps(json_ready(summary), ensure_ascii=False))


if __name__ == "__main__":
    main()
