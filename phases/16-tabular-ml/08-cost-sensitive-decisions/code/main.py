from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from cost_sensitive_decision_evaluator import DEFAULT_POLICY_PATH, read_json, run, write_outputs  # noqa: E402


def main() -> int:
    result = run()
    output_spec = read_json(DEFAULT_POLICY_PATH)["output"]
    write_outputs(result, LESSON_ROOT / "outputs", output_spec)
    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "cost_sensitive_decision_audit_id": summary["cost_sensitive_decision_audit_id"],
                "analysis_split": summary["analysis_split"],
                "baseline_selected_threshold": summary["baseline_selected_threshold"],
                "catboost_selected_threshold": summary["catboost_selected_threshold"],
                "baseline_best_total_error_cost": summary["baseline_best_total_error_cost"],
                "catboost_best_total_error_cost": summary["catboost_best_total_error_cost"],
                "candidate_cost_delta_vs_baseline": summary["candidate_cost_delta_vs_baseline"],
                "baseline_top_k_total_error_cost": summary["baseline_top_k_total_error_cost"],
                "catboost_top_k_total_error_cost": summary["catboost_top_k_total_error_cost"],
                "candidate_top_k_cost_delta_vs_baseline": summary["candidate_top_k_cost_delta_vs_baseline"],
                "decision_status": summary["decision_status"],
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
