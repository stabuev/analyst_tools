from __future__ import annotations

import importlib.util
import json
from pathlib import Path


LESSON_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = LESSON_ROOT / "outputs"
PACKAGER_PATH = OUTPUTS / "analytics_mart_packager.py"
PROJECT = OUTPUTS / "analytics-mart-dbt"
DATA_CONTRACT = LESSON_ROOT.parent / "data" / "contract.json"


def load_packager():
    spec = importlib.util.spec_from_file_location("analytics_mart_packager", PACKAGER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {PACKAGER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    packager = load_packager()
    report = packager.validate_project(PROJECT, DATA_CONTRACT, build_package=False)
    test_report = json.loads((PROJECT / "quality" / "dbt-test-report.json").read_text(encoding="utf-8"))
    sqlfluff_report = json.loads((PROJECT / "quality" / "sqlfluff-report.json").read_text(encoding="utf-8"))
    checksum_manifest = json.loads((PROJECT / "manifest.json").read_text(encoding="utf-8"))
    summary = {
        "package": PROJECT.name,
        "valid": report["valid"],
        "checks": len(report["checks"]),
        "release_files": len(packager.RELEASE_FILES),
        "checksum_files": len(checksum_manifest["files"]),
        "dbt_tests": {
            "status": test_report["status"],
            "count": test_report["test_count"],
            "warnings": test_report["warning_test_count"],
        },
        "sqlfluff": {
            "status": sqlfluff_report["status"],
            "files": sqlfluff_report["files_linted"],
            "violations": sqlfluff_report["violation_count"],
        },
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
