from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "docker_packaging_audit.py"


def load_docker_builder():
    spec = importlib.util.spec_from_file_location("docker_packaging_audit", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_docker_builder()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        sample = builder.write_sample_docker_inputs(root / "sample")
        result = builder.build_docker_packaging_audit(
            api_package_dir=sample["api_package_dir"],
            container_contract_path=sample["container_contract_path"],
            output_dir=root / "docker-package",
        )
        audit = builder.read_json(result.audit_path)
        context_report = builder.read_json(result.context_report_path)
        run_manifest = builder.read_json(result.run_manifest_path)
        payload = {
            "status": result.status,
            "valid": result.valid,
            "context_included_count": context_report["included_count"],
            "context_included_total_bytes": context_report["included_total_bytes"],
            "context_top_level": context_report["included_top_level"],
            "manifest_hashes_match": run_manifest["equivalence"]["hashes_match"],
            "image_tag": run_manifest["image_tag"],
            "build_command": " ".join(run_manifest["build_command"]),
            "run_command": " ".join(run_manifest["run_command"]),
            "audit_blocking_errors": audit["summary"]["blocking_errors"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
