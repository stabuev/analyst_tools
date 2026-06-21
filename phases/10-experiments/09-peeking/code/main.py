from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
POWER_PLAN = PHASE_ROOT / "04-mde-and-power" / "outputs" / "power_plan.json"
MULTIPLE_TESTING_REPORT = PHASE_ROOT / "08-multiple-testing" / "outputs" / "multiple_testing_report.json"
ARTIFACT = ROOT / "outputs" / "peeking_audit.py"
PEEKING_POLICY = ROOT / "outputs" / "peeking_policy.json"


def load_auditor():
    spec = importlib.util.spec_from_file_location("peeking_audit", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    auditor = load_auditor()
    report, schedule_rows, simulation_rows, manifest = auditor.run(
        PROTOCOL,
        PEEKING_POLICY,
        POWER_PLAN,
        MULTIPLE_TESTING_REPORT,
    )
    observed_rows = [row for row in schedule_rows if row["status"] != "planned_boundary"]
    interim = next(row for row in observed_rows if row["look_id"] == "interim_50")
    five_looks = next(row for row in simulation_rows if row["look_count"] == 5)
    payload = {
        "valid": report["valid"],
        "ready_for_decision": report["ready_for_decision"],
        "planned_decision_looks": report["summary"]["planned_decision_looks"],
        "unplanned_decision_looks": report["summary"]["unplanned_decision_looks"],
        "decision_blockers": report["summary"]["decision_blockers"],
        "interim_50_nominal_p_boundary": round(interim["nominal_p_boundary"], 6),
        "interim_50_observed_p_value": interim["observed_p_value"],
        "interim_50_crosses_spending_boundary": interim["crosses_spending_boundary"],
        "naive_fpr_at_five_looks": five_looks["naive_false_positive_rate"],
        "obrien_fleming_fpr_at_five_looks": five_looks["obrien_fleming_false_positive_rate"],
        "manifest_alpha_spending": manifest["alpha_spending"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
