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
INVENTORY = ROOT / "outputs" / "confounder_inventory.json"
ADJUSTMENT_SPEC = ROOT / "outputs" / "adjustment_set_spec.json"
DATA_CONTRACT = PHASE_ROOT / "data" / "contract.json"
ARTIFACT = ROOT / "outputs" / "backdoor_adjustment_auditor.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("backdoor_adjustment_auditor", ARTIFACT)
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


def candidate(report: dict, set_id: str) -> dict:
    return next(item for item in report["candidate_set_audits"] if item["set_id"] == set_id)


def candidate_spec(spec: dict, set_id: str) -> dict:
    return next(item for item in spec["candidate_adjustment_sets"] if item["set_id"] == set_id)


class BackdoorAdjustmentAuditorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dag = read_json(DAG)
        self.inventory = read_json(INVENTORY)
        self.adjustment_spec = read_json(ADJUSTMENT_SPEC)
        self.data_contract = read_json(DATA_CONTRACT)

    def validate(
        self,
        *,
        dag: dict | None = None,
        inventory: dict | None = None,
        adjustment_spec: dict | None = None,
        data_contract: dict | None = None,
    ) -> dict:
        return AUDITOR.validate_specs(
            self.dag if dag is None else dag,
            self.inventory if inventory is None else inventory,
            self.adjustment_spec if adjustment_spec is None else adjustment_spec,
            self.data_contract if data_contract is None else data_contract,
        )

    def test_valid_audit_closes_measured_paths_but_not_unmeasured_confounding(self) -> None:
        report = self.validate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["active_backdoor_paths_without_adjustment"], 48)
        self.assertEqual(report["summary"]["measured_confounders"], 11)
        self.assertEqual(report["summary"]["unmeasured_confounders"], 1)
        self.assertEqual(
            report["summary"]["primary_recommendation"], "measured_baseline_backdoor_set"
        )
        self.assertEqual(report["summary"]["primary_open_measured_paths"], 0)
        self.assertEqual(report["summary"]["primary_open_unmeasured_paths"], 1)
        self.assertEqual(
            report["summary"]["identification_status"],
            "not_identified_due_to_unmeasured_confounding",
        )

    def test_code_example_prints_transferable_summary(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["blocking_checks"], [])
        self.assertEqual(payload["recommended_open_measured_paths"], 0)
        self.assertEqual(payload["recommended_open_unmeasured_paths"], 1)
        self.assertIn("latent_motivation", payload["remaining_unmeasured_path"])
        self.assertIn("onboarding_completed_48h", payload["forbidden_controls"])

    def test_friction_score_participates_in_many_open_backdoor_paths(self) -> None:
        report = self.validate()
        participation = report["summary"]["backdoor_participation"]
        self.assertGreaterEqual(participation["friction_score"]["path_count"], 30)
        self.assertEqual(participation["friction_score"]["timing"], "baseline")
        self.assertEqual(participation["latent_motivation"]["observed"], False)

    def test_missing_active_confounder_breaks_inventory(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        inventory["confounders"] = [
            item for item in inventory["confounders"] if item["variable"] != "friction_score"
        ]
        report = self.validate(inventory=inventory)
        self.assertFalse(report["valid"])
        inventory_check = check(report, "active_backdoor_confounders_are_in_inventory")
        self.assertFalse(inventory_check["valid"])
        self.assertIn("friction_score", inventory_check["sample"])

    def test_unmeasured_confounder_cannot_be_labeled_measured(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        latent = next(
            item for item in inventory["confounders"] if item["variable"] == "latent_motivation"
        )
        latent["measurement_status"] = "measured"
        report = self.validate(inventory=inventory)
        measurement = check(report, "confounder_measurement_status_is_consistent")
        self.assertFalse(report["valid"])
        self.assertFalse(measurement["valid"])
        self.assertEqual(measurement["sample"][0]["reason"], "measured variable is not observed")

    def test_measured_confounder_source_must_exist_in_data_contract(self) -> None:
        dag = copy.deepcopy(self.dag)
        node = next(item for item in dag["nodes"] if item["id"] == "friction_score")
        node["source_fields"].append({"table": "pre_treatment_behavior", "field": "unknown_score"})
        report = self.validate(dag=dag)
        measurement = check(report, "confounder_measurement_status_is_consistent")
        self.assertFalse(report["valid"])
        self.assertFalse(measurement["valid"])
        self.assertEqual(
            measurement["sample"][0]["reason"], "source field is absent from data contract"
        )

    def test_primary_recommendation_must_be_unique(self) -> None:
        spec = copy.deepcopy(self.adjustment_spec)
        candidate_spec(spec, "friction_capacity_only")["is_primary_recommendation"] = True
        report = self.validate(adjustment_spec=spec)
        primary = check(report, "exactly_one_primary_recommendation")
        self.assertFalse(report["valid"])
        self.assertFalse(primary["valid"])
        self.assertEqual(
            set(primary["sample"]),
            {"friction_capacity_only", "measured_baseline_backdoor_set"},
        )

    def test_primary_recommendation_must_block_all_measured_backdoor_paths(self) -> None:
        spec = copy.deepcopy(self.adjustment_spec)
        primary = candidate_spec(spec, "measured_baseline_backdoor_set")
        primary["variables"] = ["friction_score", "specialist_capacity"]
        primary["declared_status"] = "recommended_measured_adjustment_with_unmeasured_limitation"
        report = self.validate(adjustment_spec=spec)
        primary_check = check(
            report,
            "primary_recommendation_is_observed_baseline_and_blocks_measured_paths",
        )
        self.assertFalse(report["valid"])
        self.assertFalse(primary_check["valid"])
        reasons = {item["reason"] for item in primary_check["sample"]}
        self.assertIn("measured_backdoors_still_open", reasons)

    def test_candidate_declared_status_must_match_graph_audit(self) -> None:
        spec = copy.deepcopy(self.adjustment_spec)
        candidate_spec(spec, "none")["declared_status"] = "sufficient_observed_backdoor_adjustment"
        report = self.validate(adjustment_spec=spec)
        status = check(report, "candidate_statuses_match_graph")
        self.assertFalse(report["valid"])
        self.assertFalse(status["valid"])
        self.assertEqual(status["sample"][0]["set_id"], "none")

    def test_oracle_latent_adjustment_is_not_observed_adjustment(self) -> None:
        report = self.validate()
        oracle = candidate(report, "oracle_latent_adjustment")
        self.assertEqual(oracle["calculated_status"], "invalid_contains_unmeasured_variable")
        self.assertEqual(oracle["unobserved_variables"], ["latent_motivation"])
        self.assertEqual(oracle["active_backdoor_paths"], 0)

    def test_mediator_and_selection_sets_are_forbidden_controls(self) -> None:
        report = self.validate()
        mediator = candidate(report, "mediator_leakage_set")
        selection = candidate(report, "complete_case_selection_set")
        self.assertEqual(mediator["calculated_status"], "invalid_forbidden_control")
        self.assertEqual(mediator["forbidden_variables"][0]["role"], "mediator")
        self.assertEqual(selection["forbidden_variables"][0]["role"], "selection")
        self.assertGreater(selection["newly_opened_or_reopened_paths"], 0)

    def test_unknown_candidate_variable_is_rejected(self) -> None:
        spec = copy.deepcopy(self.adjustment_spec)
        primary = candidate_spec(spec, "measured_baseline_backdoor_set")
        primary["variables"].append("ghost_baseline")
        primary["declared_status"] = "invalid_unknown_variable"
        report = self.validate(adjustment_spec=spec)
        primary_report = candidate(report, "measured_baseline_backdoor_set")
        self.assertFalse(report["valid"])
        self.assertEqual(primary_report["unknown_variables"], ["ghost_baseline"])
        self.assertFalse(
            check(
                report,
                "primary_recommendation_is_observed_baseline_and_blocks_measured_paths",
            )["valid"]
        )

    def test_claim_policy_cannot_allow_effect_claim_with_unmeasured_path(self) -> None:
        spec = copy.deepcopy(self.adjustment_spec)
        spec["claim_policy"]["allowed_effect_claim"] = True
        spec["claim_policy"]["identification_status"] = "identified"
        report = self.validate(adjustment_spec=spec)
        claim = check(report, "claim_policy_matches_remaining_unmeasured_confounding")
        self.assertFalse(report["valid"])
        self.assertFalse(claim["valid"])
        fields = {item["field"] for item in claim["sample"]}
        self.assertEqual(fields, {"allowed_effect_claim", "identification_status"})

    def test_forbidden_control_inventory_must_point_to_actual_bad_control(self) -> None:
        inventory = copy.deepcopy(self.inventory)
        inventory["forbidden_controls"].append(
            {"variable": "friction_score", "forbidden_reason": "incorrect test mutation"}
        )
        report = self.validate(inventory=inventory)
        forbidden = check(report, "forbidden_controls_are_real_bad_controls")
        self.assertFalse(report["valid"])
        self.assertFalse(forbidden["valid"])
        self.assertEqual(forbidden["sample"][0]["variable"], "friction_score")

    def test_cli_writes_report_and_returns_nonzero_for_invalid_adjustment_spec(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = copy.deepcopy(self.adjustment_spec)
            candidate_spec(invalid, "none")["declared_status"] = (
                "sufficient_observed_backdoor_adjustment"
            )
            spec_path = root / "adjustment_set_spec.json"
            output_path = root / "audit.json"
            write_json(spec_path, invalid)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--dag",
                    DAG,
                    "--inventory",
                    INVENTORY,
                    "--adjustment-spec",
                    spec_path,
                    "--data-contract",
                    DATA_CONTRACT,
                    "--output",
                    output_path,
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            audit = read_json(output_path)
            self.assertFalse(audit["valid"])
            self.assertFalse(check(audit, "candidate_statuses_match_graph")["valid"])


if __name__ == "__main__":
    unittest.main()
