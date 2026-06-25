from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "polars_lazy_plan_audit.py"
SPEC = importlib.util.spec_from_file_location("polars_lazy_plan_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
LAZY_AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAZY_AUDIT)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = LAZY_AUDIT.build_polars_lazy_plan_audit(
            rows=1_200,
            users=160,
            seed=2026,
            output_dir=tmp,
        )
    preview = {
        "scenario_id": report["scenario"]["scenario_id"],
        "polars_version": report["scenario"]["polars_version"],
        "project": report["plan_audit"]["optimized_projection_pushdown"]["raw"],
        "predicate_pushdown": report["plan_audit"]["optimized_has_selection_at_scan"],
        "early_collect": report["source_audit"]["early_materialization_detected"],
        "matches_pandas": report["equivalence"]["matches_pandas"],
        "safe_to_ship": report["interpretation"]["safe_to_ship"],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
