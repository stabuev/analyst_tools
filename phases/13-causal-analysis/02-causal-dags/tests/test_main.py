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
PREVIOUS_LESSON = ROOT.parent / "01-causal-question-and-estimand"
DAG = ROOT / "outputs" / "causal_dag.json"
IDENTIFICATION_MAP = ROOT / "outputs" / "identification_map.json"
QUESTION = PREVIOUS_LESSON / "outputs" / "causal_question.json"
ESTIMAND = PREVIOUS_LESSON / "outputs" / "estimand.json"
ARTIFACT = ROOT / "outputs" / "causal_dag_validator.py"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("causal_dag_validator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
VALIDATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(VALIDATOR)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def measured_variables(identification_map: dict) -> set[str]:
    return set(
        next(
            item
            for item in identification_map["adjustment_sets"]
            if item["set_id"] == "measured_baseline_core"
        )["variables"]
    )


class CausalDagValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dag = read_json(DAG)
        self.identification = read_json(IDENTIFICATION_MAP)
        self.question = read_json(QUESTION)
        self.estimand = read_json(ESTIMAND)

    def validate(self, *, dag: dict | None = None, identification: dict | None = None) -> dict:
        return VALIDATOR.validate_specs(
            self.dag if dag is None else dag,
            self.identification if identification is None else identification,
            self.question,
            self.estimand,
        )

    def test_valid_dag_is_auditable_but_not_yet_identified(self) -> None:
        report = self.validate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["nodes"], 19)
        self.assertEqual(report["summary"]["edges"], 44)
        self.assertEqual(
            report["summary"]["identification_status"],
            "not_identified_from_observed_variables",
        )
        self.assertGreater(report["summary"]["active_backdoor_paths_without_adjustment"], 1)
        self.assertEqual(report["summary"]["active_backdoor_paths_after_measured_adjustment"], 1)
        warning = check(report, "unmeasured_confounding_blocks_backdoor_identification")
        self.assertEqual(warning["severity"], "warning")
        self.assertFalse(warning["valid"])

    def test_code_example_compares_association_intervention_and_collider(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["audit_valid"])
        self.assertEqual(payload["blocking_checks"], [])
        self.assertEqual(
            payload["warnings"],
            ["unmeasured_confounding_blocks_backdoor_identification"],
        )
        self.assertEqual(payload["active_backdoor_paths_after_measured_adjustment"], 1)
        self.assertIn("latent_motivation", payload["remaining_backdoor_example"])
        self.assertEqual(payload["intervention_operation"], "do(assisted_within_24h)")
        self.assertFalse(payload["collider_path_active_without_conditioning"])
        self.assertTrue(payload["collider_path_active_after_conditioning"])

    def test_cycle_is_rejected(self) -> None:
        dag = copy.deepcopy(self.dag)
        dag["edges"].append(
            {
                "source": "activation_14d",
                "target": "friction_score",
                "reason": "invalid reverse causal edge for test",
            }
        )
        report = self.validate(dag=dag)
        self.assertFalse(report["valid"])
        self.assertFalse(check(report, "graph_is_acyclic")["valid"])

    def test_temporal_order_violation_is_rejected(self) -> None:
        dag = copy.deepcopy(self.dag)
        for node in dag["nodes"]:
            if node["id"] == "friction_score":
                node["timing"] = "outcome"
        report = self.validate(dag=dag)
        timing = check(report, "temporal_order_respected")
        self.assertFalse(report["valid"])
        self.assertFalse(timing["valid"])
        self.assertEqual(timing["sample"][0]["reason"], "effect cannot precede its cause")

    def test_unknown_edge_endpoint_is_rejected(self) -> None:
        dag = copy.deepcopy(self.dag)
        dag["edges"].append(
            {
                "source": "friction_score",
                "target": "ghost_outcome",
                "reason": "invalid unknown target for test",
            }
        )
        report = self.validate(dag=dag)
        self.assertFalse(report["valid"])
        self.assertFalse(check(report, "edge_endpoints_known")["valid"])

    def test_question_estimand_and_graph_ids_must_align(self) -> None:
        identification = copy.deepcopy(self.identification)
        identification["estimand_id"] = "another_estimand"
        report = self.validate(identification=identification)
        self.assertFalse(report["valid"])
        self.assertFalse(check(report, "question_estimand_graph_ids_align")["valid"])

    def test_friction_backdoor_path_is_blocked_by_conditioning_on_friction(self) -> None:
        path = ["assisted_within_24h", "friction_score", "activation_14d"]
        self.assertTrue(VALIDATOR.is_path_active(self.dag, path, set()))
        self.assertFalse(VALIDATOR.is_path_active(self.dag, path, {"friction_score"}))

    def test_measured_adjustment_leaves_latent_backdoor_open(self) -> None:
        remaining = VALIDATOR.active_backdoor_paths(
            self.dag,
            "assisted_within_24h",
            "activation_14d",
            measured_variables(self.identification),
        )
        self.assertEqual(
            remaining,
            [["assisted_within_24h", "latent_motivation", "activation_14d"]],
        )

    def test_collider_path_is_closed_then_opened_by_conditioning(self) -> None:
        path = [
            "assisted_within_24h",
            "opened_support_chat_after_offer",
            "friction_score",
            "activation_14d",
        ]
        self.assertFalse(VALIDATOR.is_path_active(self.dag, path, set()))
        self.assertTrue(
            VALIDATOR.is_path_active(
                self.dag,
                path,
                {"opened_support_chat_after_offer"},
            )
        )

    def test_total_effect_path_stays_open_without_mediator_adjustment(self) -> None:
        path = ["assisted_within_24h", "onboarding_completed_48h", "activation_14d"]
        self.assertTrue(
            VALIDATOR.is_path_active(self.dag, path, measured_variables(self.identification))
        )
        self.assertFalse(
            VALIDATOR.is_path_active(
                self.dag,
                path,
                measured_variables(self.identification) | {"onboarding_completed_48h"},
            )
        )

    def test_unobserved_variable_cannot_be_silently_used_for_adjustment(self) -> None:
        identification = copy.deepcopy(self.identification)
        oracle = next(
            item
            for item in identification["adjustment_sets"]
            if item["set_id"] == "oracle_unobserved_adjustment"
        )
        oracle["status"] = "sufficient_for_backdoor_identification"
        report = self.validate(identification=identification)
        self.assertFalse(report["valid"])
        adjustment = check(report, "adjustment_sets_are_graph_consistent")
        self.assertFalse(adjustment["valid"])
        self.assertEqual(
            adjustment["sample"][0]["reason"],
            "unobserved variables cannot be used as observed adjustment",
        )

    def test_mediator_adjustment_cannot_be_labeled_sufficient(self) -> None:
        identification = copy.deepcopy(self.identification)
        bad = next(
            item
            for item in identification["adjustment_sets"]
            if item["set_id"] == "bad_mediator_adjustment"
        )
        bad["status"] = "sufficient_for_backdoor_identification"
        report = self.validate(identification=identification)
        self.assertFalse(report["valid"])
        adjustment = check(report, "adjustment_sets_are_graph_consistent")
        self.assertFalse(adjustment["valid"])
        self.assertIn("forbidden controls", adjustment["sample"][0]["reason"])

    def test_identified_status_requires_supported_identification_not_an_estimator(self) -> None:
        identification = copy.deepcopy(self.identification)
        identification["identification_status"] = "identified"
        report = self.validate(identification=identification)
        self.assertFalse(report["valid"])
        self.assertFalse(check(report, "identification_status_not_supported")["valid"])

    def test_estimator_before_identification_is_rejected(self) -> None:
        identification = copy.deepcopy(self.identification)
        identification["estimator"] = "logistic_regression"
        report = self.validate(identification=identification)
        self.assertFalse(report["valid"])
        estimator = check(report, "estimator_selected_before_identification")
        self.assertFalse(estimator["valid"])
        self.assertEqual(estimator["sample"]["estimator"], "logistic_regression")

    def test_intervention_summary_removes_only_incoming_treatment_edges(self) -> None:
        summary = VALIDATOR.intervention_graph_summary(self.dag, "assisted_within_24h")
        removed = {(edge["source"], edge["target"]) for edge in summary["removed_incoming_edges"]}
        kept = {(edge["source"], edge["target"]) for edge in summary["kept_outgoing_edges"]}
        self.assertIn(("latent_motivation", "assisted_within_24h"), removed)
        self.assertIn(("friction_score", "assisted_within_24h"), removed)
        self.assertIn(("assisted_within_24h", "activation_14d"), kept)
        self.assertNotIn(("assisted_within_24h", "activation_14d"), removed)

    def test_d_separation_claim_mismatch_is_rejected(self) -> None:
        identification = copy.deepcopy(self.identification)
        identification["d_separation_checks"][0]["expected_d_separated"] = True
        report = self.validate(identification=identification)
        self.assertFalse(report["valid"])
        self.assertFalse(check(report, "d_separation_claims_match_graph")["valid"])

    def test_cli_writes_audit_and_returns_nonzero_for_invalid_graph(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid_dag = copy.deepcopy(self.dag)
            invalid_dag["edges"].append(
                {
                    "source": "activation_14d",
                    "target": "friction_score",
                    "reason": "invalid reverse causal edge for CLI test",
                }
            )
            dag_path = root / "dag.json"
            output_path = root / "audit.json"
            write_json(dag_path, invalid_dag)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--dag",
                    dag_path,
                    "--identification-map",
                    IDENTIFICATION_MAP,
                    "--question",
                    QUESTION,
                    "--estimand",
                    ESTIMAND,
                    "--output",
                    output_path,
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            audit = read_json(output_path)
            self.assertFalse(audit["valid"])
            self.assertFalse(check(audit, "graph_is_acyclic")["valid"])


if __name__ == "__main__":
    unittest.main()
