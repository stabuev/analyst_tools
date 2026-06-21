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
ARTIFACT = ROOT / "outputs" / "experiment_protocol_validator.py"
PROTOCOL = ROOT / "outputs" / "experiment_protocol.json"
SPECS = ROOT / "outputs" / "metric_specs.json"
DATA_CONTRACT = PHASE_ROOT / "data" / "contract.json"
CODE = ROOT / "code" / "main.py"

MODULE_SPEC = importlib.util.spec_from_file_location("experiment_protocol_validator", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
VALIDATOR = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(VALIDATOR)


def load_examples() -> tuple[dict, list[dict], dict]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    specs = VALIDATOR.normalize_metric_specs(json.loads(SPECS.read_text(encoding="utf-8")))
    data_contract = json.loads(DATA_CONTRACT.read_text(encoding="utf-8"))
    return protocol, specs, data_contract


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class ExperimentProtocolValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol, self.specs, self.data_contract = load_examples()

    def validate(self, protocol: dict | None = None, specs: list[dict] | None = None) -> dict:
        return VALIDATOR.validate_protocol(
            self.protocol if protocol is None else protocol,
            self.specs if specs is None else specs,
            self.data_contract,
        )

    def test_valid_protocol_is_ready_for_preregistration(self) -> None:
        report = self.validate()
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["primary_metric"], "activation_rate_7d")
        self.assertEqual(report["summary"]["guardrail_metric_count"], 3)
        self.assertEqual(report["summary"]["allowed_decisions"], ["launch", "hold", "rollback", "iterate", "inconclusive"])

    def test_code_example_prints_metric_roles_and_protocol_status(self) -> None:
        result = subprocess.run(
            [sys.executable, CODE],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["protocol_valid"])
        self.assertEqual(payload["primary_metric"], "activation_rate_7d")
        self.assertEqual(payload["manual_metric_roles"]["primary"], ["activation_rate_7d"])
        self.assertEqual(payload["manual_missing_metric_windows"], [])
        self.assertEqual(payload["blocking_checks"], [])

    def test_duplicate_variant_id_is_rejected(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["variants"][1]["variant_id"] = "control"
        protocol["traffic_allocation"] = {"control": 1.0}
        report = self.validate(protocol=protocol)
        self.assertFalse(report["valid"])
        variant_check = check(report, "variants_and_allocation")
        self.assertFalse(variant_check["valid"])
        self.assertIn("duplicate variant_id", {item.get("reason") for item in variant_check["sample"]})

    def test_traffic_allocation_must_sum_to_one(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["traffic_allocation"]["treatment"] = 0.4
        report = self.validate(protocol=protocol)
        allocation_check = check(report, "variants_and_allocation")
        self.assertFalse(allocation_check["valid"])
        self.assertIn("allocation must sum to 1.0", {item.get("reason") for item in allocation_check["sample"]})

    def test_primary_metric_must_resolve_to_primary_spec(self) -> None:
        specs = copy.deepcopy(self.specs)
        specs[0]["role"] = "secondary"
        report = self.validate(specs=specs)
        self.assertFalse(report["valid"])
        metric_check = check(report, "protocol_metrics_resolve")
        self.assertFalse(metric_check["valid"])
        self.assertEqual(metric_check["sample"][0]["metric_id"], "activation_rate_7d")

    def test_guardrail_requires_risk_direction(self) -> None:
        specs = copy.deepcopy(self.specs)
        for spec in specs:
            if spec["metric_id"] == "support_ticket_rate_7d":
                spec["expected_direction"] = "up"
        report = self.validate(specs=specs)
        direction_check = check(report, "guardrail_risk_directions")
        self.assertFalse(direction_check["valid"])
        self.assertEqual(direction_check["sample"][0]["metric_id"], "support_ticket_rate_7d")

    def test_every_declared_metric_needs_exposure_based_window(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        del protocol["metric_windows"]["activation_rate_7d"]
        report = self.validate(protocol=protocol)
        window_check = check(report, "metric_windows_declared")
        self.assertFalse(window_check["valid"])
        self.assertEqual(window_check["sample"][0]["metric_id"], "activation_rate_7d")

    def test_metric_source_tables_must_exist_in_phase_contract(self) -> None:
        specs = copy.deepcopy(self.specs)
        specs[0]["source_tables"].append("missing_table")
        report = self.validate(specs=specs)
        source_check = check(report, "metric_sources_exist")
        self.assertFalse(source_check["valid"])
        self.assertEqual(source_check["sample"][0]["table"], "missing_table")

    def test_timeline_blocks_short_runtime_and_bad_freeze(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["planned_end_at"] = "2026-06-12T00:00:00+03:00"
        protocol["metric_freeze_at"] = "2026-06-11T00:00:00+03:00"
        report = self.validate(protocol=protocol)
        timeline_check = check(report, "experiment_timeline")
        self.assertFalse(timeline_check["valid"])
        reasons = {item["reason"] for item in timeline_check["sample"]}
        self.assertIn("planned runtime is shorter than minimum_runtime_days", reasons)
        self.assertIn("metric_freeze_at must be after planned_end_at", reasons)

    def test_mde_must_belong_to_primary_metric_and_be_positive(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["minimum_detectable_effect"]["metric_id"] = "refund_rate_7d"
        protocol["minimum_detectable_effect"]["absolute"] = 0
        report = self.validate(protocol=protocol)
        design_check = check(report, "statistical_design_parameters")
        self.assertFalse(design_check["valid"])
        fields = {item["field"] for item in design_check["sample"]}
        self.assertIn("minimum_detectable_effect.metric_id", fields)
        self.assertIn("minimum_detectable_effect.absolute", fields)

    def test_cuped_covariates_must_be_pre_treatment(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["pre_experiment_covariates"][0]["timing"] = "post_treatment"
        report = self.validate(protocol=protocol)
        covariate_check = check(report, "pre_experiment_covariates_are_pre_treatment")
        self.assertFalse(covariate_check["valid"])
        self.assertEqual(covariate_check["sample"][0]["name"], "sessions_7d_pre")

    def test_launch_decision_requires_primary_and_all_guardrails(self) -> None:
        protocol = copy.deepcopy(self.protocol)
        protocol["decision_rule"]["launch"]["requires_all_guardrails_not_breached"] = False
        protocol["rollback_rule"]["guardrails"] = ["support_ticket_rate_7d"]
        report = self.validate(protocol=protocol)
        decision_check = check(report, "decision_rule_uses_primary_and_guardrails")
        self.assertFalse(decision_check["valid"])
        fields = {item["field"] for item in decision_check["sample"]}
        self.assertIn("launch.requires_all_guardrails_not_breached", fields)
        self.assertIn("rollback_rule.guardrails", fields)

    def test_cli_writes_report_and_returns_nonzero_for_invalid_protocol(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid_protocol = copy.deepcopy(self.protocol)
            invalid_protocol["traffic_allocation"]["treatment"] = 0.4
            protocol_path = root / "protocol.json"
            output_path = root / "report.json"
            protocol_path.write_text(json.dumps(invalid_protocol, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--protocol",
                    protocol_path,
                    "--specs",
                    SPECS,
                    "--data-contract",
                    DATA_CONTRACT,
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
