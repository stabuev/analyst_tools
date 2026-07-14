from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_data_contract_auditor.py"


def load_auditor():
    spec = importlib.util.spec_from_file_location("capstone_data_contract_auditor", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    auditor = load_auditor()
    with TemporaryDirectory() as directory:
        inputs = auditor.write_sample_inputs(Path(directory) / "input")
        result = auditor.build_data_contract_package(
            upstream_brief_package=inputs["upstream_brief_package"],
            data_contract_path=inputs["data_contract_path"],
            dataset_manifest_path=inputs["dataset_manifest_path"],
            source_root=inputs["source_root"],
            output_dir=LESSON_ROOT / "outputs",
        )
    report = result["report"]
    payload = {
        "status": report["status"],
        "valid": report["valid"],
        "project_id": report["project_id"],
        "contract_id": report["contract_id"],
        "source_count": report["summary"]["source_count"],
        "relationship_count": report["summary"]["relationship_count"],
        "public_sample_rows": report["summary"]["public_sample_rows"],
        "warnings": report["summary"]["warnings"],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
