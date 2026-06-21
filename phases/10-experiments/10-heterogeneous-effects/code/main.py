from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
ARTIFACT = ROOT / "outputs" / "segment_effect_auditor.py"

MODULE_SPEC = importlib.util.spec_from_file_location("segment_effect_auditor", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(AUDITOR)


def main() -> None:
    report, segment_rows, interaction_rows, manifest = AUDITOR.run(
        PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json",
        ROOT / "outputs" / "segment_policy.json",
        PHASE_ROOT / "05-means-and-proportions" / "outputs" / "metric_observations.csv",
        PHASE_ROOT / "data" / "tiny" / "users.csv",
        PHASE_ROOT / "08-multiple-testing" / "outputs" / "multiple_testing_report.json",
        PHASE_ROOT / "09-peeking" / "outputs" / "sequential_monitoring_report.json",
    )
    platform_primary = next(
        row
        for row in segment_rows
        if row["dimension"] == "platform"
        and row["segment_value"] == "android"
        and row["metric_id"] == "activation_rate_7d"
    )
    payload = {
        "valid": report["valid"],
        "ready_for_decision": report["ready_for_decision"],
        "minimum_cell_size": report["summary"]["minimum_cell_size"],
        "predeclared_dimensions": report["summary"]["predeclared_dimensions"],
        "post_hoc_dimensions": report["summary"]["post_hoc_dimensions"],
        "platform_android_primary_lift": platform_primary["absolute_lift"],
        "platform_android_status": platform_primary["status"],
        "missing_variant_rows": report["summary"]["missing_variant_rows"],
        "below_minimum_cell_rows": report["summary"]["below_minimum_cell_rows"],
        "insufficient_interaction_checks": report["summary"]["insufficient_interaction_checks"],
        "manifest_artifact": manifest["artifact"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
