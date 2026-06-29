from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "matching_pipeline.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("matching_pipeline", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    matching = load_artifact()
    report = matching.estimate_matching(
        PHASE_ROOT / "data" / "tiny",
        matching.read_json(
            PHASE_ROOT / "01-causal-question-and-estimand" / "outputs" / "target_trial_spec.json"
        ),
        matching.read_json(
            PHASE_ROOT / "01-causal-question-and-estimand" / "outputs" / "estimand.json"
        ),
        matching.read_json(
            PHASE_ROOT / "04-colliders" / "outputs" / "bad_control_selection_audit.json"
        ),
        matching.read_json(ROOT / "outputs" / "matching_spec.json"),
    )
    summary = report["summary"]
    payload = {
        "matching_valid": report["valid"],
        "cohort_n": summary["cohort_n"],
        "treated_n": summary["treated_n"],
        "comparator_n": summary["comparator_n"],
        "matched_treated_n": summary["matched_treated_n"],
        "unmatched_treated_n": summary["unmatched_treated_n"],
        "matched_att": round(summary["matched_att"], 6),
        "naive_risk_difference": round(summary["naive_risk_difference"], 6),
        "max_abs_smd_after": round(summary["max_abs_smd_after"], 6),
        "warning_checks": summary["warning_checks"],
        "effect_claim_allowed": report["claim_policy"]["allowed_effect_claim"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
