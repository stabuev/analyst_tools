from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "decision_memo_builder.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("decision_memo_builder", ARTIFACT)
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
        result = builder.build_decision_memo(
            spec_path=paths["spec_path"],
            evidence_path=paths["evidence_path"],
            quality_gates_path=paths["quality_gates_path"],
            output_dir=root / "memo-package",
        )
        summary = {
            "valid": result.audit["valid"],
            "readiness_status": result.audit["readiness_status"],
            "recommended_decision": result.audit["recommended_decision"],
            "claims": result.audit["summary"]["claim_count"],
            "matrix_rows": result.audit["summary"]["matrix_row_count"],
            "warnings": result.audit["summary"]["warnings"],
            "files": [
                result.memo_path.name,
                result.matrix_path.name,
                result.audit_path.name,
                result.manifest_path.name,
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
