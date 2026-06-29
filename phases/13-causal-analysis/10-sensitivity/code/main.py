from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "sensitivity_refutation_suite.py"
SPEC = ROOT / "outputs" / "sensitivity_spec.json"
DATA_DIR = PHASE_ROOT / "data" / "tiny"


def load_suite():
    module_spec = importlib.util.spec_from_file_location("sensitivity_refutation_suite", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    suite = load_suite()
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    report = suite.audit_sensitivity(DATA_DIR, spec)
    summary = report["summary"]
    print(
        json.dumps(
            {
                "sensitivity_valid": report["valid"],
                "cohort_n": summary["cohort_n"],
                "primary_effect": round(summary["primary_effect"], 6),
                "falsification_failures": summary["falsification_failures"],
                "required_bias_to_reach_null": round(
                    summary["required_bias_to_reach_null"],
                    6,
                ),
                "first_nulling_bias": round(summary["first_nulling_bias"], 6),
                "design_estimate_range": round(summary["design_estimate_range"], 6),
                "allowed_effect_claim": summary["allowed_effect_claim"],
                "claim_blocking_reasons": summary["claim_blocking_reasons"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
