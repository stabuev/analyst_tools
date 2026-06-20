from __future__ import annotations

import copy
import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "anomaly_detector.py"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
RELEASE_CALENDAR = ROOT.parent / "data" / "tiny" / "release_calendar.csv"
SEGMENTS = ROOT.parent / "08-segmentation" / "outputs" / "segments.csv"
GUARDRAILS = ROOT.parent / "09-guardrails" / "outputs" / "guardrails.csv"
SPEC_PATH = ROOT / "outputs" / "anomaly_spec.json"
SAMPLE_ANOMALIES = ROOT / "outputs" / "anomalies.json"
MODULE_SPEC = importlib.util.spec_from_file_location("anomaly_detector", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DETECTOR = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = DETECTOR
MODULE_SPEC.loader.exec_module(DETECTOR)


def load_inputs() -> tuple[
    list[dict[str, str]],
    list[str],
    list[dict[str, str]],
    list[str],
    dict,
    list[dict[str, str]],
    list[str],
    list[dict[str, str]],
    list[str],
    list[dict[str, str]],
    list[str],
    dict,
]:
    users, user_columns = DETECTOR.read_csv(USERS)
    events, event_columns = DETECTOR.read_csv(EVENTS)
    releases, release_columns = DETECTOR.read_csv(RELEASE_CALENDAR)
    segments, segment_columns = DETECTOR.read_csv(SEGMENTS)
    guardrails, guardrail_columns = DETECTOR.read_csv(GUARDRAILS)
    return (
        users,
        user_columns,
        events,
        event_columns,
        DETECTOR.read_json(TRACKING_PLAN),
        releases,
        release_columns,
        segments,
        segment_columns,
        guardrails,
        guardrail_columns,
        DETECTOR.read_json(SPEC_PATH),
    )


def detect(
    *,
    events: list[dict[str, str]] | None = None,
    releases: list[dict[str, str]] | None = None,
    segments: list[dict[str, str]] | None = None,
    guardrails: list[dict[str, str]] | None = None,
    spec: dict | None = None,
):
    (
        users,
        user_columns,
        base_events,
        event_columns,
        tracking_plan,
        base_releases,
        release_columns,
        base_segments,
        segment_columns,
        base_guardrails,
        guardrail_columns,
        base_spec,
    ) = load_inputs()
    return DETECTOR.detect_anomalies(
        users,
        user_columns,
        base_events if events is None else events,
        event_columns,
        tracking_plan,
        base_releases if releases is None else releases,
        release_columns,
        base_segments if segments is None else segments,
        segment_columns,
        base_guardrails if guardrails is None else guardrails,
        guardrail_columns,
        base_spec if spec is None else spec,
    )


def candidate(anomalies: dict, candidate_id: str) -> dict:
    return next(item for item in anomalies["candidates"] if item["candidate_id"] == candidate_id)


def gate(report: dict, gate_id: str) -> dict:
    return next(item for item in report["quality_gates"] if item["id"] == gate_id)


def candidate_ids(anomalies: dict, classification: str) -> list[str]:
    return [
        item["candidate_id"]
        for item in anomalies["candidates"]
        if item["classification"] == classification
    ]


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


class AnomalyDetectorTest(unittest.TestCase):
    def setUp(self) -> None:
        (
            self.users,
            self.user_columns,
            self.events,
            self.event_columns,
            self.tracking_plan,
            self.releases,
            self.release_columns,
            self.segments,
            self.segment_columns,
            self.guardrails,
            self.guardrail_columns,
            self.spec,
        ) = load_inputs()

    def test_valid_tiny_anomalies_have_expected_classifications(self) -> None:
        result = detect()
        self.assertTrue(result.report["valid"])
        self.assertTrue(result.report["quality_gates_passed"])
        self.assertEqual(result.anomalies["summary"]["candidates"], 5)
        self.assertEqual(
            result.anomalies["summary"]["by_classification"],
            {
                "data_quality": 0,
                "composition": 1,
                "calendar_effect": 1,
                "product_signal": 3,
            },
        )
        self.assertEqual(
            candidate_ids(result.anomalies, "product_signal"),
            [
                "guardrail-support_ticket_rate_7d",
                "guardrail-subscription_cancel_rate_14d",
                "guardrail-refund_rate_7d",
            ],
        )
        self.assertEqual(
            candidate(result.anomalies, "composition-platform-android")["classification"],
            "composition",
        )
        self.assertEqual(
            candidate(result.anomalies, "calendar-R002-android")["classification"],
            "calendar_effect",
        )
        self.assertEqual(result.anomalies["summary"]["recommended_action"], "investigate_before_rollout")

    def test_sample_anomalies_json_matches_calculated_output(self) -> None:
        result = detect()
        self.assertEqual(result.anomalies, DETECTOR.read_json(SAMPLE_ANOMALIES))

    def test_duplicate_event_id_blocks_product_signal_and_marks_data_quality(self) -> None:
        events = copy.deepcopy(self.events)
        events.append(copy.deepcopy(next(row for row in events if row["event_id"] == "E031")))
        result = detect(events=events)
        self.assertFalse(result.report["valid"])
        self.assertFalse(result.report["quality_gates_passed"])
        self.assertEqual(gate(result.report, "event_ids_unique")["sample"], ["E031"])
        self.assertEqual(candidate_ids(result.anomalies, "product_signal"), [])
        self.assertIn("data-quality-event_ids_unique", candidate_ids(result.anomalies, "data_quality"))

    def test_unknown_event_name_blocks_product_signal(self) -> None:
        events = copy.deepcopy(self.events)
        events[0]["event_name"] = "signup_started_v2"
        result = detect(events=events)
        self.assertFalse(gate(result.report, "known_event_names")["valid"])
        self.assertEqual(candidate_ids(result.anomalies, "product_signal"), [])
        self.assertIn("data-quality-known_event_names", candidate_ids(result.anomalies, "data_quality"))

    def test_missing_required_event_blocks_tracking_completeness(self) -> None:
        events = [row for row in self.events if row["event_name"] != "support_ticket_created"]
        result = detect(events=events)
        self.assertFalse(gate(result.report, "required_events_present")["valid"])
        self.assertEqual(gate(result.report, "required_events_present")["sample"], ["support_ticket_created"])
        self.assertEqual(candidate_ids(result.anomalies, "product_signal"), [])

    def test_late_event_blocks_product_signal(self) -> None:
        events = copy.deepcopy(self.events)
        late_event = next(row for row in events if row["event_id"] == "E031")
        late_event["received_at"] = "2026-06-07T14:56:07+03:00"
        result = detect(events=events)
        self.assertFalse(gate(result.report, "late_events_within_policy")["valid"])
        self.assertEqual(gate(result.report, "late_events_within_policy")["sample"], ["E031"])
        self.assertEqual(candidate_ids(result.anomalies, "product_signal"), [])

    def test_freshness_gate_uses_observation_end_date(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["observation_end_date"] = "2026-06-10"
        result = detect(spec=spec)
        self.assertFalse(gate(result.report, "freshness")["valid"])
        self.assertEqual(gate(result.report, "freshness")["observed"], "2026-06-09")
        self.assertIn("data-quality-freshness", candidate_ids(result.anomalies, "data_quality"))

    def test_received_before_occurred_fails_quality(self) -> None:
        events = copy.deepcopy(self.events)
        events[0]["received_at"] = "2026-06-01T08:59:00+03:00"
        result = detect(events=events)
        self.assertFalse(gate(result.report, "received_after_occurred")["valid"])
        self.assertEqual(gate(result.report, "received_after_occurred")["sample"], ["E001"])

    def test_period_volume_gate_catches_too_small_windows(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["quality_gates"]["min_events_per_period"] = 100
        result = detect(spec=spec)
        self.assertFalse(gate(result.report, "period_event_volume")["valid"])
        self.assertEqual(
            gate(result.report, "period_event_volume")["observed"],
            {"baseline": 22, "comparison": 18},
        )
        self.assertEqual(candidate_ids(result.anomalies, "product_signal"), [])

    def test_guardrail_delta_threshold_controls_product_signal(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["thresholds"]["guardrail_delta"] = 0.6
        result = detect(spec=spec)
        self.assertTrue(result.report["valid"])
        self.assertEqual(candidate_ids(result.anomalies, "product_signal"), [])
        self.assertEqual(candidate_ids(result.anomalies, "calendar_effect"), [])
        self.assertEqual(candidate_ids(result.anomalies, "composition"), ["composition-platform-android"])

    def test_composition_threshold_controls_composition_candidate(self) -> None:
        spec = copy.deepcopy(self.spec)
        spec["thresholds"]["composition_effect"] = 0.2
        result = detect(spec=spec)
        self.assertTrue(result.report["valid"])
        self.assertEqual(candidate_ids(result.anomalies, "composition"), [])
        self.assertEqual(len(candidate_ids(result.anomalies, "product_signal")), 3)

    def test_release_calendar_drives_calendar_effect(self) -> None:
        releases = [row for row in self.releases if row["release_id"] != "R002"]
        result = detect(releases=releases)
        self.assertTrue(result.report["valid"])
        self.assertEqual(candidate_ids(result.anomalies, "calendar_effect"), [])
        self.assertEqual(len(candidate_ids(result.anomalies, "product_signal")), 3)

    def test_cli_writes_anomalies_and_returns_nonzero_when_gates_fail(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            events = copy.deepcopy(self.events)
            events.append(copy.deepcopy(next(row for row in events if row["event_id"] == "E031")))
            event_path = tmp / "events.csv"
            output_path = tmp / "anomalies.json"
            write_csv(event_path, events, self.event_columns)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--users",
                    str(USERS),
                    "--events",
                    str(event_path),
                    "--tracking-plan",
                    str(TRACKING_PLAN),
                    "--release-calendar",
                    str(RELEASE_CALENDAR),
                    "--segments",
                    str(SEGMENTS),
                    "--guardrails",
                    str(GUARDRAILS),
                    "--spec",
                    str(SPEC_PATH),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            anomalies = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(anomalies["quality_gates_passed"])
            self.assertEqual(candidate_ids(anomalies, "product_signal"), [])


if __name__ == "__main__":
    unittest.main()
