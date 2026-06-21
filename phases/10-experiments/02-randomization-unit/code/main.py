from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
DATA = PHASE_ROOT / "data" / "tiny"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
SPEC = ROOT / "outputs" / "randomization_spec.json"
ENGINE_PATH = ROOT / "outputs" / "assignment_engine.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("assignment_engine", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ENGINE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    engine = load_engine()
    users = engine.read_csv(DATA / "users.csv")
    events = engine.read_csv(DATA / "events.csv")
    protocol = engine.read_json(PROTOCOL)
    spec = engine.read_json(SPEC)
    assignments = engine.build_assignments(users, protocol, spec)
    exposures = engine.build_exposures(assignments, events, protocol)
    report = engine.audit_assignment(assignments, exposures, users, protocol, spec)
    preview = [
        {
            "user_id": row["user_id"],
            "bucket": row["bucket"],
            "variant_id": row["variant_id"],
        }
        for row in assignments[:3]
    ]
    payload = {
        "assignment_unit": spec["assignment_unit"],
        "analysis_unit": spec["analysis_unit"],
        "assigned_units": report["summary"]["assigned_units"],
        "variant_counts": report["summary"]["variant_counts"],
        "assignment_preview": preview,
        "audit_valid": report["valid"],
        "failed_checks": [check["id"] for check in report["checks"] if not check["valid"]],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
