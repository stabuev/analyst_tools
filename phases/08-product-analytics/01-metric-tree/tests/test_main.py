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
ARTIFACT = ROOT / "outputs" / "metric_tree_validator.py"
TREE = ROOT / "outputs" / "metric_tree.json"
SPECS = ROOT / "outputs" / "metric_specs.json"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("metric_tree_validator", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def load_examples() -> tuple[dict, list[dict]]:
    tree = json.loads(TREE.read_text(encoding="utf-8"))
    specs = VALIDATOR.normalize_specs(json.loads(SPECS.read_text(encoding="utf-8")))
    return tree, specs


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class MetricTreeValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tree, self.specs = load_examples()

    def test_valid_metric_tree_has_outcome_inputs_and_guardrails(self) -> None:
        report = VALIDATOR.validate_tree(self.tree, self.specs)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["roles"], {"outcome": 1, "input": 2, "guardrail": 2})
        self.assertEqual(report["summary"]["metrics"], 5)

    def test_duplicate_metric_id_is_rejected(self) -> None:
        tree = copy.deepcopy(self.tree)
        tree["nodes"][1]["metric_id"] = tree["nodes"][0]["metric_id"]
        report = VALIDATOR.validate_tree(tree, self.specs)
        duplicate_check = check(report, "metric_ids_unique")
        self.assertFalse(duplicate_check["valid"])
        self.assertEqual(duplicate_check["sample"], ["activation_rate_7d"])

    def test_tree_must_have_guardrail_role(self) -> None:
        tree = copy.deepcopy(self.tree)
        for node in tree["nodes"]:
            if node["role"] == "guardrail":
                node["role"] = "input"
        report = VALIDATOR.validate_tree(tree, self.specs)
        role_check = check(report, "metric_roles_present")
        self.assertFalse(role_check["valid"])
        self.assertIn("guardrail", role_check["sample"])

    def test_unknown_edge_target_is_rejected(self) -> None:
        tree = copy.deepcopy(self.tree)
        tree["edges"].append({"from": "activation_rate_7d", "to": "missing_metric"})
        report = VALIDATOR.validate_tree(tree, self.specs)
        edge_check = check(report, "metric_edges_resolve")
        self.assertFalse(edge_check["valid"])
        self.assertEqual(edge_check["sample"][0]["to"], "missing_metric")

    def test_metric_spec_requires_explicit_denominator(self) -> None:
        specs = copy.deepcopy(self.specs)
        specs[0]["denominator"] = ""
        report = VALIDATOR.validate_tree(self.tree, specs)
        denominator_check = check(report, "metric_denominator_defined")
        self.assertFalse(denominator_check["valid"])
        self.assertEqual(denominator_check["sample"], ["activation_rate_7d"])

    def test_guardrail_requires_risk_direction(self) -> None:
        specs = copy.deepcopy(self.specs)
        for spec in specs:
            if spec["metric_id"] == "support_ticket_rate_7d":
                spec["expected_direction"] = "up"
        report = VALIDATOR.validate_tree(self.tree, specs)
        direction_check = check(report, "metric_direction_declared")
        self.assertFalse(direction_check["valid"])
        self.assertEqual(direction_check["sample"][0]["metric_id"], "support_ticket_rate_7d")

    def test_sources_and_validation_checks_are_mandatory(self) -> None:
        specs = copy.deepcopy(self.specs)
        specs[0]["source_tables"] = []
        specs[1]["validation_checks"] = []
        report = VALIDATOR.validate_tree(self.tree, specs)
        self.assertFalse(check(report, "metric_sources_declared")["valid"])
        self.assertFalse(check(report, "metric_validation_checks")["valid"])

    def test_metric_sources_exist_in_phase_data_contract(self) -> None:
        contract = json.loads(DATA_CONTRACT.read_text(encoding="utf-8"))
        tables = set(contract["tables"])
        for spec in self.specs:
            with self.subTest(metric_id=spec["metric_id"]):
                self.assertLessEqual(set(spec["source_tables"]), tables)

    def test_cli_writes_report_and_returns_nonzero_for_invalid_specs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid_specs = copy.deepcopy(self.specs)
            invalid_specs[0]["denominator"] = ""
            specs_path = root / "metric_specs.json"
            output_path = root / "report.json"
            specs_path.write_text(
                json.dumps({"metrics": invalid_specs}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--tree",
                    TREE,
                    "--specs",
                    specs_path,
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
