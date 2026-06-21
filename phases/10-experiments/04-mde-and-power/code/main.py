from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
DATA = PHASE_ROOT / "data" / "tiny"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
HEALTH = PHASE_ROOT / "03-aa-and-srm" / "outputs" / "randomization_health_report.json"
ARTIFACT = ROOT / "outputs" / "power_planner.py"
POWER_SPEC = ROOT / "outputs" / "power_spec.json"


def load_planner():
    spec = importlib.util.spec_from_file_location("power_planner", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    planner = load_planner()
    plan, grid = planner.run(PROTOCOL, DATA / "metric_baselines.csv", HEALTH, POWER_SPEC)
    primary = next(row for row in plan["metric_plans"] if row["metric_id"] == "activation_rate_7d")
    revenue = next(row for row in plan["metric_plans"] if row["metric_id"] == "realized_revenue_per_user_7d")
    payload = {
        "valid": plan["valid"],
        "primary_required_n_per_variant": primary["required_n_control"],
        "primary_planned_power": primary["planned_power"],
        "revenue_required_n_per_variant": revenue["required_n_control"],
        "recommended_runtime_days": primary["recommended_runtime_days"],
        "grid_rows": len(grid),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
