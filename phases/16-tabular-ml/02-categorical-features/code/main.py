from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = LESSON_ROOT / "outputs"
if str(ARTIFACT_ROOT) not in sys.path:
    sys.path.insert(0, str(ARTIFACT_ROOT))

from categorical_feature_auditor import (  # noqa: E402
    DEFAULT_CONTRACT_PATH,
    read_json,
    run,
    write_outputs,
)


def main() -> None:
    result = run()
    output_spec = read_json(DEFAULT_CONTRACT_PATH)["output"]
    write_outputs(result, ARTIFACT_ROOT, output_spec)

    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "categorical_audit_id": summary["categorical_audit_id"],
                "catboost_model_id": summary["catboost_model_id"],
                "feature_count": summary["feature_count"],
                "unknown_category_row_count": summary["unknown_category_row_count"],
                "high_cardinality_feature_count": summary["high_cardinality_feature_count"],
                "selected_leaky_feature_count": summary["selected_leaky_feature_count"],
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
