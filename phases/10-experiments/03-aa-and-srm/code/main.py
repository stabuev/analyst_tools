from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
DATA = PHASE_ROOT / "data" / "tiny"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
ARTIFACT = ROOT / "outputs" / "randomization_health.py"
HEALTH_SPEC = ROOT / "outputs" / "randomization_health_spec.json"


def load_diagnostic():
    spec = importlib.util.spec_from_file_location("randomization_health", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    diagnostic = load_diagnostic()
    report = diagnostic.run(
        DATA / "assignments.csv",
        DATA / "exposures.csv",
        DATA / "pre_experiment_metrics.csv",
        PROTOCOL,
        HEALTH_SPEC,
    )
    checks = {check["id"]: check for check in report["checks"]}
    payload = {
        "ready_for_ab_analysis": report["ready_for_ab_analysis"],
        "assignment_srm_p_value": checks["assignment_srm_chi_square"]["observed"]["p_value"],
        "exposure_srm_p_value": checks["exposure_srm_chi_square"]["observed"]["p_value"],
        "telemetry_missing_units": checks["telemetry_loss_by_variant"]["observed"]["missing_units"],
        "warning_checks": report["summary"]["warning_checks"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
