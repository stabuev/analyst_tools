from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "layer_contract_auditor.py"
CONTRACT = ROOT / "outputs" / "layer_contract.json"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
BRIEF = ROOT / "outputs" / "mart_design_brief.md"


def load_auditor():
    spec = importlib.util.spec_from_file_location("layer_contract_auditor", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    auditor = load_auditor()
    report = auditor.validate_contract(
        auditor.read_json(CONTRACT),
        auditor.read_json(DATA_CONTRACT),
        brief_text=BRIEF.read_text(encoding="utf-8"),
    )
    summary = {
        "valid": report["valid"],
        "project_id": report["summary"]["project_id"],
        "layers": report["summary"]["layers"],
        "mart_models": report["summary"]["mart_models"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
