from __future__ import annotations

import json
import sys
from pathlib import Path

LESSON_ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = LESSON_ROOT.parent
DATA_ROOT = PHASE_ROOT / "data" / "tiny"
OUTPUT_ROOT = LESSON_ROOT / "outputs"
sys.path.insert(0, str(OUTPUT_ROOT))

from preprocessing_contract_checker import run  # noqa: E402


def main() -> None:
    report = run(
        spec_path=DATA_ROOT / "problem_spec.json",
        contract_path=DATA_ROOT / "preprocessing_contract.json",
        features_path=DATA_ROOT / "ml_raw_features.csv",
        manifest_path=DATA_ROOT / "ml_split_manifest.csv",
        matrix_output_path=OUTPUT_ROOT / "preprocessed_feature_matrix.csv",
        state_output_path=OUTPUT_ROOT / "preprocessing_state.json",
    )
    output = OUTPUT_ROOT / "preprocessing_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "audit_valid": report["valid"],
        "problem_id": report["problem_id"],
        "contract_id": report["summary"]["contract_id"],
        "fit_split": report["summary"]["fit_split"],
        "fit_row_count": report["summary"]["fit_row_count"],
        "transformed_row_count": report["summary"]["transformed_row_count"],
        "transformed_feature_count": report["summary"]["transformed_feature_count"],
        "unknown_category_events": len(report["summary"]["unknown_category_events"]),
        "blocking_errors": report["summary"]["blocking_errors"],
        "warnings": report["summary"]["warnings"],
        "readiness_status": report["summary"]["readiness_status"],
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
