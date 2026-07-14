from __future__ import annotations

import copy
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = LESSON_ROOT / "outputs" / "capstone_brief_validator.py"
CODE = LESSON_ROOT / "code" / "main.py"
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

import capstone_brief_validator as BRIEF  # noqa: E402


def find_check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def write_json(path: Path, value: dict) -> Path:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CapstoneBriefValidatorTest(TestCase):
    def validate(self, mutate=None) -> tuple[dict, dict]:
        brief = BRIEF.default_capstone_brief()
        if mutate is not None:
            mutate(brief)
        return brief, BRIEF.validate_capstone_brief(brief)

    def build(self, root: Path, mutate=None) -> dict:
        brief = BRIEF.default_capstone_brief()
        if mutate is not None:
            mutate(brief)
        brief_path = write_json(root / "capstone_brief.json", brief)
        return BRIEF.build_capstone_brief_package(
            brief_path=brief_path,
            output_dir=root / "package",
        )

    def test_reference_brief_is_ready_with_visible_reference_warning(self) -> None:
        brief, report = self.validate()

        self.assertTrue(report["valid"])
        self.assertEqual(report["status"], "ready_for_data_contract")
        self.assertEqual(report["summary"]["next_stage"], "data_contract")
        self.assertEqual(report["summary"]["estimated_hours"], 44)
        self.assertEqual(report["summary"]["risk_count"], 6)
        self.assertEqual(report["summary"]["milestone_count"], 7)
        self.assertEqual(report["summary"]["blocking_errors"], [])
        self.assertEqual(
            report["summary"]["warnings"],
            ["reference_profile_is_not_portfolio_evidence"],
        )
        self.assertEqual(sum(row["estimated_hours"] for row in brief["milestones"]), 44)

    def test_code_example_writes_committed_outputs(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)

        self.assertTrue(payload["valid"])
        self.assertEqual(payload["status"], "ready_for_data_contract")
        self.assertEqual(payload["estimated_hours"], 44)
        self.assertEqual(payload["risk_count"], 6)
        self.assertEqual(payload["milestone_count"], 7)
        for name in (
            "capstone_brief_audit.json",
            "risk_register.csv",
            "milestone_plan.csv",
            "capstone_state.json",
            "brief_manifest.json",
        ):
            self.assertTrue((LESSON_ROOT / "outputs" / name).is_file(), name)

    def test_cli_write_example_builds_package_and_help_names_contract(self) -> None:
        help_result = subprocess.run(
            [sys.executable, ARTIFACT, "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--brief", help_result.stdout)
        self.assertIn("--write-example", help_result.stdout)
        self.assertIn("--fail-on-invalid", help_result.stdout)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--write-example",
                    root / "input",
                    "--output-dir",
                    root / "package",
                    "--fail-on-invalid",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(result.stdout)

            self.assertTrue(payload["valid"])
            self.assertTrue((root / "input" / "capstone_brief.json").is_file())
            self.assertTrue((root / "package" / "brief_manifest.json").is_file())

    def test_missing_required_field_blocks_before_data_contract(self) -> None:
        _brief, report = self.validate(lambda value: value.pop("decision_owner"))

        self.assertFalse(report["valid"])
        self.assertEqual(report["status"], "brief_revision_required")
        self.assertIn("brief_required_fields", report["summary"]["blocking_errors"])
        self.assertFalse(find_check(report, "decision_precedes_analysis")["valid"])

    def test_decision_requires_accountable_owner_and_no_action(self) -> None:
        def mutate(brief: dict) -> None:
            brief["decision_owner"]["accountable"] = False
            brief["decision_options"] = [brief["decision_options"][1]]

        _brief, report = self.validate(mutate)
        observed = find_check(report, "decision_precedes_analysis")["observed"]

        self.assertFalse(report["valid"])
        self.assertIn("decision_precedes_analysis", report["summary"]["blocking_errors"])
        self.assertIn("targeted_manual_review", observed["option_ids"])
        self.assertNotIn("no_action", observed["option_ids"])

    def test_all_route_variants_compute_minimal_prerequisites(self) -> None:
        profiles = [
            ("core_analytics", "standard", "descriptive", [*range(8), 17]),
            ("product_experiments", "standard", "product_decision", [*range(11), 17]),
            ("data_analytics_engineering", "standard", "data_quality", [*range(8), 11, 12, 17]),
            ("decision_science", "causal", "causal", [*range(8), 13, 17]),
            ("decision_science", "forecast", "forecast", [*range(8), 14, 17]),
            ("machine_learning", "baseline", "predictive", [*range(8), 15, 17]),
            ("machine_learning", "strong_model", "decision_policy", [*range(8), 15, 16, 17]),
            ("delivery_product", "standard", "delivery_quality", [*range(8), 17]),
        ]
        for route, variant, claim_type, expected in profiles:
            with self.subTest(route=route, variant=variant):
                brief = BRIEF.default_capstone_brief()
                brief["profile_kind"] = "student_project"
                brief["route"] = route
                brief["route_variant"] = variant
                brief["claim_type"] = claim_type
                brief["declared_prerequisites"] = expected
                if route == "delivery_product":
                    brief["upstream_package_id"] = "verified-evidence-package"
                    brief["upstream_claim_type"] = "descriptive"

                report = BRIEF.validate_capstone_brief(brief)

                self.assertTrue(report["valid"], report["summary"]["blocking_errors"])
                self.assertEqual(report["summary"]["required_prerequisites"], expected)

    def test_missing_and_unnecessary_route_prerequisites_are_visible(self) -> None:
        def mutate(brief: dict) -> None:
            brief["declared_prerequisites"].remove(7)
            brief["declared_prerequisites"].append(16)
            brief["completed_phases"].remove(7)

        _brief, report = self.validate(mutate)
        route_check = find_check(report, "route_prerequisites_are_minimal_and_complete")
        errors = route_check["observed"]["errors"]

        self.assertFalse(report["valid"])
        self.assertIn(7, errors[0]["missing"])
        self.assertIn(16, errors[0]["unnecessary"])
        self.assertIn(7, errors[1]["missing"])

    def test_claim_type_cannot_exceed_route_boundary(self) -> None:
        _brief, report = self.validate(lambda value: value.__setitem__("claim_type", "causal"))
        claim = find_check(report, "claim_matches_route_boundary")

        self.assertFalse(report["valid"])
        self.assertFalse(claim["valid"])
        self.assertEqual(
            claim["observed"]["errors"][0]["allowed"], ["associational", "descriptive"]
        )

    def test_decision_science_variant_and_claim_must_align(self) -> None:
        def mutate(brief: dict) -> None:
            brief["route"] = "decision_science"
            brief["route_variant"] = "causal"
            brief["claim_type"] = "forecast"
            brief["declared_prerequisites"] = [*range(8), 13, 17]

        _brief, report = self.validate(mutate)
        claim = find_check(report, "claim_matches_route_boundary")

        self.assertFalse(report["valid"])
        self.assertEqual(claim["observed"]["errors"][0]["field"], "route_variant/claim_type")

    def test_delivery_route_requires_verified_upstream_boundary(self) -> None:
        def mutate(brief: dict) -> None:
            brief["route"] = "delivery_product"
            brief["route_variant"] = "standard"
            brief["claim_type"] = "upstream_preserving"

        _brief, report = self.validate(mutate)
        fields = {
            item["field"]
            for item in find_check(report, "claim_matches_route_boundary")["observed"]["errors"]
        }

        self.assertFalse(report["valid"])
        self.assertEqual(fields, {"upstream_package_id", "upstream_claim_type"})

    def test_scope_outside_budget_and_milestone_total_both_block(self) -> None:
        _brief, report = self.validate(
            lambda value: value["scope"].__setitem__("estimated_hours", 90)
        )

        self.assertFalse(find_check(report, "scope_fits_capstone_budget")["valid"])
        milestone = find_check(report, "milestones_cover_all_stage_gates")
        self.assertFalse(milestone["valid"])
        self.assertEqual(milestone["observed"]["total_hours"], 44.0)

    def test_scope_requires_non_goals_stop_conditions_and_deliverables(self) -> None:
        def mutate(brief: dict) -> None:
            brief["scope"]["non_goals"] = []
            brief["scope"]["stop_conditions"] = ["if it becomes difficult"]
            brief["scope"]["deliverables"] = ["notebook"]

        _brief, report = self.validate(mutate)
        errors = find_check(report, "scope_fits_capstone_budget")["observed"]["errors"]

        self.assertFalse(report["valid"])
        self.assertEqual(
            {item["field"] for item in errors},
            {"scope.non_goals", "scope.stop_conditions", "scope.deliverables"},
        )

    def test_success_criteria_need_unique_ids_and_acceptance_tests(self) -> None:
        def mutate(brief: dict) -> None:
            brief["success_criteria"][1]["id"] = brief["success_criteria"][0]["id"]
            brief["success_criteria"][1]["acceptance_test"] = ""

        _brief, report = self.validate(mutate)
        errors = find_check(report, "success_criteria_are_testable")["observed"]["errors"]

        self.assertFalse(report["valid"])
        self.assertIn("success_criteria.id", {item.get("field") for item in errors})
        self.assertIn("acceptance_test", {item.get("field") for item in errors})

    def test_risk_register_must_cover_review_and_have_actionable_rows(self) -> None:
        def mutate(brief: dict) -> None:
            brief["risks"] = [row for row in brief["risks"] if row["category"] != "review"]
            brief["risks"][0]["trigger"] = ""

        _brief, report = self.validate(mutate)
        risk = find_check(report, "risk_register_covers_capstone_lifecycle")

        self.assertFalse(report["valid"])
        self.assertIn("review", risk["observed"]["errors"][-1]["missing"])
        self.assertEqual(risk["observed"]["errors"][0]["field"], "trigger")

    def test_milestones_require_stage_order_dependencies_and_matching_hours(self) -> None:
        def mutate(brief: dict) -> None:
            brief["milestones"][4], brief["milestones"][6] = (
                brief["milestones"][6],
                brief["milestones"][4],
            )
            brief["milestones"][1]["depends_on"] = []
            brief["milestones"][3]["estimated_hours"] = 10

        _brief, report = self.validate(mutate)
        milestone = find_check(report, "milestones_cover_all_stage_gates")

        self.assertFalse(report["valid"])
        fields = {item["field"] for item in milestone["observed"]["errors"]}
        self.assertIn("depends_on", fields)
        self.assertIn("milestones.stage", fields)
        self.assertIn("milestones.estimated_hours", fields)

    def test_assistance_policy_requires_disclosure_and_author_accountability(self) -> None:
        def mutate(brief: dict) -> None:
            brief["assistance_disclosure"]["disclosure_required"] = False
            brief["assistance_disclosure"]["author_accountability"] = ""
            brief["assistance_disclosure"]["prohibited_uses"] = []

        _brief, report = self.validate(mutate)
        disclosure = find_check(report, "assistance_is_disclosed_without_delegating_accountability")

        self.assertFalse(report["valid"])
        self.assertEqual(len(disclosure["observed"]["errors"]), 3)

    def test_state_hands_off_only_problem_selection_evidence(self) -> None:
        with TemporaryDirectory() as directory:
            result = self.build(Path(directory))
            state = read_json(result["state_path"])

        self.assertEqual(state["current_stage"], "problem_selection")
        self.assertEqual(state["stage_status"], "ready_for_data_contract")
        self.assertIsNone(state["data_contract_id"])
        self.assertIsNone(state["baseline_id"])
        self.assertEqual(state["open_blockers"], [])
        self.assertEqual(state["warnings"], ["reference_profile_is_not_portfolio_evidence"])
        self.assertEqual(len(state["route_prerequisites"]), 9)

    def test_csv_outputs_and_manifest_are_deterministic_and_hash_checked(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.build(root)
            manifest = read_json(result["manifest_path"])
            with result["risk_register_path"].open(encoding="utf-8", newline="") as source:
                risks = list(csv.DictReader(source))
            with result["milestone_plan_path"].open(encoding="utf-8", newline="") as source:
                milestones = list(csv.DictReader(source))

            self.assertEqual(len(risks), 6)
            self.assertEqual(len(milestones), 7)
            self.assertEqual(milestones[0]["depends_on"], "")
            self.assertEqual(milestones[-1]["depends_on"], "m06")
            self.assertEqual(manifest["renderer_used"], "capstone_brief_validator")
            self.assertEqual(
                set(manifest["outputs"]),
                {"audit", "risk_register", "milestone_plan", "capstone_state"},
            )
            for entry in manifest["outputs"].values():
                path = result["output_dir"] / entry["path"]
                self.assertEqual(entry["sha256"], sha256(path))
                self.assertEqual(entry["bytes"], path.stat().st_size)

    def test_cli_exit_codes_distinguish_blocked_brief_and_system_error(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            brief = BRIEF.default_capstone_brief()
            brief["scope"]["estimated_hours"] = 90
            brief_path = write_json(root / "bad_brief.json", brief)
            blocked = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--brief",
                    brief_path,
                    "--output-dir",
                    root / "blocked",
                    "--fail-on-invalid",
                ],
                capture_output=True,
                text=True,
            )
            missing = subprocess.run(
                [sys.executable, ARTIFACT, "--output-dir", root / "missing"],
                capture_output=True,
                text=True,
            )

        self.assertEqual(blocked.returncode, 1)
        self.assertEqual(json.loads(blocked.stdout)["status"], "brief_revision_required")
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stdout)["error"]["code"], "missing_brief")

    def test_default_brief_is_not_mutated_by_validation(self) -> None:
        brief = BRIEF.default_capstone_brief()
        original = copy.deepcopy(brief)

        BRIEF.validate_capstone_brief(brief)

        self.assertEqual(brief, original)


if __name__ == "__main__":
    import unittest

    unittest.main()
