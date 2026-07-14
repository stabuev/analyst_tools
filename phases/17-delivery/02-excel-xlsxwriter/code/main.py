from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "stakeholder_workbook_builder.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("stakeholder_workbook_builder", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_builder()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        paths = builder.write_sample_inputs(root / "inputs")
        result = builder.build_stakeholder_workbook(
            spec_path=paths["spec_path"],
            metrics_path=paths["metrics_path"],
            evidence_path=paths["evidence_path"],
            memo_audit_path=paths["memo_audit_path"],
            output_dir=root / "workbook-package",
        )
        summary = {
            "valid": result.audit["valid"],
            "readiness_status": result.audit["readiness_status"],
            "blocking_errors": result.audit["summary"]["blocking_errors"],
            "files": [
                result.workbook_path.name,
                result.audit_path.name,
                result.dictionary_path.name,
                result.manifest_path.name,
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
