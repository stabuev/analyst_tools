from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
DATA = PHASE / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "correlation_auditor.py"
SPEC = ROOT / "outputs" / "correlation_spec.json"


def load_auditor():
    module_spec = importlib.util.spec_from_file_location("correlation_auditor", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    auditor = load_auditor()
    report = auditor.run(DATA / "sample_observations.csv", SPEC)
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "summary": report["summary"],
                "associations": {
                    item["association_id"]: {
                        "status": item["status"],
                        "pearson": item["aggregate"].get("pearson", {}).get("statistic"),
                        "spearman": item["aggregate"].get("spearman", {}).get("statistic"),
                        "warnings": item["diagnostic_warning_ids"],
                    }
                    for item in report["associations"]
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
