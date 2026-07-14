from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from tabular_ml_interpretation_packager import build_tabular_ml_package, write_outputs  # noqa: E402


def main() -> None:
    result = build_tabular_ml_package()
    write_outputs(result, LESSON_ROOT / "outputs", result["output"])
    report = result["report"]
    summary = report["summary"]
    print(
        json.dumps(
            {
                "package_valid": report["valid"],
                "package_id": summary["package_id"],
                "decision_status": report["decision_status"],
                "monitoring_status": summary["monitoring_status"],
                "evidence_row_count": summary["evidence_row_count"],
                "feature_drift_watch_count": summary["feature_drift_watch_count"],
                "importance_stability_watch_count": summary["importance_stability_watch_count"],
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
