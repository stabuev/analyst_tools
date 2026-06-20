from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
TRACKING_PLAN = ROOT / "outputs" / "tracking_plan.json"
METRIC_SPECS = ROOT.parent / "01-metric-tree" / "outputs" / "metric_specs.json"
ARTIFACT = ROOT / "outputs" / "event_model_validator.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("event_model_validator", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manual_event_name_counts(events_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with events_path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            name = row["event_name"]
            counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def main() -> None:
    validator = load_validator()
    report = validator.run(EVENTS, TRACKING_PLAN, METRIC_SPECS)
    result = {
        "manual_event_name_counts": manual_event_name_counts(EVENTS),
        "validator_summary": report["summary"],
        "valid": report["valid"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
