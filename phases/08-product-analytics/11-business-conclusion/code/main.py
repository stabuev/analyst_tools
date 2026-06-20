from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "product_problem_builder.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("product_problem_builder", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_builder()
    with TemporaryDirectory() as directory:
        package = Path(directory) / "product-problem-investigation"
        result = builder.build_package(PHASE_ROOT, package)
        recommendation = builder.read_json(package / "recommendation.json")
        summary = {
            "valid": result.report["valid"],
            "decision": recommendation["decision"],
            "claims": [claim["claim_id"] for claim in recommendation["claims"]],
            "next_steps": [step["step_id"] for step in recommendation["next_steps"]],
            "manifest_files": result.report["files"],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
