from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
PHASE_ROOT = ROOT.parent
DAG = PHASE_ROOT / "02-causal-dags" / "outputs" / "causal_dag.json"
POLICY = ROOT / "outputs" / "bad_control_policy.json"
ACTIONS = ROOT / "outputs" / "candidate_control_actions.json"
DATA_CONTRACT = PHASE_ROOT / "data" / "contract.json"
ARTIFACT = ROOT / "outputs" / "bad_control_selection_auditor.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("bad_control_selection_auditor", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(AUDITOR)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def action(report: dict, action_id: str) -> dict:
    return next(
        item for item in report["candidate_action_audits"] if item["action_id"] == action_id
    )


def action_spec(spec: dict, action_id: str) -> dict:
    return next(
        item for item in spec["candidate_control_actions"] if item["action_id"] == action_id
    )


def bad_control(policy: dict, variable: str) -> dict:
    return next(item for item in policy["bad_controls"] if item["variable"] == variable)


class BadControlSelectionAuditorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dag = read_json(DAG)
        self.policy = read_json(POLICY)
        self.actions = read_json(ACTIONS)
        self.data_contract = read_json(DATA_CONTRACT)

    def validate(
        self,
        *,
        dag: dict | None = None,
        policy: dict | None = None,
        actions: dict | None = None,
        data_contract: dict | None = None,
    ) -> dict:
        return AUDITOR.validate_specs(
            self.dag if dag is None else dag,
            self.policy if policy is None else policy,
            self.actions if actions is None else actions,
            self.data_contract if data_contract is None else data_contract,
        )

    def test_valid_policy_allows_only_baseline_handoff(self) -> None:
        report = self.validate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["initial_active_total_paths"], 50)
        self.assertEqual(report["summary"]["initial_active_backdoor_paths"], 48)
        self.assertEqual(report["summary"]["directed_total_effect_paths"], 2)
        self.assertEqual(
            report["summary"]["allowed_candidate_actions"],
            ["recommended_pre_treatment_set"],
        )
        self.assertEqual(report["summary"]["primary_open_measured_backdoor_paths"], 0)
        self.assertEqual(report["summary"]["primary_open_unmeasured_backdoor_paths"], 1)
        self.assertIn("telemetry_complete_30d", report["summary"]["bad_control_variables"])

    def test_code_example_prints_compact_teaching_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["primary_action"], "recommended_pre_treatment_set")
        self.assertEqual(payload["primary_open_unmeasured_paths"], 1)
        self.assertEqual(payload["mediator_blocks_directed_paths"], 1)
        self.assertGreater(payload["collider_newly_opened_paths"], 0)
        self.assertGreater(payload["selection_newly_opened_paths"], 0)

    def test_mediator_control_blocks_directed_total_effect_path(self) -> None:
        report = self.validate()
        mediator = action(report, "mediator_adjusted_total_effect")
        self.assertEqual(mediator["calculated_status"], "invalid_blocks_total_effect")
        self.assertEqual(mediator["blocked_directed_total_effect_paths"], 1)
        blocked_paths = {
            item["path_text"] for item in mediator["blocked_directed_total_effect_path_examples"]
        }
        self.assertIn(
            "assisted_within_24h -> onboarding_completed_48h -> activation_14d",
            blocked_paths,
        )
        completion = next(
            item
            for item in mediator["variable_classifications"]
            if item["variable"] == "onboarding_completed_48h"
        )
        self.assertTrue(completion["on_directed_total_effect_path"])

    def test_collider_filter_opens_support_chat_paths(self) -> None:
        report = self.validate()
        collider = action(report, "support_chat_restricted_cohort")
        self.assertEqual(collider["calculated_status"], "invalid_opens_collider_bias")
        self.assertTrue(collider["changes_population"])
        self.assertGreater(collider["newly_opened_paths"], 0)
        support_chat = next(
            item
            for item in collider["variable_classifications"]
            if item["variable"] == "opened_support_chat_after_offer"
        )
        mechanism_paths = [item["path"] for item in support_chat["mechanism_path_examples"]]
        self.assertTrue(any("opened_support_chat_after_offer" in path for path in mechanism_paths))
        self.assertTrue(any("friction_score" in path for path in mechanism_paths))

    def test_selection_filter_requires_population_change_and_opens_paths(self) -> None:
        report = self.validate()
        selection = action(report, "telemetry_complete_case_filter")
        self.assertEqual(selection["calculated_status"], "invalid_selection_bias")
        self.assertTrue(selection["changes_population"])
        self.assertGreater(selection["newly_opened_paths"], 0)
        telemetry = next(
            item
            for item in selection["variable_classifications"]
            if item["variable"] == "telemetry_complete_30d"
        )
        self.assertIn(
            "post_treatment_selection_changes_population",
            telemetry["bad_control_reasons"],
        )
        self.assertTrue(telemetry["mechanism_path_examples"])

    def test_assignment_mechanism_changes_received_treatment_question(self) -> None:
        report = self.validate()
        offer = action(report, "offer_split_set")
        self.assertEqual(offer["calculated_status"], "invalid_changes_treatment_definition")
        offered = next(
            item
            for item in offer["variable_classifications"]
            if item["variable"] == "offered_assistance"
        )
        self.assertEqual(offered["role"], "assignment_mechanism")
        self.assertFalse(offered["is_descendant_of_treatment"])

    def test_feature_soup_is_rejected_as_multiple_bad_controls(self) -> None:
        report = self.validate()
        soup = action(report, "feature_soup_post_treatment")
        self.assertEqual(soup["calculated_status"], "invalid_multiple_bad_controls")
        statuses = {item["core_status"] for item in soup["bad_control_variables"]}
        self.assertEqual(
            statuses,
            {
                "invalid_blocks_total_effect",
                "invalid_opens_collider_bias",
                "invalid_selection_bias",
            },
        )

    def test_outcome_and_secondary_outcome_are_leakage_controls(self) -> None:
        report = self.validate()
        primary_outcome = action(report, "outcome_as_feature")
        secondary_outcome = action(report, "secondary_outcome_as_control")
        self.assertEqual(primary_outcome["calculated_status"], "invalid_outcome_leakage")
        self.assertEqual(secondary_outcome["calculated_status"], "invalid_outcome_leakage")
        paid = secondary_outcome["bad_control_variables"][0]
        self.assertTrue(paid["is_descendant_of_treatment"])
        self.assertIn("descendant_of_treatment", paid["bad_control_reasons"])

    def test_policy_must_cover_all_graph_bad_controls(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["bad_controls"] = [
            item for item in policy["bad_controls"] if item["variable"] != "telemetry_complete_30d"
        ]
        report = self.validate(policy=policy)
        coverage = check(report, "policy_covers_graph_bad_controls")
        self.assertFalse(report["valid"])
        self.assertFalse(coverage["valid"])
        self.assertIn("telemetry_complete_30d", coverage["sample"])

    def test_policy_classification_must_match_graph_role(self) -> None:
        policy = copy.deepcopy(self.policy)
        bad_control(policy, "onboarding_completed_48h")["expected_status"] = (
            "allowed_pre_treatment_adjustment"
        )
        report = self.validate(policy=policy)
        classification = check(report, "bad_control_policy_classifications_match_graph")
        self.assertFalse(report["valid"])
        self.assertFalse(classification["valid"])
        self.assertEqual(classification["sample"][0]["variable"], "onboarding_completed_48h")

    def test_bad_control_source_fields_must_exist_in_data_contract(self) -> None:
        dag = copy.deepcopy(self.dag)
        node = next(item for item in dag["nodes"] if item["id"] == "telemetry_complete_30d")
        node["source_fields"].append({"table": "outcomes", "field": "ghost_completeness"})
        report = self.validate(dag=dag)
        source_check = check(report, "bad_control_source_fields_exist")
        self.assertFalse(report["valid"])
        self.assertFalse(source_check["valid"])
        self.assertEqual(source_check["sample"][0]["variable"], "telemetry_complete_30d")

    def test_candidate_declared_status_must_match_audit(self) -> None:
        actions = copy.deepcopy(self.actions)
        action_spec(actions, "support_chat_restricted_cohort")["declared_status"] = (
            "allowed_pre_treatment_adjustment"
        )
        report = self.validate(actions=actions)
        status = check(report, "candidate_statuses_match_audit")
        self.assertFalse(report["valid"])
        self.assertFalse(status["valid"])
        self.assertEqual(status["sample"][0]["action_id"], "support_chat_restricted_cohort")

    def test_primary_recommendation_cannot_contain_bad_control(self) -> None:
        actions = copy.deepcopy(self.actions)
        primary = action_spec(actions, "recommended_pre_treatment_set")
        primary["variables"].append("onboarding_completed_48h")
        primary["declared_status"] = "invalid_blocks_total_effect"
        primary["allowed_for_estimation"] = False
        report = self.validate(actions=actions)
        primary_check = check(
            report,
            "primary_recommendation_has_no_bad_controls_and_blocks_measured_backdoors",
        )
        self.assertFalse(report["valid"])
        self.assertFalse(primary_check["valid"])
        self.assertEqual(primary_check["sample"][0]["reason"], "primary contains bad controls")

    def test_filter_actions_must_explain_population_change(self) -> None:
        actions = copy.deepcopy(self.actions)
        action_spec(actions, "telemetry_complete_case_filter")["population_change"] = ""
        report = self.validate(actions=actions)
        filter_check = check(report, "filter_actions_declare_population_change")
        self.assertFalse(report["valid"])
        self.assertFalse(filter_check["valid"])
        self.assertEqual(filter_check["sample"][0]["action_id"], "telemetry_complete_case_filter")

    def test_unknown_candidate_variable_is_rejected_even_when_declared(self) -> None:
        actions = copy.deepcopy(self.actions)
        actions["candidate_control_actions"].append(
            {
                "action_id": "unknown_feature",
                "label": "Unknown feature",
                "action_type": "feature_set",
                "variables": ["ghost_post_treatment_feature"],
                "filter_variables": [],
                "is_primary_recommendation": False,
                "allowed_for_estimation": False,
                "declared_status": "invalid_unknown_variable",
                "interpretation": "Unknown variables are not valid teaching counterexamples.",
            }
        )
        report = self.validate(actions=actions)
        unknown = check(report, "candidate_variables_exist_in_graph")
        self.assertFalse(report["valid"])
        self.assertFalse(unknown["valid"])
        self.assertEqual(unknown["sample"][0]["variables"], ["ghost_post_treatment_feature"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = copy.deepcopy(self.actions)
            action_spec(invalid, "telemetry_complete_case_filter")["allowed_for_estimation"] = True
            actions_path = root / "candidate_control_actions.json"
            output_path = root / "audit.json"
            write_json(actions_path, invalid)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--dag",
                    DAG,
                    "--policy",
                    POLICY,
                    "--candidate-actions",
                    actions_path,
                    "--data-contract",
                    DATA_CONTRACT,
                    "--output",
                    output_path,
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            written = read_json(output_path)
            self.assertFalse(written["valid"])
            self.assertIn(
                "estimation_policy_rejects_bad_controls",
                written["summary"]["blocking_checks"],
            )


if __name__ == "__main__":
    unittest.main()
