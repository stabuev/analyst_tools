from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "stakeholder_delivery_package.py"


def load_handoff_builder():
    spec = importlib.util.spec_from_file_location("stakeholder_delivery_package", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_handoff_builder()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        sample = builder.write_sample_handoff_inputs(root / "sample")
        result = builder.build_stakeholder_delivery_package(
            source_root=sample["source_root"],
            docker_package_dir=sample["docker_package_dir"],
            workbook_package_dir=sample["workbook_package_dir"],
            handoff_contract_path=sample["handoff_contract_path"],
            output_dir=root / "handoff-package",
        )
        quality = builder.read_json(result.quality_summary_path)
        manifest = builder.read_json(result.manifest_path)
        audit = builder.read_json(result.audit_path)
        payload = {
            "status": result.status,
            "valid": result.valid,
            "decision_status": result.decision_status,
            "quality_gate_count": len(quality["gates"]),
            "blocking_layers": quality["blocking_layers"],
            "manifest_output_count": len(manifest["outputs"]),
            "runbook_exists": (result.package_dir / "handoff" / "runbook.md").is_file(),
            "support_policy_exists": (result.package_dir / "handoff" / "support-policy.md").is_file(),
            "audit_blocking_errors": audit["summary"]["blocking_errors"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
