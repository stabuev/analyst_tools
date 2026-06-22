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
ARTIFACT = ROOT / "outputs" / "incremental_model_auditor.py"
PROJECT = ROOT / "outputs" / "incremental_project"
PLAYBOOK = ROOT / "outputs" / "backfill_full_refresh_playbook.md"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("incremental_model_auditor", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


def check(report: dict[str, Any], check_id: str) -> dict[str, Any]:
    return next(item for item in report["checks"] if item["id"] == check_id)


def read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def model_doc(properties: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in properties["models"] if item["name"] == name)


class IncrementalModelAuditorTest(unittest.TestCase):
    def copy_project(self, tmp: str) -> Path:
        base = Path(tmp)
        destination = base / "project"
        shutil.copytree(PROJECT, destination)
        shutil.copy(PLAYBOOK, base / PLAYBOOK.name)
        return destination

    def test_valid_project_declares_incremental_contract(self) -> None:
        report = AUDITOR.validate_project(PROJECT, DATA_CONTRACT, run_dbt=False)
        self.assertTrue(report["valid"])
        contract = report["summary"]["incremental_contract"]
        self.assertEqual(contract["unique_key"], "revenue_date")
        self.assertEqual(contract["late_arrival_window_days"], 2)
        self.assertEqual(contract["schema_change_policy"], "fail")
        self.assertTrue(check(report, "incremental_model_sql_declares_contract")["valid"])
        self.assertTrue(check(report, "unique_key_has_data_tests")["valid"])

    def test_live_incremental_run_catches_late_arriving_order_without_duplicates(self) -> None:
        report = AUDITOR.validate_project(PROJECT, DATA_CONTRACT, run_dbt=True)
        self.assertTrue(report["valid"])
        self.assertEqual(
            report["summary"]["initial_fct_output"],
            {
                "row_count": 3,
                "paid_revenue_rub": "2000.00",
                "may_03_paid_revenue_rub": "800.00",
                "duplicate_date_rows": 0,
            },
        )
        self.assertEqual(
            report["summary"]["incremental_fct_output"],
            {
                "row_count": 4,
                "paid_revenue_rub": "4412.50",
                "may_03_paid_revenue_rub": "900.00",
                "duplicate_date_rows": 0,
            },
        )
        self.assertTrue(check(report, "documented_full_refresh_succeeds")["valid"])

    def test_unique_key_config_is_required_in_model_sql(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            model_path = project / "models" / "marts" / "fct_order_revenue_daily.sql"
            model_path.write_text(
                model_path.read_text(encoding="utf-8").replace("        unique_key='revenue_date',\n", ""),
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "incremental_model_sql_declares_contract")["valid"])

    def test_is_incremental_guard_and_this_relation_are_required(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            model_path = project / "models" / "marts" / "fct_order_revenue_daily.sql"
            text = model_path.read_text(encoding="utf-8")
            text = text.replace("{% if is_incremental() %}", "{% if false %}")
            text = text.replace("{{ this }}", "analytics.fct_order_revenue_daily")
            model_path.write_text(text, encoding="utf-8")
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            sql_check = check(report, "incremental_model_sql_declares_contract")
            self.assertFalse(sql_check["valid"])
            missing = {item["fragment"] for item in sql_check["sample"]}
            self.assertIn("is_incremental_guard", missing)
            self.assertIn("target_relation", missing)

    def test_late_arrival_window_cannot_be_shrunk_silently(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            model_path = project / "models" / "marts" / "fct_order_revenue_daily.sql"
            model_path.write_text(
                model_path.read_text(encoding="utf-8").replace("interval '2 days'", "interval '0 days'"),
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "incremental_model_sql_declares_contract")["valid"])

    def test_incremental_contract_meta_is_required(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            properties_path = project / "models" / "properties.yml"
            properties = read_yaml(properties_path)
            model_doc(properties, "fct_order_revenue_daily")["meta"].pop("incremental_contract")
            write_yaml(properties_path, properties)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "incremental_contract_meta_is_complete")["valid"])

    def test_unique_key_must_have_unique_and_not_null_tests(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            properties_path = project / "models" / "properties.yml"
            properties = read_yaml(properties_path)
            model = model_doc(properties, "fct_order_revenue_daily")
            revenue_date = next(item for item in model["columns"] if item["name"] == "revenue_date")
            revenue_date["data_tests"] = ["not_null"]
            write_yaml(properties_path, properties)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "unique_key_has_data_tests")["valid"])

    def test_playbook_must_name_full_refresh_and_schema_change_policy(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            playbook = Path(directory) / PLAYBOOK.name
            playbook.write_text("Run the model carefully.\n", encoding="utf-8")
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "backfill_full_refresh_playbook_exists")["valid"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            output = Path(directory) / "report.json"
            model_path = project / "models" / "marts" / "fct_order_revenue_daily.sql"
            model_path.write_text(
                model_path.read_text(encoding="utf-8").replace("materialized='incremental'", "materialized='table'"),
                encoding="utf-8",
            )
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
            self.assertFalse(check(report, "incremental_model_sql_declares_contract")["valid"])


if __name__ == "__main__":
    unittest.main()
