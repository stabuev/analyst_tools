from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_independent_verifier.py"


def load_verifier():
    spec = importlib.util.spec_from_file_location("capstone_independent_verifier", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    verifier = load_verifier()
    with TemporaryDirectory() as directory:
        inputs = verifier.write_sample_inputs(Path(directory) / "input")
        result = verifier.build_verification_package(
            upstream_implementation_package=inputs["upstream_implementation_package"],
            implementation_runner=inputs["implementation_runner"],
            upstream_baseline_package=inputs["upstream_baseline_package"],
            verification_spec_path=inputs["verification_spec_path"],
            output_dir=LESSON_ROOT / "outputs",
        )
    report = result["report"]
    payload = {
        "status": report["status"],
        "valid": report["valid"],
        "project_id": report["project_id"],
        "verification_id": report["verification_id"],
        "clean_room_match": report["summary"]["clean_room_match"],
        "shadow_pass": report["summary"]["shadow_pass"],
        "negative_fixtures": report["summary"]["negative_fixtures"],
        "negative_fixtures_pass": report["summary"]["negative_fixtures_pass"],
        "sensitivity_decision_flips": report["summary"]["sensitivity_decision_flips"],
        "verified_claims": report["summary"]["verified_claims"],
        "selected_method": report["summary"]["selected_method"],
        "warnings": report["summary"]["warnings"],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
