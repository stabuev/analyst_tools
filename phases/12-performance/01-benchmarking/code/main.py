from __future__ import annotations

import importlib.util
from pathlib import Path


ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "benchmark_harness.py"
SPEC = importlib.util.spec_from_file_location("benchmark_harness", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


if __name__ == "__main__":
    report = HARNESS.run_benchmark(rows=2_000, repeat=3, seed=2026)
    print(
        {
            "scenario_id": report["scenario"]["scenario_id"],
            "equivalence_passed": report["equivalence"]["passed"],
            "raw_runs": len(report["measurements"]["raw_runs"]),
            "speedup": report["decision"]["speedup_reference_over_candidate"],
        }
    )
