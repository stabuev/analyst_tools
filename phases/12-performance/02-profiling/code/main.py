from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "profiling_report.py"
SPEC = importlib.util.spec_from_file_location("profiling_report", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PROFILING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILING)


def main() -> None:
    report = PROFILING.profile_pipeline(
        rows=1_500,
        seed=2026,
        top_n=5,
        memory_budget_mb=8.0,
    )
    top_cpu = report["findings"][0]["evidence"]
    preview = {
        "scenario_id": report["scenario"]["scenario_id"],
        "output_rows": report["result_contract"]["output_rows"],
        "top_cpu_function": top_cpu["function"],
        "peak_bytes": report["memory_profile"]["peak_bytes"],
        "findings": len(report["findings"]),
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
