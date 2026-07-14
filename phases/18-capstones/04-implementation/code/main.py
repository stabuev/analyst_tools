from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_route_implementation.py"


def load_implementation():
    spec = importlib.util.spec_from_file_location("capstone_route_implementation", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    implementation = load_implementation()
    with TemporaryDirectory() as directory:
        inputs = implementation.write_sample_inputs(Path(directory) / "input")
        result = implementation.build_implementation_package(
            upstream_baseline_package=inputs["upstream_baseline_package"],
            implementation_spec_path=inputs["implementation_spec_path"],
            output_dir=LESSON_ROOT / "outputs",
        )
    report = result["report"]
    payload = {
        "status": report["status"],
        "valid": report["valid"],
        "project_id": report["project_id"],
        "implementation_id": report["implementation_id"],
        "selected_segments": report["summary"]["selected_segments"],
        "candidate_value": report["summary"]["candidate_value"],
        "candidate_threshold": report["summary"]["candidate_threshold"],
        "candidate_pass": report["summary"]["candidate_pass"],
        "selected_method": report["summary"]["selected_method"],
        "warnings": report["summary"]["warnings"],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
