from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from optuna_tuning_auditor import DEFAULT_POLICY_PATH, read_json, run, write_outputs  # noqa: E402


def main() -> int:
    result = run()
    output_spec = read_json(DEFAULT_POLICY_PATH)["output"]
    write_outputs(result, LESSON_ROOT / "outputs", output_spec)
    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "optuna_tuning_audit_id": summary["optuna_tuning_audit_id"],
                "study_name": summary["study_name"],
                "n_trials": summary["n_trials"],
                "objective_split": summary["objective_split"],
                "test_used_for_objective": summary["test_used_for_objective"],
                "source_validation_logloss": summary["source_validation_logloss"],
                "best_trial_number": summary["best_trial_number"],
                "best_validation_logloss": summary["best_validation_logloss"],
                "best_depth": summary["best_depth"],
                "best_learning_rate": summary["best_learning_rate"],
                "best_trial_validation_top_k_cost": summary["best_trial_validation_top_k_cost"],
                "cost_gate_still_fails_vs_baseline": summary["cost_gate_still_fails_vs_baseline"],
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
