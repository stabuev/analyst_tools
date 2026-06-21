from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
DATA = PHASE_ROOT / "data" / "tiny"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
METRIC_SPECS = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "metric_specs.json"
HEALTH = PHASE_ROOT / "03-aa-and-srm" / "outputs" / "randomization_health_report.json"
POWER_PLAN = PHASE_ROOT / "04-mde-and-power" / "outputs" / "power_plan.json"
ARTIFACT = ROOT / "outputs" / "experiment_effect_calculator.py"
EFFECT_SPEC = ROOT / "outputs" / "effect_spec.json"


def load_calculator():
    spec = importlib.util.spec_from_file_location("experiment_effect_calculator", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    calculator = load_calculator()
    observations, effects, assumptions = calculator.run(
        PROTOCOL,
        METRIC_SPECS,
        EFFECT_SPEC,
        HEALTH,
        POWER_PLAN,
        DATA / "users.csv",
        DATA / "assignments.csv",
        DATA / "exposures.csv",
        DATA / "events.csv",
        DATA / "orders.csv",
        DATA / "subscriptions.csv",
        DATA / "support_tickets.csv",
    )
    primary = next(row for row in effects if row["metric_id"] == "activation_rate_7d")
    trial = next(row for row in effects if row["metric_id"] == "paywall_to_trial_conversion_7d")
    payload = {
        "valid": assumptions["valid"],
        "ready_for_decision": assumptions["ready_for_decision"],
        "observation_rows": len(observations),
        "primary_absolute_lift": primary["absolute_lift"],
        "primary_p_value": primary["p_value"],
        "primary_status": primary["practical_status"],
        "trial_absolute_lift": trial["absolute_lift"],
        "trial_decision_status": trial["decision_status"],
        "decision_blockers": assumptions["summary"]["decision_blockers"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
