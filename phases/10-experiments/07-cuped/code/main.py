from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
OBSERVATIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "metric_observations.csv"
PRE_EXPERIMENT = PHASE_ROOT / "data" / "tiny" / "pre_experiment_metrics.csv"
EFFECTS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "effect_results.csv"
ASSUMPTIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "assumption_checks.json"
ARTIFACT = ROOT / "outputs" / "experiment_cuped_adjuster.py"
CUPED_SPEC = ROOT / "outputs" / "cuped_spec.json"


def load_adjuster():
    spec = importlib.util.spec_from_file_location("experiment_cuped_adjuster", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    adjuster = load_adjuster()
    report, effects, adjusted_rows, manifest = adjuster.run(
        PROTOCOL,
        CUPED_SPEC,
        OBSERVATIONS,
        PRE_EXPERIMENT,
        EFFECTS,
        ASSUMPTIONS,
    )
    primary = next(row for row in effects if row["metric_id"] == "activation_rate_7d")
    trial = next(row for row in effects if row["metric_id"] == "paywall_to_trial_conversion_7d")
    payload = {
        "valid": report["valid"],
        "ready_for_decision": report["ready_for_decision"],
        "metrics_analyzed": report["summary"]["metrics_analyzed"],
        "adjusted_observation_rows": len(adjusted_rows),
        "primary_raw_lift": primary["raw_absolute_lift"],
        "primary_adjusted_lift": primary["adjusted_absolute_lift"],
        "primary_variance_reduction": primary["variance_reduction"],
        "trial_variance_reduction": trial["variance_reduction"],
        "skipped_metrics": report["summary"]["skipped_metrics"],
        "manifest_metrics": manifest["metrics"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
