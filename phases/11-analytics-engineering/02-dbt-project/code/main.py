from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dbt_project_auditor.py"
SKELETON = ROOT / "outputs" / "dbt_project_skeleton"


def load_auditor():
    spec = importlib.util.spec_from_file_location("dbt_project_auditor", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    auditor = load_auditor()
    report = auditor.validate_project(SKELETON, run_dbt=False)
    summary = {
        "valid": report["valid"],
        "project_name": report["summary"].get("project_name"),
        "profile_name": report["summary"].get("profile_name"),
        "checks_passed": sum(1 for check in report["checks"] if check["valid"]),
        "checks_total": len(report["checks"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
