from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
RELEASE_CALENDAR = ROOT.parent / "data" / "tiny" / "release_calendar.csv"
SEGMENTS = ROOT.parent / "08-segmentation" / "outputs" / "segments.csv"
GUARDRAILS = ROOT.parent / "09-guardrails" / "outputs" / "guardrails.csv"
SPEC = ROOT / "outputs" / "anomaly_spec.json"
ARTIFACT = ROOT / "outputs" / "anomaly_detector.py"


def load_detector():
    spec = importlib.util.spec_from_file_location("anomaly_detector", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    detector = load_detector()
    users, user_columns = detector.read_csv(USERS)
    events, event_columns = detector.read_csv(EVENTS)
    releases, release_columns = detector.read_csv(RELEASE_CALENDAR)
    segments, segment_columns = detector.read_csv(SEGMENTS)
    guardrails, guardrail_columns = detector.read_csv(GUARDRAILS)
    result = detector.detect_anomalies(
        users,
        user_columns,
        events,
        event_columns,
        detector.read_json(TRACKING_PLAN),
        releases,
        release_columns,
        segments,
        segment_columns,
        guardrails,
        guardrail_columns,
        detector.read_json(SPEC),
    )
    candidates = result.anomalies["candidates"]
    summary = {
        "valid": result.report["valid"],
        "quality_gates_passed": result.report["quality_gates_passed"],
        "by_classification": result.anomalies["summary"]["by_classification"],
        "product_signal_ids": [
            candidate["candidate_id"]
            for candidate in candidates
            if candidate["classification"] == "product_signal"
        ],
        "context_ids": [
            candidate["candidate_id"]
            for candidate in candidates
            if candidate["classification"] in {"composition", "calendar_effect"}
        ],
        "recommended_action": result.anomalies["summary"]["recommended_action"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
