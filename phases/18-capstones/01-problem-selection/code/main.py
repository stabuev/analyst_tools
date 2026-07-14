from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_brief_validator.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("capstone_brief_validator", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    validator = load_validator()
    with TemporaryDirectory() as directory:
        brief_path = validator.write_example(Path(directory) / "input")
        result = validator.build_capstone_brief_package(
            brief_path=brief_path,
            output_dir=LESSON_ROOT / "outputs",
        )
    report = result["report"]
    payload = {
        "status": report["status"],
        "valid": report["valid"],
        "project_id": report["project_id"],
        "route": report["summary"]["route"],
        "required_prerequisites": report["summary"]["required_prerequisites"],
        "estimated_hours": report["summary"]["estimated_hours"],
        "risk_count": report["summary"]["risk_count"],
        "milestone_count": report["summary"]["milestone_count"],
        "warnings": report["summary"]["warnings"],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
