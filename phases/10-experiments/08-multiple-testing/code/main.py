from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
EFFECTS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "effect_results.csv"
ASSUMPTIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "assumption_checks.json"
BOOTSTRAP = PHASE_ROOT / "06-bootstrap" / "outputs" / "bootstrap_intervals.json"
CUPED_REPORT = PHASE_ROOT / "07-cuped" / "outputs" / "variance_reduction_report.json"
CUPED_EFFECTS = PHASE_ROOT / "07-cuped" / "outputs" / "cuped_effects.csv"
ARTIFACT = ROOT / "outputs" / "multiple_testing_policy_checker.py"
POLICY_SPEC = ROOT / "outputs" / "multiple_testing_policy.json"


def load_checker():
    spec = importlib.util.spec_from_file_location("multiple_testing_policy_checker", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    checker = load_checker()
    report, adjusted_rows, manifest = checker.run(
        PROTOCOL,
        POLICY_SPEC,
        EFFECTS,
        BOOTSTRAP,
        CUPED_REPORT,
        CUPED_EFFECTS,
        ASSUMPTIONS,
    )
    secondary = [row for row in adjusted_rows if row["family"] == "secondary"]
    exploratory = [row for row in adjusted_rows if row["family"] == "exploratory"]
    payload = {
        "valid": report["valid"],
        "ready_for_decision": report["ready_for_decision"],
        "hypotheses_evaluated": report["summary"]["hypotheses_evaluated"],
        "primary_gate_passed": report["summary"]["primary_gate_passed"],
        "secondary_adjusted_signals": report["summary"]["secondary_adjusted_signals"],
        "secondary_adjusted_p_values": {
            row["metric_id"]: row["adjusted_p_value"] for row in secondary
        },
        "exploratory_adjusted_signals": report["summary"]["exploratory_adjusted_signals"],
        "launch_allowed_by_multiple_testing": report["summary"]["launch_allowed_by_multiple_testing"],
        "manifest_families": manifest["families"],
        "exploratory_rows": len(exploratory),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
