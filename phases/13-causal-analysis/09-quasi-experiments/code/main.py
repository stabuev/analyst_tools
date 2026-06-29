from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "quasi_experiment_design_auditor.py"
SPEC = ROOT / "outputs" / "quasi_experiment_spec.json"
DATA_DIR = PHASE_ROOT / "data" / "tiny"


def load_auditor():
    module_spec = importlib.util.spec_from_file_location(
        "quasi_experiment_design_auditor",
        ARTIFACT,
    )
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    auditor = load_auditor()
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    report = auditor.audit_quasi_experiments(DATA_DIR, spec)
    summary = report["summary"]
    print(
        json.dumps(
            {
                "quasi_design_valid": report["valid"],
                "rdd_design_type": report["rdd_design_audit"]["calculated_design_type"],
                "rdd_local_rows_n": summary["rdd_local_rows_n"],
                "rdd_first_stage": round(summary["rdd_first_stage"], 6),
                "rdd_wald_local_effect_diagnostic": round(
                    summary["rdd_wald_local_effect_diagnostic"], 6
                ),
                "iv_first_stage": round(summary["iv_first_stage"], 6),
                "iv_wald_late": round(summary["iv_wald_late"], 6),
                "allowed_local_claim": summary["allowed_local_claim"],
                "warning_checks": summary["warning_checks"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
