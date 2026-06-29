from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "ipw_aipw_estimator.py"


def load_estimator():
    module_spec = importlib.util.spec_from_file_location("ipw_aipw_estimator", ARTIFACT)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def main() -> None:
    estimator = load_estimator()
    paths = estimator.default_paths()
    report = estimator.estimate_ipw_aipw(
        paths["data_dir"],
        estimator.read_json(paths["target_trial"]),
        estimator.read_json(paths["estimand"]),
        estimator.read_json(paths["adjustment_gate"]),
        estimator.read_json(paths["spec"]),
    )

    stress = {
        item["stress_test_id"]: {
            "ipw_hajek_ate": round(item["estimates"]["ipw_hajek_ate"], 6),
            "aipw_ate": round(item["estimates"]["aipw_ate"], 6),
            "max_stabilized_weight": round(item["weights"]["max_stabilized_weight"], 6),
        }
        for item in report["stress_tests"]
    }
    summary = {
        "estimator_valid": report["valid"],
        "cohort_n": report["summary"]["cohort_n"],
        "treated_n": report["summary"]["treated_n"],
        "comparator_n": report["summary"]["comparator_n"],
        "naive_risk_difference": round(report["summary"]["naive_risk_difference"], 6),
        "ipw_hajek_ate": round(report["summary"]["ipw_hajek_ate"], 6),
        "aipw_ate": round(report["summary"]["aipw_ate"], 6),
        "outcome_regression_ate": round(report["summary"]["outcome_regression_ate"], 6),
        "min_propensity": round(report["summary"]["min_propensity"], 6),
        "max_propensity": round(report["summary"]["max_propensity"], 6),
        "stabilized_effective_sample_size": round(
            report["summary"]["stabilized_effective_sample_size"],
            6,
        ),
        "effect_claim_allowed": report["summary"]["allowed_effect_claim"],
        "warning_checks": report["summary"]["warning_checks"],
        "stress_tests": stress,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
