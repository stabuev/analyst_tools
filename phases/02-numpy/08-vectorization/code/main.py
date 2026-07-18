from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "vectorization_benchmark.py"
SPEC = importlib.util.spec_from_file_location("vectorization_benchmark", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


if __name__ == "__main__":
    report = BENCHMARK.benchmark(size=100_000, repeat=7, seed=42)
    print(json.dumps(report, ensure_ascii=False, indent=2))
