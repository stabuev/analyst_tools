from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from early_stopping_auditor import DEFAULT_POLICY_PATH, read_json, run, write_outputs  # noqa: E402


def main() -> None:
    result = run()
    write_outputs(result, LESSON_ROOT / "outputs", read_json(DEFAULT_POLICY_PATH)["output"])
    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "early_stopping_audit_id": summary["early_stopping_audit_id"],
                "early_stopping_model_id": summary["early_stopping_model_id"],
                "planned_iterations": summary["planned_iterations"],
                "trained_iteration_count": summary["trained_iteration_count"],
                "best_iteration": summary["best_iteration"],
                "tree_count": summary["tree_count"],
                "stopped_before_budget": summary["stopped_before_budget"],
                "warning_count": len(summary["warnings"]),
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
