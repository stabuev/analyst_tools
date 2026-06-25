from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dtype_policy.py"
SPEC = importlib.util.spec_from_file_location("dtype_policy", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DTYPE_POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DTYPE_POLICY)


def main() -> None:
    report = DTYPE_POLICY.build_schema_optimization_plan(
        rows=2_000,
        seed=2026,
        memory_budget_mb=2.0,
    )
    preview = {
        "scenario_id": report["scenario"]["scenario_id"],
        "baseline_bytes": report["baseline"]["total_bytes"],
        "optimized_bytes": report["optimized"]["total_bytes"],
        "reduction_percent": round(report["optimized"]["reduction_percent"], 2),
        "safe_to_ship": report["interpretation"]["safe_to_ship"],
        "memory_budget": report["memory_budget"]["severity"],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
