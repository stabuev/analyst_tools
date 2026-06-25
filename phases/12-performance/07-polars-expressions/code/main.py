from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "polars_expression_pipeline.py"
SPEC = importlib.util.spec_from_file_location("polars_expression_pipeline", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
POLARS_PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLARS_PIPELINE)


def main() -> None:
    report = POLARS_PIPELINE.build_polars_expression_report(
        rows=1_200,
        users=160,
        seed=2026,
    )
    preview = {
        "scenario_id": report["scenario"]["scenario_id"],
        "polars_version": report["scenario"]["polars_version"],
        "contexts": report["expression_audit"]["contexts"],
        "row_wise_python_detected": report["expression_audit"]["row_wise_python_detected"],
        "matches_pandas": report["equivalence"]["matches_pandas"],
        "rows": report["equivalence"]["polars_rows"],
        "safe_to_ship": report["interpretation"]["safe_to_ship"],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
