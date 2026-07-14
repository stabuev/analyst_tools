from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from shap_explanation_reporter import DEFAULT_POLICY_PATH, read_json, run, write_outputs  # noqa: E402


def main() -> int:
    result = run()
    output_spec = read_json(DEFAULT_POLICY_PATH)["output"]
    write_outputs(result, LESSON_ROOT / "outputs", output_spec)
    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "shap_explanation_audit_id": summary["shap_explanation_audit_id"],
                "early_stopping_model_id": summary["early_stopping_model_id"],
                "explain_split": summary["explain_split"],
                "background_row_count": summary["background_row_count"],
                "explain_row_count": summary["explain_row_count"],
                "output_space": summary["output_space"],
                "expected_value": summary["expected_value"],
                "additivity_max_abs_error": summary["additivity_max_abs_error"],
                "top_mean_abs_shap_feature": summary["top_mean_abs_shap_feature"],
                "disagreement_status": summary["disagreement_status"],
                "warning_count": len(summary["warnings"]),
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
