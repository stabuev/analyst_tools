from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from built_in_importance_reporter import DEFAULT_POLICY_PATH, read_json, run, write_outputs  # noqa: E402


def main() -> None:
    result = run()
    write_outputs(result, LESSON_ROOT / "outputs", read_json(DEFAULT_POLICY_PATH)["output"])
    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "built_in_importance_audit_id": summary["built_in_importance_audit_id"],
                "early_stopping_model_id": summary["early_stopping_model_id"],
                "method_count": summary["method_count"],
                "feature_count": summary["feature_count"],
                "importance_row_count": summary["importance_row_count"],
                "top_prediction_values_change_feature": summary["top_prediction_values_change_feature"],
                "top_loss_function_change_feature": summary["top_loss_function_change_feature"],
                "warning_count": len(summary["warnings"]),
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
