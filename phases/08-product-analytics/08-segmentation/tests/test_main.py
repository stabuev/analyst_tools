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
ARTIFACT = ROOT / "outputs" / "segmentation_calculator.py"
USERS = ROOT.parent / "data" / "tiny" / "users.csv"
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
TRACKING_PLAN = ROOT.parent / "02-event-model" / "outputs" / "tracking_plan.json"
SPEC_PATH = ROOT / "outputs" / "segmentation_spec.json"
SAMPLE_SEGMENTS = ROOT / "outputs" / "segments.csv"
MODULE_SPEC = importlib.util.spec_from_file_location("segmentation_calculator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CALCULATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(CALCULATOR)


def load_inputs() -> tuple[list[dict[str, str]], list[str], list[dict[str, str]], list[str], dict, dict]:
    users, user_columns = CALCULATOR.read_csv(USERS)
    events, event_columns = CALCULATOR.read_csv(EVENTS)
    tracking_plan = CALCULATOR.normalize_tracking_plan(CALCULATOR.read_json(TRACKING_PLAN))
    segmentation_spec = CALCULATOR.normalize_spec(CALCULATOR.read_json(SPEC_PATH))
    return users, user_columns, events, event_columns, tracking_plan, segmentation_spec


def calculate(
    users: list[dict[str, str]] | None = None,
    events: list[dict[str, str]] | None = None,
    tracking_plan: dict | None = None,
    segmentation_spec: dict | None = None,
) -> object:
    base_users, user_columns, base_events, event_columns, base_tracking_plan, base_spec = load_inputs()
    return CALCULATOR.calculate_segmentation(
        base_users if users is None else users,
        user_columns,
        base_events if events is None else events,
        event_columns,
        base_tracking_plan if tracking_plan is None else tracking_plan,
        base_spec if segmentation_spec is None else segmentation_spec,
    )


def row_for(
    rows: list[dict[str, str]],
    row_type: str,
    dimension: str,
    segment_value: str,
    period: str | None = None,
) -> dict[str, str]:
    return next(
        row
        for row in rows
        if row["row_type"] == row_type
        and row["dimension"] == dimension
        and row["segment_value"] == segment_value
        and (period is None or row["period"] == period)
    )


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def add_user(users: list[dict[str, str]], user_id: str, registered_at: str) -> list[dict[str, str]]:
    updated = copy.deepcopy(users)
    user = copy.deepcopy(updated[0])
    user.update({
        "user_id": user_id,
        "registered_at": registered_at,
        "country": "RU",
        "acquisition_channel": "organic",
        "platform": "web",
        "is_test_user": "false",
    })
    updated.append(user)
    return updated


def add_event(
    events: list[dict[str, str]],
    event_id: str,
    user_id: str,
    occurred_at: str,
    received_at: str | None = None,
) -> list[dict[str, str]]:
    updated = copy.deepcopy(events)
    event = copy.deepcopy(next(row for row in updated if row["event_name"] == "feature_value_seen"))
    event.update({
        "event_id": event_id,
        "user_id": user_id,
        "anonymous_id": f"A{user_id[-3:]}" if user_id else "A000",
        "session_id": f"S{user_id[-3:]}" if user_id else "S000",
        "event_name": "feature_value_seen",
        "occurred_at": occurred_at,
        "received_at": received_at or occurred_at,
        "platform": "web",
        "app_version": "",
        "properties_json": "{\"feature\":\"weekly_plan\"}",
    })
    updated.append(event)
    return updated


class SegmentationCalculatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.users, self.user_columns, self.events, self.event_columns, self.tracking_plan, self.spec = load_inputs()

    def test_valid_tiny_segmentation_has_expected_rates_and_decomposition(self) -> None:
        result = calculate()
        self.assertTrue(result.report["valid"])
        self.assertEqual(result.report["summary"]["rows"], 22)
        self.assertEqual(result.report["summary"]["segment_metric_rows"], 17)
        self.assertEqual(result.report["summary"]["decomposition_rows"], 3)
        self.assertEqual(result.report["summary"]["eligible_users"], 7)
        self.assertEqual(result.report["summary"]["excluded_test_users"], 1)
        self.assertEqual(result.report["summary"]["overall_baseline_rate"], "0.500000")
        self.assertEqual(result.report["summary"]["overall_comparison_rate"], "0.333333")
        self.assertEqual(result.report["summary"]["overall_delta"], "-0.166667")
        baseline = row_for(result.table, "overall", "__overall__", "__all__", "baseline")
        comparison = row_for(result.table, "overall", "__overall__", "__all__", "comparison")
        self.assertEqual(baseline["eligible_users"], "4")
        self.assertEqual(baseline["activated_users"], "2")
        self.assertEqual(comparison["eligible_users"], "3")
        self.assertEqual(comparison["activated_users"], "1")
        android = row_for(result.table, "decomposition", "platform", "android")
        self.assertEqual(android["within_segment_effect"], "-0.166667")
        self.assertEqual(android["composition_effect"], "-0.083333")
        self.assertEqual(android["total_delta_contribution"], "-0.250000")

    def test_sample_segments_csv_matches_calculated_table(self) -> None:
        result = calculate()
        with SAMPLE_SEGMENTS.open(encoding="utf-8", newline="") as source:
            expected = list(csv.DictReader(source))
        self.assertEqual(result.table, expected)

    def test_exploratory_country_segments_are_marked_without_hiding_predeclared_segments(self) -> None:
        result = calculate()
        country_rows = [row for row in result.table if row["row_type"] == "segment_metric" and row["dimension"] == "country"]
        predeclared_rows = [
            row
            for row in result.table
            if row["row_type"] == "segment_metric" and row["dimension"] in {"platform", "acquisition_channel"}
        ]
        self.assertTrue(country_rows)
        self.assertTrue(all(row["is_exploratory"] == "true" for row in country_rows))
        self.assertTrue(all(row["is_exploratory"] == "false" for row in predeclared_rows))

    def test_minimum_cell_size_suppresses_small_segment_rates(self) -> None:
        segmentation_spec = copy.deepcopy(self.spec)
        segmentation_spec["minimum_cell_size"] = 2
        result = calculate(segmentation_spec=segmentation_spec)
        self.assertTrue(result.report["valid"])
        web = row_for(result.table, "segment_metric", "platform", "web", "baseline")
        android = row_for(result.table, "segment_metric", "platform", "android", "baseline")
        decomposition = row_for(result.table, "decomposition", "platform", "android")
        self.assertEqual(web["eligible_users"], "1")
        self.assertEqual(web["is_reportable"], "false")
        self.assertEqual(web["activation_rate"], "")
        self.assertEqual(android["is_reportable"], "true")
        self.assertEqual(android["activation_rate"], "0.500000")
        self.assertEqual(decomposition["is_reportable"], "false")
        self.assertEqual(decomposition["total_delta_contribution"], "")

    def test_primary_decomposition_dimension_must_be_predeclared(self) -> None:
        segmentation_spec = copy.deepcopy(self.spec)
        segmentation_spec["primary_decomposition_dimension"] = "country"
        result = calculate(segmentation_spec=segmentation_spec)
        self.assertFalse(result.report["valid"])
        self.assertFalse(check(result.report, "primary_decomposition_dimension_valid")["valid"])
        self.assertEqual(result.table, [])

    def test_activation_event_must_exist_in_tracking_plan(self) -> None:
        segmentation_spec = copy.deepcopy(self.spec)
        segmentation_spec["activation_event_name"] = "unknown_activation"
        result = calculate(segmentation_spec=segmentation_spec)
        self.assertFalse(result.report["valid"])
        self.assertFalse(check(result.report, "activation_event_in_tracking_plan")["valid"])
        self.assertFalse(check(result.report, "segment_rows_present")["valid"])

    def test_duplicate_event_id_is_reported_and_deduplicated(self) -> None:
        events = copy.deepcopy(self.events)
        events.append(copy.deepcopy(next(row for row in events if row["event_id"] == "E031")))
        result = calculate(events=events)
        self.assertFalse(result.report["valid"])
        self.assertEqual(check(result.report, "event_ids_unique")["sample"], ["E031"])
        self.assertEqual(result.report["summary"]["deduplicated_events"], 41)
        comparison = row_for(result.table, "overall", "__overall__", "__all__", "comparison")
        self.assertEqual(comparison["activated_users"], "1")
        self.assertEqual(comparison["activation_rate"], "0.333333")

    def test_activation_event_requires_user_id(self) -> None:
        events = add_event(self.events, "E900", "", "2026-06-05T14:56:00+03:00")
        result = calculate(events=events)
        self.assertFalse(result.report["valid"])
        self.assertFalse(check(result.report, "activation_events_have_user_id")["valid"])
        self.assertEqual(check(result.report, "activation_events_have_user_id")["sample"][0]["event_id"], "E900")

    def test_activation_event_user_must_exist(self) -> None:
        events = add_event(self.events, "E900", "U404", "2026-06-05T14:56:00+03:00")
        result = calculate(events=events)
        self.assertFalse(result.report["valid"])
        self.assertFalse(check(result.report, "activation_events_reference_known_users")["valid"])
        self.assertEqual(check(result.report, "activation_events_reference_known_users")["sample"][0]["user_id"], "U404")

    def test_late_activation_event_breaks_quality_report(self) -> None:
        events = copy.deepcopy(self.events)
        event = next(row for row in events if row["event_id"] == "E031")
        event["received_at"] = "2026-06-07T14:56:07+03:00"
        result = calculate(events=events)
        self.assertFalse(result.report["valid"])
        self.assertFalse(check(result.report, "late_events_within_policy")["valid"])
        self.assertEqual(check(result.report, "late_events_within_policy")["sample"][0]["event_id"], "E031")

    def test_business_timezone_controls_period_assignment(self) -> None:
        users = add_user(self.users, "U008", "2026-06-03T22:30:00+00:00")
        events = add_event(self.events, "E900", "U008", "2026-06-03T23:00:00+00:00")
        result = calculate(users=users, events=events)
        comparison = row_for(result.table, "overall", "__overall__", "__all__", "comparison")
        self.assertEqual(comparison["eligible_users"], "4")
        self.assertEqual(comparison["activated_users"], "2")
        self.assertEqual(comparison["activation_rate"], "0.500000")
        self.assertEqual(result.report["summary"]["overall_delta"], "0.000000")

    def test_observation_end_excludes_incomplete_users(self) -> None:
        segmentation_spec = copy.deepcopy(self.spec)
        segmentation_spec["observation_end_date"] = "2026-06-04"
        result = calculate(segmentation_spec=segmentation_spec)
        self.assertTrue(result.report["valid"])
        self.assertEqual(result.report["summary"]["excluded_incomplete_users"], 2)
        comparison = row_for(result.table, "overall", "__overall__", "__all__", "comparison")
        self.assertEqual(comparison["eligible_users"], "1")
        self.assertEqual(comparison["activation_rate"], "0.000000")

    def test_causal_claims_are_forbidden_without_experiment(self) -> None:
        segmentation_spec = copy.deepcopy(self.spec)
        segmentation_spec["allowed_claim_types"] = ["descriptive", "hypothesis", "causal"]
        result = calculate(segmentation_spec=segmentation_spec)
        self.assertFalse(result.report["valid"])
        self.assertFalse(check(result.report, "causal_claims_forbidden")["valid"])
        self.assertEqual(result.table, [])

    def test_decomposition_contributions_sum_to_overall_delta(self) -> None:
        result = calculate()
        decomposition_rows = [row for row in result.table if row["row_type"] == "decomposition"]
        contribution_sum = sum(float(row["total_delta_contribution"]) for row in decomposition_rows)
        overall_delta = float(result.report["summary"]["overall_delta"])
        self.assertAlmostEqual(contribution_sum, overall_delta, places=6)
        web = row_for(result.table, "decomposition", "platform", "web")
        self.assertEqual(web["within_segment_effect"], "0.000000")
        self.assertEqual(web["composition_effect"], "0.083333")

    def test_cli_writes_segments_csv_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output_path = root / "segments.csv"
            report_path = root / "segmentation-report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--users",
                    USERS,
                    "--events",
                    EVENTS,
                    "--tracking-plan",
                    TRACKING_PLAN,
                    "--spec",
                    SPEC_PATH,
                    "--output",
                    output_path,
                    "--report",
                    report_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["valid"])
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text(encoding="utf-8")))
            with output_path.open(encoding="utf-8", newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 22)

            invalid_spec = copy.deepcopy(self.spec)
            invalid_spec["activation_event_name"] = "unknown_activation"
            invalid_spec_path = root / "bad_segmentation_spec.json"
            invalid_spec_path.write_text(json.dumps(invalid_spec, ensure_ascii=False, indent=2), encoding="utf-8")
            invalid_result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--users",
                    USERS,
                    "--events",
                    EVENTS,
                    "--tracking-plan",
                    TRACKING_PLAN,
                    "--spec",
                    invalid_spec_path,
                    "--output",
                    root / "bad-segments.csv",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(invalid_result.returncode, 1, invalid_result.stderr)
            self.assertFalse(json.loads(invalid_result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
