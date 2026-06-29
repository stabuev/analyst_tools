from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "g_computation_estimator.py"


def load_estimator():
    spec = importlib.util.spec_from_file_location("g_computation_estimator", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    estimator = load_estimator()
    report = estimator.estimate_g_formula(
        PHASE_ROOT / "data" / "tiny",
        estimator.read_json(
            PHASE_ROOT / "01-causal-question-and-estimand" / "outputs" / "target_trial_spec.json"
        ),
        estimator.read_json(
            PHASE_ROOT / "01-causal-question-and-estimand" / "outputs" / "estimand.json"
        ),
        estimator.read_json(
            PHASE_ROOT / "04-colliders" / "outputs" / "bad_control_selection_audit.json"
        ),
        estimator.read_json(ROOT / "outputs" / "g_formula_spec.json"),
    )
    payload = {
        "estimate_valid": report["valid"],
        "blocking_checks": report["summary"]["blocking_checks"],
        "warning_checks": report["summary"]["warning_checks"],
        "cohort_n": report["summary"]["cohort_n"],
        "treated_n": report["summary"]["treated_n"],
        "comparator_n": report["summary"]["comparator_n"],
        "naive_risk_difference": round(report["summary"]["naive_risk_difference"], 6),
        "standardized_ate": round(report["summary"]["manual_ate"], 6),
        "standardized_att": round(report["summary"]["manual_att"], 6),
        "manual_statsmodels_max_effect_diff": report["summary"][
            "manual_statsmodels_max_effect_diff"
        ],
        "effect_claim_allowed": report["summary"]["effect_claim_allowed"],
        "identification_status": report["summary"]["identification_status"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
