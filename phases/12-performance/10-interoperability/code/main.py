from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "interoperability_audit.py"
SPEC = importlib.util.spec_from_file_location(
    "interoperability_audit",
    ARTIFACT,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = AUDIT.build_interoperability_report(
            rows=24,
            chunk_size=8,
            seed=2026,
            output_dir=tmp,
        )
    boundaries = {item["boundary_id"]: item for item in report["boundaries"]}
    preview = {
        "scenario_id": report["scenario"]["scenario_id"],
        "selected_path": report["decision"]["selected_path"],
        "pandas_full_reuse_columns": boundaries["arrow_to_pandas"]["buffer_reuse"][
            "columns_with_full_source_reuse"
        ],
        "polars_reuse_columns": boundaries["arrow_to_polars"]["buffer_reuse"][
            "columns_with_any_reuse"
        ],
        "duckdb_category_family": boundaries["arrow_to_duckdb"]["column_type_checks"]["plan_tier"][
            "target_family"
        ],
        "timezone_counterexample": report["decision"]["timezone_counterexample_detected"],
        "safe_to_ship": report["interpretation"]["safe_to_ship"],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
