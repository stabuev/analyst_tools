from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE = ROOT.parent
ARTIFACT = ROOT / "outputs" / "regression_diagnostics_checker.py"
SPEC = ROOT / "outputs" / "diagnostic_spec.json"
MODEL_REPORT = PHASE / "08-linear-regression" / "outputs" / "model_report.json"


def load_checker():
    module_spec = importlib.util.spec_from_file_location("regression_diagnostics_checker", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    checker = load_checker()
    report = checker.run(MODEL_REPORT, SPEC)
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "warning_flags": report["summary"]["warning_flags"],
                "condition_number": report["diagnostics"]["condition_number"],
                "leverage_threshold": report["diagnostics"]["leverage"]["threshold"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
