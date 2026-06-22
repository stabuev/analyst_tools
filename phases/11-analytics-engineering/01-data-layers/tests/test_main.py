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
ARTIFACT = ROOT / "outputs" / "layer_contract_auditor.py"
CONTRACT = ROOT / "outputs" / "layer_contract.json"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
BRIEF = ROOT / "outputs" / "mart_design_brief.md"
SPEC = importlib.util.spec_from_file_location("layer_contract_auditor", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


def load_examples() -> tuple[dict, dict, str]:
    return (
        json.loads(CONTRACT.read_text(encoding="utf-8")),
        json.loads(DATA_CONTRACT.read_text(encoding="utf-8")),
        BRIEF.read_text(encoding="utf-8"),
    )


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


class LayerContractAuditorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract, self.data_contract, self.brief = load_examples()

    def test_valid_contract_declares_layers_and_mart(self) -> None:
        report = AUDITOR.validate_contract(self.contract, self.data_contract, self.brief)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["layers"]["raw"], 3)
        self.assertEqual(report["summary"]["layers"]["staging"], 3)
        self.assertEqual(report["summary"]["layers"]["intermediate"], 1)
        self.assertEqual(report["summary"]["layers"]["mart"], 1)
        self.assertEqual(report["summary"]["mart_models"], ["mart_customer_revenue_health"])

    def test_duplicate_model_id_is_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["models"][1]["model_id"] = contract["models"][0]["model_id"]
        report = AUDITOR.validate_contract(contract, self.data_contract, self.brief)
        duplicate_check = check(report, "model_ids_unique")
        self.assertFalse(duplicate_check["valid"])
        self.assertEqual(duplicate_check["sample"], ["raw_users"])

    def test_required_model_fields_are_checked(self) -> None:
        contract = copy.deepcopy(self.contract)
        del contract["models"][3]["grain"]
        report = AUDITOR.validate_contract(contract, self.data_contract, self.brief)
        field_check = check(report, "model_required_fields")
        self.assertFalse(field_check["valid"])
        self.assertEqual(field_check["sample"][0]["model_id"], "stg_users")
        self.assertIn("grain", field_check["sample"][0]["missing"])

    def test_source_tables_must_exist_in_data_contract(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["models"][3]["source_tables"] = ["raw_missing_users"]
        report = AUDITOR.validate_contract(contract, self.data_contract, self.brief)
        source_check = check(report, "source_tables_exist")
        self.assertFalse(source_check["valid"])
        self.assertEqual(source_check["sample"][0]["source_table"], "raw_missing_users")

    def test_raw_primary_key_must_match_data_contract(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["models"][0]["primary_key"] = ["user_id", "updated_at"]
        report = AUDITOR.validate_contract(contract, self.data_contract, self.brief)
        key_check = check(report, "raw_primary_keys_match_data_contract")
        self.assertFalse(key_check["valid"])
        self.assertEqual(key_check["sample"][0]["data_contract"], ["user_id"])

    def test_mart_cannot_skip_to_raw_sources(self) -> None:
        contract = copy.deepcopy(self.contract)
        mart = contract["models"][-1]
        mart["upstream_models"] = ["raw_orders"]
        report = AUDITOR.validate_contract(contract, self.data_contract, self.brief)
        self.assertTrue(check(report, "layer_order_is_forward")["valid"])
        self.assertFalse(check(report, "mart_does_not_skip_layers")["valid"])

    def test_non_raw_models_must_declare_upstream_models(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["models"][4]["upstream_models"] = []
        report = AUDITOR.validate_contract(contract, self.data_contract, self.brief)
        upstream_check = check(report, "non_raw_models_have_upstream")
        self.assertFalse(upstream_check["valid"])
        self.assertEqual(upstream_check["sample"], ["stg_orders"])

    def test_primary_key_tests_are_required(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["models"][6]["required_tests"] = ["amount_reconciles_to_items"]
        report = AUDITOR.validate_contract(contract, self.data_contract, self.brief)
        pk_check = check(report, "primary_key_tests_required")
        self.assertFalse(pk_check["valid"])
        self.assertEqual(pk_check["sample"][0]["model_id"], "int_order_line_revenue")
        self.assertIn("not_null_primary_key", pk_check["sample"][0]["missing_tests"])

    def test_mart_requires_docs_exposure_publication_and_reconciliation(self) -> None:
        contract = copy.deepcopy(self.contract)
        mart = contract["models"][-1]
        mart["documentation_required"] = False
        mart["downstream_exposures"] = []
        mart["reconciliation_rules"] = []
        report = AUDITOR.validate_contract(contract, self.data_contract, self.brief)
        mart_check = check(report, "mart_publication_contract")
        self.assertFalse(mart_check["valid"])
        self.assertEqual(mart_check["sample"][0]["model_id"], "mart_customer_revenue_health")
        self.assertIn("documentation_required", mart_check["sample"][0]["missing"])
        self.assertIn("downstream_exposures", mart_check["sample"][0]["missing"])

    def test_design_brief_must_name_mart_and_required_sections(self) -> None:
        brief = "# Wrong brief\n\nNo mart id here."
        report = AUDITOR.validate_contract(self.contract, self.data_contract, brief)
        self.assertFalse(check(report, "brief_required_headings")["valid"])
        self.assertFalse(check(report, "brief_mentions_mart_models")["valid"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_contract(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid_contract = copy.deepcopy(self.contract)
            invalid_contract["models"][-1]["downstream_exposures"] = []
            contract_path = root / "layer_contract.json"
            output_path = root / "audit.json"
            contract_path.write_text(
                json.dumps(invalid_contract, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--contract",
                    contract_path,
                    "--data-contract",
                    DATA_CONTRACT,
                    "--brief",
                    BRIEF,
                    "--output",
                    output_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            stdout_report = json.loads(result.stdout)
            self.assertFalse(stdout_report["valid"])
            self.assertEqual(stdout_report, json.loads(output_path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
