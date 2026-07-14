from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = LESSON_ROOT / "outputs"
if str(ARTIFACT_ROOT) not in sys.path:
    sys.path.insert(0, str(ARTIFACT_ROOT))

from catboost_baseline_trainer import (  # noqa: E402
    DEFAULT_SPEC_PATH,
    read_json,
    run,
    write_outputs,
)


def main() -> None:
    result = run()
    output_spec = read_json(DEFAULT_SPEC_PATH)["output"]
    write_outputs(result, ARTIFACT_ROOT, output_spec)

    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "catboost_baseline_id": summary["catboost_baseline_id"],
                "model_id": summary["model_id"],
                "fit_row_count": summary["fit_row_count"],
                "cat_features": summary["cat_features"],
                "selected_model_id": summary["selected_model_id"],
                "catboost_validation_precision_at_budget": summary[
                    "catboost_validation_precision_at_budget"
                ],
                "baseline_validation_precision_at_budget": summary[
                    "baseline_validation_precision_at_budget"
                ],
                "test_used_for_selection": summary["test_used_for_selection"],
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
