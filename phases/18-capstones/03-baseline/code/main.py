from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_baseline_gate.py"


def load_gate():
    spec = importlib.util.spec_from_file_location("capstone_baseline_gate", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    gate = load_gate()
    with TemporaryDirectory() as directory:
        inputs = gate.write_sample_inputs(Path(directory) / "input")
        result = gate.build_baseline_package(
            upstream_data_package=inputs["upstream_data_package"],
            baseline_spec_path=inputs["baseline_spec_path"],
            output_dir=LESSON_ROOT / "outputs",
        )
    report = result["report"]
    payload = {
        "status": report["status"],
        "valid": report["valid"],
        "project_id": report["project_id"],
        "baseline_id": report["baseline_id"],
        "selected_segments": report["summary"]["selected_segments"],
        "baseline_value": report["summary"]["baseline_value"],
        "candidate_threshold": report["summary"]["candidate_threshold"],
        "warnings": report["summary"]["warnings"],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
