from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
OBSERVATIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "metric_observations.csv"
EFFECTS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "effect_results.csv"
ASSUMPTIONS = PHASE_ROOT / "05-means-and-proportions" / "outputs" / "assumption_checks.json"
ARTIFACT = ROOT / "outputs" / "experiment_bootstrap_analyzer.py"
BOOTSTRAP_SPEC = ROOT / "outputs" / "bootstrap_spec.json"


def load_analyzer():
    spec = importlib.util.spec_from_file_location("experiment_bootstrap_analyzer", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    analyzer = load_analyzer()
    report, distribution, manifest = analyzer.run(PROTOCOL, BOOTSTRAP_SPEC, OBSERVATIONS, EFFECTS, ASSUMPTIONS)
    primary = next(row for row in report["intervals"] if row["metric_id"] == "activation_rate_7d")
    refund = next(row for row in report["intervals"] if row["metric_id"] == "refund_rate_7d")
    revenue = next(row for row in report["intervals"] if row["metric_id"] == "realized_revenue_per_user_7d")
    payload = {
        "valid": report["valid"],
        "metrics_analyzed": report["summary"]["metrics_analyzed"],
        "distribution_rows": len(distribution),
        "primary_ci": [primary["ci_low"], primary["ci_high"]],
        "refund_paired_denominator": refund["paired_denominator"],
        "refund_invalid_resamples": refund["invalid_resamples"],
        "revenue_interval_contains_zero": revenue["interval_contains_zero"],
        "manifest_metrics": manifest["metrics"]
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
