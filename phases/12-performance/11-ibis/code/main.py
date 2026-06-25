from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "performance_benchmark_packager.py"
SPEC = importlib.util.spec_from_file_location(
    "performance_benchmark_packager",
    ARTIFACT,
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PACKAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGER)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        report = PACKAGER.build_performance_benchmark_package(
            dataset_profile="tiny",
            rows=1_200,
            users=160,
            seed=2026,
            repeat=3,
            warmup=1,
            row_group_size=256,
            output_dir=tmp,
        )
    preview = {
        "scenario_id": report["scenario"]["scenario_id"],
        "ibis_version": report["environment"]["versions"]["ibis"],
        "engines": [row["engine"] for row in report["measurements"]["summary"]],
        "portable_core": report["portability"]["portable_core"]["portable_on_tested_backends"],
        "rank_divergence": report["portability"]["window_rank_probe"]["divergence_detected"],
        "decision": report["decision"]["decision"],
        "manifest_files": report["package"]["manifest_files"],
        "safe_to_ship": report["interpretation"]["safe_to_ship"],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
