from __future__ import annotations

import json
import sys
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from strong_model_segment_analyzer import DEFAULT_POLICY_PATH, read_json, run, write_outputs  # noqa: E402


def main() -> int:
    result = run()
    output_spec = read_json(DEFAULT_POLICY_PATH)["output"]
    write_outputs(result, LESSON_ROOT / "outputs", output_spec)
    summary = result["summary"]
    print(
        json.dumps(
            {
                "audit_valid": result["valid"],
                "segment_analysis_audit_id": summary["segment_analysis_audit_id"],
                "baseline_model_id": summary["baseline_model_id"],
                "early_stopping_model_id": summary["early_stopping_model_id"],
                "analysis_split": summary["analysis_split"],
                "baseline_precision": summary["baseline_precision"],
                "catboost_precision": summary["catboost_precision"],
                "precision_delta": summary["precision_delta"],
                "baseline_recall": summary["baseline_recall"],
                "catboost_recall": summary["catboost_recall"],
                "error_rate_delta": summary["error_rate_delta"],
                "hidden_failure_slice_count": summary["hidden_failure_slice_count"],
                "small_n_slice_count": summary["small_n_slice_count"],
                "score_band_shift_count": summary["score_band_shift_count"],
                "readiness_status": summary["readiness_status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
