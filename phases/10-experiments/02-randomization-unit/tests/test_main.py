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
PHASE_ROOT = ROOT.parent
DATA = PHASE_ROOT / "data" / "tiny"
ARTIFACT = ROOT / "outputs" / "assignment_engine.py"
SPEC_PATH = ROOT / "outputs" / "randomization_spec.json"
PROTOCOL = PHASE_ROOT / "01-hypothesis-and-metric" / "outputs" / "experiment_protocol.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("assignment_engine", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
ENGINE = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(ENGINE)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def load_examples() -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], dict, dict]:
    users = ENGINE.read_csv(DATA / "users.csv")
    events = ENGINE.read_csv(DATA / "events.csv")
    assignments = ENGINE.read_csv(DATA / "assignments.csv")
    exposures = ENGINE.read_csv(DATA / "exposures.csv")
    protocol = ENGINE.read_json(PROTOCOL)
    spec = ENGINE.read_json(SPEC_PATH)
    return users, events, assignments, exposures, protocol, spec


def write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None) -> None:
    fieldnames = fieldnames or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class AssignmentEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.users, self.events, self.assignments, self.exposures, self.protocol, self.spec = load_examples()

    def audit(
        self,
        assignments: list[dict[str, str]] | None = None,
        exposures: list[dict[str, str]] | None = None,
        users: list[dict[str, str]] | None = None,
        spec: dict | None = None,
    ) -> dict:
        return ENGINE.audit_assignment(
            self.assignments if assignments is None else assignments,
            self.exposures if exposures is None else exposures,
            self.users if users is None else users,
            self.protocol,
            self.spec if spec is None else spec,
        )

    def test_build_assignments_is_stable_and_matches_committed_fixture(self) -> None:
        generated = ENGINE.build_assignments(self.users, self.protocol, self.spec)
        self.assertEqual([row["bucket"] for row in generated], [870, 9916, 4643, 2880, 9142])
        self.assertEqual([row["variant_id"] for row in generated], ["control", "treatment", "control", "control", "treatment"])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "assignments.csv"
            ENGINE.write_csv(path, generated, ENGINE.ASSIGNMENT_FIELDS)
            self.assertEqual(ENGINE.read_csv(path), self.assignments)

    def test_valid_assignment_and_exposure_audit_passes(self) -> None:
        report = self.audit()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["assigned_units"], 5)
        self.assertEqual(report["summary"]["exposed_units"], 5)
        self.assertEqual(report["summary"]["variant_counts"], {"control": 3, "treatment": 2})

    def test_code_example_prints_assignment_preview(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["assignment_unit"], "user_id")
        self.assertEqual(payload["variant_counts"], {"control": 3, "treatment": 2})
        self.assertEqual(payload["assignment_preview"][0], {"user_id": "U001", "bucket": 870, "variant_id": "control"})

    def test_only_eligible_android_non_test_users_are_assigned(self) -> None:
        assigned_users = {row["user_id"] for row in self.assignments}
        self.assertEqual(assigned_users, {"U001", "U002", "U003", "U004", "U005"})
        self.assertNotIn("U006", assigned_users)
        self.assertNotIn("U007", assigned_users)
        self.assertNotIn("U999", assigned_users)

    def test_duplicate_assignment_unit_is_rejected(self) -> None:
        assignments = copy.deepcopy(self.assignments)
        assignments.append(dict(assignments[0]))
        report = self.audit(assignments=assignments)
        duplicate_check = check(report, "one_assignment_per_unit")
        self.assertFalse(duplicate_check["valid"])
        self.assertEqual(duplicate_check["sample"], ["U001"])

    def test_missing_eligible_user_is_rejected(self) -> None:
        assignments = [row for row in copy.deepcopy(self.assignments) if row["user_id"] != "U005"]
        report = self.audit(assignments=assignments)
        eligibility_check = check(report, "assignment_matches_eligibility")
        self.assertFalse(eligibility_check["valid"])
        self.assertEqual(eligibility_check["observed"]["missing"], ["U005"])

    def test_ineligible_assignment_is_rejected(self) -> None:
        assignments = copy.deepcopy(self.assignments)
        extra = dict(assignments[0])
        extra["assignment_unit_id"] = "U999"
        extra["user_id"] = "U999"
        assignments.append(extra)
        report = self.audit(assignments=assignments)
        eligibility_check = check(report, "assignment_matches_eligibility")
        self.assertFalse(eligibility_check["valid"])
        self.assertEqual(eligibility_check["observed"]["extra"], ["U999"])

    def test_changed_bucket_or_variant_breaks_stable_hash(self) -> None:
        assignments = copy.deepcopy(self.assignments)
        assignments[0]["bucket"] = "9999"
        assignments[1]["variant_id"] = "control"
        report = self.audit(assignments=assignments)
        stable_check = check(report, "assignment_hash_is_stable")
        self.assertFalse(stable_check["valid"])
        unit_ids = {item["assignment_unit_id"] for item in stable_check["sample"]}
        self.assertEqual(unit_ids, {"U001", "U002"})

    def test_balance_check_catches_extreme_split(self) -> None:
        assignments = copy.deepcopy(self.assignments)
        for row in assignments:
            row["variant_id"] = "control"
        report = self.audit(assignments=assignments)
        self.assertFalse(check(report, "assignment_hash_is_stable")["valid"])
        balance_check = check(report, "assignment_balance_within_tolerance")
        self.assertFalse(balance_check["valid"])
        self.assertEqual(balance_check["sample"][0]["variant_id"], "control")

    def test_exposure_variant_and_timing_are_checked(self) -> None:
        exposures = copy.deepcopy(self.exposures)
        exposures[0]["variant_id"] = "treatment"
        exposures[1]["exposed_at"] = "2026-06-09T23:00:00+03:00"
        exposures[2]["received_at"] = "2026-06-11T10:00:00+03:00"
        report = self.audit(exposures=exposures)
        exposure_check = check(report, "exposures_match_assignments_and_timing")
        self.assertFalse(exposure_check["valid"])
        reasons = {item.get("reason") for item in exposure_check["sample"]}
        self.assertIn("exposure before assignment", reasons)
        self.assertIn("received before exposed", reasons)

    def test_exposure_without_assignment_is_rejected(self) -> None:
        exposures = copy.deepcopy(self.exposures)
        exposures[0]["assignment_unit_id"] = "U404"
        report = self.audit(exposures=exposures)
        exposure_check = check(report, "exposures_match_assignments_and_timing")
        self.assertFalse(exposure_check["valid"])
        self.assertEqual(exposure_check["sample"][0]["reason"], "missing assignment")

    def test_interference_unit_split_across_variants_is_rejected(self) -> None:
        users = copy.deepcopy(self.users)
        for row in users:
            if row["user_id"] in {"U001", "U002"}:
                row["household_id"] = "H-SHARED"
        report = self.audit(users=users)
        interference_check = check(report, "interference_units_not_split")
        self.assertFalse(interference_check["valid"])
        self.assertEqual(interference_check["sample"][0]["column"], "household_id")

    def test_cli_can_write_assignments_exposures_and_report(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            assignments_path = root / "assignments.csv"
            exposures_path = root / "exposures.csv"
            report_path = root / "assignment-audit.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--users",
                    DATA / "users.csv",
                    "--events",
                    DATA / "events.csv",
                    "--protocol",
                    PROTOCOL,
                    "--spec",
                    SPEC_PATH,
                    "--write-assignments",
                    assignments_path,
                    "--write-exposures",
                    exposures_path,
                    "--output",
                    report_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(ENGINE.read_csv(assignments_path), self.assignments)
            self.assertEqual(ENGINE.read_csv(exposures_path), self.exposures)
            self.assertEqual(json.loads(result.stdout), json.loads(report_path.read_text()))

    def test_cli_returns_nonzero_for_bad_exposure_fixture(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bad_exposures = copy.deepcopy(self.exposures)
            bad_exposures.append(dict(bad_exposures[0]))
            exposure_path = root / "bad_exposures.csv"
            write_rows(exposure_path, bad_exposures)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--users",
                    DATA / "users.csv",
                    "--events",
                    DATA / "events.csv",
                    "--protocol",
                    PROTOCOL,
                    "--spec",
                    SPEC_PATH,
                    "--assignments",
                    DATA / "assignments.csv",
                    "--exposures",
                    exposure_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
