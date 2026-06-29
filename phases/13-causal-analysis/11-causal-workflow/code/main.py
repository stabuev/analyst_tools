from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "causal_study_package_builder.py"
SPEC = ROOT / "outputs" / "causal_workflow_spec.json"


def load_builder():
    module_spec = importlib.util.spec_from_file_location("causal_study_package_builder", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_builder()
    package, _manifest = builder.build_package(json.loads(SPEC.read_text(encoding="utf-8")))
    summary = package["summary"]
    print(
        json.dumps(
            {
                "package_valid": package["valid"],
                "source_files_n": summary["source_files_n"],
                "workflow_steps": summary["workflow_steps"],
                "estimate_rows_n": summary["estimate_rows_n"],
                "final_claim_status": summary["final_claim_status"],
                "allowed_effect_claim": summary["allowed_effect_claim"],
                "dowhy_runtime_status": summary["dowhy_runtime_status"],
                "econml_used": summary["econml_used"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
