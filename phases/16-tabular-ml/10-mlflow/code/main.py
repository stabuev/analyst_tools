from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from mlflow_experiment_ledger_exporter import DEFAULT_POLICY_PATH, read_json, run, write_outputs  # noqa: E402


def main() -> int:
    result = run()
    output_spec = read_json(DEFAULT_POLICY_PATH)["output"]
    write_outputs(result, LESSON_ROOT / "outputs", output_spec)
    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "mlflow_tracking_audit_id": summary["mlflow_tracking_audit_id"],
                "mlflow_version": summary["mlflow_version"],
                "tracking_package": summary["tracking_package"],
                "experiment_name": summary["experiment_name"],
                "run_count": summary["run_count"],
                "raw_run_ids_exported": summary["raw_run_ids_exported"],
                "best_run_alias": summary["best_run_alias"],
                "best_validation_logloss": summary["best_validation_logloss"],
                "best_trial_validation_top_k_cost": summary["best_trial_validation_top_k_cost"],
                "baseline_validation_top_k_cost": summary["baseline_validation_top_k_cost"],
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
