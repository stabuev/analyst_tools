from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "duckdb_out_of_core_report.py"
SPEC = importlib.util.spec_from_file_location("duckdb_out_of_core_report", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DUCKDB_REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DUCKDB_REPORT)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = DUCKDB_REPORT.build_duckdb_out_of_core_report(
            rows=2_400,
            users=240,
            seed=2026,
            memory_limit="64MB",
            threads=1,
            output_dir=tmp,
        )
    preview = {
        "scenario_id": report["scenario"]["scenario_id"],
        "duckdb_version": report["scenario"]["duckdb_version"],
        "memory_limit": report["settings"]["memory_limit"],
        "threads": report["settings"]["threads"],
        "blocking_operators": [
            item["operator"]
            for item in report["plan"]["blocking_operators"]
        ],
        "profile_has_runtime_evidence": report["profile"]["has_runtime_evidence"],
        "result_matches_control": report["equivalence"]["matches_control"],
        "spill_ready": report["interpretation"]["spill_ready"],
        "spill_observed": report["interpretation"]["spill_observed"],
        "safe_to_ship": report["interpretation"]["safe_to_ship"],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
