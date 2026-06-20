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
ARTIFACT = ROOT / "outputs" / "event_model_validator.py"
EVENTS = ROOT.parent / "data" / "tiny" / "events.csv"
TRACKING_PLAN = ROOT / "outputs" / "tracking_plan.json"
METRIC_SPECS = ROOT.parent / "01-metric-tree" / "outputs" / "metric_specs.json"
SPEC = importlib.util.spec_from_file_location("event_model_validator", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def load_events() -> tuple[list[dict[str, str]], list[str]]:
    with EVENTS.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def load_plan() -> dict:
    return json.loads(TRACKING_PLAN.read_text(encoding="utf-8"))


def load_metrics() -> list[dict]:
    return VALIDATOR.normalize_metric_specs(json.loads(METRIC_SPECS.read_text(encoding="utf-8")))


def write_events(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class EventModelValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows, self.fieldnames = load_events()
        self.plan = load_plan()
        self.metrics = load_metrics()

    def validate(self, rows: list[dict[str, str]] | None = None, plan: dict | None = None) -> dict:
        return VALIDATOR.validate_event_model(
            plan or self.plan,
            rows or self.rows,
            self.metrics,
            self.fieldnames,
        )

    def test_valid_tiny_events_match_tracking_plan(self) -> None:
        report = self.validate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["events"], 41)
        self.assertEqual(report["summary"]["tracking_events"], 12)
        self.assertEqual(report["summary"]["metric_specs"], 5)

    def test_duplicate_event_id_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[1]["event_id"] = rows[0]["event_id"]
        report = self.validate(rows)
        duplicate_check = check(report, "event_ids_unique")
        self.assertFalse(duplicate_check["valid"])
        self.assertEqual(duplicate_check["sample"], ["E001"])

    def test_unknown_event_name_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[0]["event_name"] = "signup_begin"
        report = self.validate(rows)
        name_check = check(report, "event_names_known")
        self.assertFalse(name_check["valid"])
        self.assertEqual(name_check["sample"][0]["event_name"], "signup_begin")

    def test_unknown_event_version_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[0]["event_version"] = "99"
        report = self.validate(rows)
        version_check = check(report, "event_versions_known")
        self.assertFalse(version_check["valid"])
        self.assertEqual(version_check["sample"][0]["event_version"], "99")

    def test_missing_required_property_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[1]["properties_json"] = "{}"
        report = self.validate(rows)
        property_check = check(report, "required_properties_present")
        self.assertFalse(property_check["valid"])
        self.assertEqual(property_check["sample"][0]["missing"], ["method"])

    def test_invalid_properties_json_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[0]["properties_json"] = "{not-json"
        report = self.validate(rows)
        json_check = check(report, "properties_json_valid")
        self.assertFalse(json_check["valid"])
        self.assertEqual(json_check["sample"][0]["event_id"], "E001")

    def test_known_user_event_requires_user_id(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[1]["user_id"] = ""
        report = self.validate(rows)
        identity_check = check(report, "identity_policy_satisfied")
        self.assertFalse(identity_check["valid"])
        self.assertEqual(identity_check["sample"][0]["event_name"], "account_created")

    def test_received_at_before_occurred_at_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[1]["received_at"] = "2026-06-01T09:03:00+03:00"
        report = self.validate(rows)
        order_check = check(report, "received_after_occurred")
        self.assertFalse(order_check["valid"])
        self.assertEqual(order_check["sample"][0]["event_id"], "E002")

    def test_late_arrival_over_policy_is_rejected(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[1]["received_at"] = "2026-06-03T09:04:07+03:00"
        report = self.validate(rows)
        late_check = check(report, "late_arrivals_within_policy")
        self.assertFalse(late_check["valid"])
        self.assertEqual(late_check["sample"][0]["event_id"], "E002")

    def test_mobile_event_requires_app_version(self) -> None:
        rows = copy.deepcopy(self.rows)
        rows[8]["app_version"] = ""
        report = self.validate(rows)
        version_check = check(report, "mobile_app_version_present")
        self.assertFalse(version_check["valid"])
        self.assertEqual(version_check["sample"][0]["event_id"], "E009")

    def test_tracking_plan_metric_links_must_resolve(self) -> None:
        plan = copy.deepcopy(self.plan)
        plan["events"][0]["used_by_metrics"] = ["missing_metric"]
        report = self.validate(plan=plan)
        link_check = check(report, "metric_links_resolve")
        self.assertFalse(link_check["valid"])
        self.assertEqual(link_check["sample"][0]["metric_id"], "missing_metric")

    def test_cli_writes_report_and_returns_nonzero_for_invalid_log(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rows = copy.deepcopy(self.rows)
            rows[0]["event_name"] = "signup_begin"
            events_path = root / "events.csv"
            output_path = root / "event-model-report.json"
            write_events(events_path, rows, self.fieldnames)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--events",
                    events_path,
                    "--tracking-plan",
                    TRACKING_PLAN,
                    "--metric-specs",
                    METRIC_SPECS,
                    "--output",
                    output_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)["valid"])
            self.assertEqual(json.loads(result.stdout), json.loads(output_path.read_text()))


if __name__ == "__main__":
    unittest.main()
