from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "streaming_batch_processor.py"
SPEC = importlib.util.spec_from_file_location("streaming_batch_processor", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PROCESSOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROCESSOR)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = PROCESSOR.build_streaming_batch_report(
            rows=1_200,
            batch_size=200,
            users=160,
            seed=2026,
            interrupt_after=2,
            output_dir=tmp,
        )
    preview = {
        "scenario_id": report["scenario"]["scenario_id"],
        "batches": len(report["manifest"]["files"]),
        "checkpointed_before_resume": report["interruption"]["checkpointed_files_before_resume"],
        "resume_skipped": report["resume"]["skipped_files"],
        "batch_matches_pandas": report["correctness"]["batch_vs_pandas"]["matches"],
        "polars_matches_pandas": report["correctness"]["polars_vs_pandas"]["matches"],
        "median_of_medians_matches": report["non_associative_counterexample"][
            "naive_merge_matches"
        ],
        "safe_to_ship": report["interpretation"]["safe_to_ship"],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
