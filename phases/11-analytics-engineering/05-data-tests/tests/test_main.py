from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dbt_test_reporter.py"
PROJECT = ROOT / "outputs" / "data_test_project"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("dbt_test_reporter", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
REPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORTER)


def check(report: dict[str, Any], check_id: str) -> dict[str, Any]:
    return next(item for item in report["checks"] if item["id"] == check_id)


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def model_spec(properties: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in properties["models"] if item["name"] == name)


def source_table_spec(sources: dict[str, Any], name: str) -> dict[str, Any]:
    source = next(item for item in sources["sources"] if item["name"] == "raw_app")
    return next(item for item in source["tables"] if item["name"] == name)


def remove_data_test(value: Any, test_name: str) -> None:
    if isinstance(value, dict):
        if isinstance(value.get("data_tests"), list):
            value["data_tests"] = [
                item for item in value["data_tests"] if REPORTER.test_name(item) != test_name
            ]
        for nested in value.values():
            remove_data_test(nested, test_name)
    elif isinstance(value, list):
        for nested in value:
            remove_data_test(nested, test_name)


def contract_failure_names(report: dict[str, Any]) -> set[str]:
    return {
        row["name"]
        for row in report["summary"].get("test_results", [])
        if row["classification"] == "contract_gate" and row["status"] != "pass"
    }


class DataTestReporterTest(unittest.TestCase):
    def copy_project(self, tmp: str) -> Path:
        destination = Path(tmp) / "project"
        shutil.copytree(PROJECT, destination)
        return destination

    def copy_data(self, tmp: str) -> Path:
        destination = Path(tmp) / "data"
        shutil.copytree(DATA_CONTRACT.parent / "tiny", destination)
        return destination

    def test_valid_project_declares_generic_and_singular_data_tests(self) -> None:
        report = REPORTER.validate_project(PROJECT, DATA_CONTRACT, run_dbt=False)
        self.assertTrue(report["valid"])
        self.assertEqual(
            report["summary"]["generic_counts"],
            {"accepted_values": 10, "not_null": 28, "relationships": 11, "unique": 15},
        )
        self.assertEqual(
            report["summary"]["singular_sql"],
            [
                "assert_no_many_to_many_revenue_join",
                "assert_paid_revenue_reconciles",
                "warn_customers_without_subscription",
            ],
        )
        self.assertTrue(check(report, "generic_tests_cover_core_assertions")["valid"])
        self.assertTrue(check(report, "warning_diagnostics_are_marked_non_blocking")["valid"])

    def test_legacy_tests_key_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            properties_path = project / "models" / "properties.yml"
            properties = read_yaml(properties_path)
            user_id_column = model_spec(properties, "stg_users")["columns"][0]
            user_id_column["tests"] = ["not_null"]
            write_yaml(properties_path, properties)
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            legacy_check = check(report, "uses_data_tests_key")
            self.assertFalse(legacy_check["valid"])
            self.assertIn("models/properties.yml", legacy_check["sample"])

    def test_missing_generic_test_family_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            for relative in ("models/properties.yml", "models/sources.yml"):
                path = project / relative
                value = read_yaml(path)
                remove_data_test(value, "accepted_values")
                write_yaml(path, value)
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            generic_check = check(report, "generic_tests_cover_core_assertions")
            self.assertFalse(generic_check["valid"])
            self.assertEqual(generic_check["sample"], ["accepted_values"])

    def test_warning_diagnostic_must_be_severity_warn(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            warning_sql = project / "tests" / "warn_customers_without_subscription.sql"
            warning_sql.write_text(
                warning_sql.read_text(encoding="utf-8").replace("{{ config(severity = 'warn') }}\n\n", ""),
                encoding="utf-8",
            )
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            warning_check = check(report, "warning_diagnostics_are_marked_non_blocking")
            self.assertFalse(warning_check["valid"])
            self.assertEqual(warning_check["sample"], ["warn_customers_without_subscription"])

    def test_contract_singular_test_cannot_be_downgraded_to_warning(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            contract_sql = project / "tests" / "assert_paid_revenue_reconciles.sql"
            contract_sql.write_text(
                "{{ config(severity = 'warn') }}\n\n" + contract_sql.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            warning_check = check(report, "warning_diagnostics_are_marked_non_blocking")
            self.assertFalse(warning_check["valid"])
            self.assertEqual(warning_check["sample"], ["assert_paid_revenue_reconciles"])

    def test_source_freshness_config_must_match_data_contract(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            sources_path = project / "models" / "sources.yml"
            sources = read_yaml(sources_path)
            source_table_spec(sources, "orders")["config"]["loaded_at_field"] = "ordered_at"
            write_yaml(sources_path, sources)
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            freshness_check = check(report, "sources_have_freshness_config")
            self.assertFalse(freshness_check["valid"])
            self.assertEqual(freshness_check["sample"][0]["source"], "orders")

    def test_live_dbt_data_tests_pass_contract_gates_and_keep_warning_non_blocking(self) -> None:
        report = REPORTER.validate_project(PROJECT, DATA_CONTRACT, run_dbt=True)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["test_kind_counts"], {"generic": 64, "singular": 3})
        self.assertEqual(report["summary"]["test_classification_counts"], {"contract_gate": 66, "warning_diagnostic": 1})
        self.assertEqual(report["summary"]["test_status_counts"], {"pass": 66, "warn": 1})
        self.assertTrue(check(report, "contract_gates_pass")["valid"])
        self.assertTrue(check(report, "warning_diagnostics_are_non_blocking")["valid"])
        self.assertTrue(check(report, "dbt_test_exit_code_matches_contract_policy")["valid"])

    def test_bad_order_status_breaks_accepted_values_contract_gate(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            data_dir = self.copy_data(directory)
            orders_path = data_dir / "raw_orders.csv"
            orders_path.write_text(
                orders_path.read_text(encoding="utf-8").replace(",paid,RUB,800.00,", ",chargeback,RUB,800.00,"),
                encoding="utf-8",
            )
            report = REPORTER.validate_project(project, DATA_CONTRACT, data_dir=data_dir, run_dbt=True)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "contract_gates_pass")["valid"])
            self.assertTrue(check(report, "dbt_test_exit_code_matches_contract_policy")["valid"])
            self.assertTrue(any(name.startswith("accepted_values_") for name in contract_failure_names(report)))

    def test_orphan_support_ticket_breaks_relationship_contract_gate(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            data_dir = self.copy_data(directory)
            tickets_path = data_dir / "raw_support_tickets.csv"
            tickets_path.write_text(
                tickets_path.read_text(encoding="utf-8").replace("t001,u004,", "t001,u999,"),
                encoding="utf-8",
            )
            report = REPORTER.validate_project(project, DATA_CONTRACT, data_dir=data_dir, run_dbt=True)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "contract_gates_pass")["valid"])
            self.assertTrue(any(name.startswith("relationships_") for name in contract_failure_names(report)))

    def test_paid_revenue_reconciliation_catches_line_item_drift(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            data_dir = self.copy_data(directory)
            items_path = data_dir / "raw_order_items.csv"
            items_path.write_text(
                items_path.read_text(encoding="utf-8").replace("o001,2,p_addon,1,200.00,RUB", "o001,2,p_addon,1,250.00,RUB"),
                encoding="utf-8",
            )
            report = REPORTER.validate_project(project, DATA_CONTRACT, data_dir=data_dir, run_dbt=True)
            self.assertFalse(report["valid"])
            self.assertIn("assert_paid_revenue_reconciles", contract_failure_names(report))

    def test_cli_writes_report_and_returns_nonzero_for_invalid_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            output = Path(directory) / "report.json"
            warning_sql = project / "tests" / "warn_customers_without_subscription.sql"
            warning_sql.write_text("select 1 where false\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--project",
                    project,
                    "--data-contract",
                    DATA_CONTRACT,
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "warning_diagnostics_are_marked_non_blocking")["valid"])


if __name__ == "__main__":
    unittest.main()
