from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "arrow_memory_inspector.py"
SPEC = importlib.util.spec_from_file_location("arrow_memory_inspector", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
ARROW_MEMORY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARROW_MEMORY)


def main() -> None:
    report = ARROW_MEMORY.build_arrow_memory_report(rows=48, chunk_size=16, seed=2026)
    preview = {
        "scenario_id": report["scenario"]["scenario_id"],
        "rows": report["scenario"]["rows"],
        "columns": report["table"]["columns"],
        "table_nbytes": report["table"]["nbytes"],
        "zero_copy_numpy": report["copy_audit"]["zero_copy_numpy"]["shares_arrow_values_buffer"],
        "combine_chunks_requires_copy": report["copy_audit"]["combine_chunks"]["requires_copy"],
        "safe_to_ship": report["interpretation"]["safe_to_ship"],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
