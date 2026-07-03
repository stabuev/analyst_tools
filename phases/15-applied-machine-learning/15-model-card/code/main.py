from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = LESSON_ROOT / "outputs"
if str(ARTIFACT_ROOT) not in sys.path:
    sys.path.insert(0, str(ARTIFACT_ROOT))

from ml_baseline_packager import (  # noqa: E402
    DATA_ROOT,
    DEFAULT_REPORT_PATHS,
    DEFAULT_TABLE_PATHS,
    build_ml_baseline_package,
    read_json,
    write_outputs,
)


def main() -> None:
    package_spec_path = DATA_ROOT / "ml_baseline_package_spec.json"
    result = build_ml_baseline_package(
        package_spec_path=package_spec_path,
        problem_spec_path=DATA_ROOT / "problem_spec.json",
        report_paths=DEFAULT_REPORT_PATHS,
        table_paths=DEFAULT_TABLE_PATHS,
    )
    spec = read_json(package_spec_path)
    write_outputs(result, ARTIFACT_ROOT, spec["output"])
    summary = result["report"]["summary"]
    print(
        json.dumps(
            {
                "package_valid": result["report"]["valid"],
                "package_id": summary["package_id"],
                "model_card_id": summary["model_card_id"],
                "decision_status": summary["decision_status"],
                "evidence_row_count": summary["evidence_row_count"],
                "risk_row_count": summary["risk_row_count"],
                "hidden_failure_slice_count": summary["hidden_failure_slice_count"],
                "production_ready": summary["production_ready"],
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
