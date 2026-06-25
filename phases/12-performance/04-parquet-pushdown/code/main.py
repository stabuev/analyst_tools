from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "parquet_pushdown_audit.py"
SPEC = importlib.util.spec_from_file_location("parquet_pushdown_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PUSHDOWN_AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PUSHDOWN_AUDIT)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = PUSHDOWN_AUDIT.build_pushdown_audit(
            rows=2_400,
            seed=2026,
            row_group_size=96,
            target_week="2026-02-02",
            output_dir=tmp,
        )
    preview = {
        "scenario_id": report["scenario"]["scenario_id"],
        "files": report["layout"]["file_count"],
        "row_groups": report["layout"]["row_group_count"],
        "projected_columns": report["projection"]["projected_column_count"],
        "candidate_files": report["predicate_pushdown"]["partition_pruning"]["candidate_file_count"],
        "candidate_row_groups": report["predicate_pushdown"]["row_group_statistics"]["candidate_row_group_count"],
        "safe_to_ship": report["interpretation"]["safe_to_ship"],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
