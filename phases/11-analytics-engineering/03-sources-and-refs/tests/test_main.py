from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "source_ref_lineage_auditor.py"
PROJECT = ROOT / "outputs" / "source_ref_project"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("source_ref_lineage_auditor", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


class SourceRefLineageAuditorTest(unittest.TestCase):
    def copy_project(self, tmp: str) -> Path:
        destination = Path(tmp) / "project"
        shutil.copytree(PROJECT, destination)
        return destination

    def test_valid_project_declares_sources_and_ref_graph(self) -> None:
        report = AUDITOR.validate_project(PROJECT, DATA_CONTRACT, run_dbt=False)
        self.assertTrue(report["valid"])
        self.assertEqual(len(report["summary"]["declared_sources"]), 8)
        self.assertTrue(check(report, "sources_match_data_contract")["valid"])
        self.assertTrue(check(report, "downstream_models_use_ref")["valid"])

    def test_missing_raw_source_declaration_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            sources_path = project / "models" / "sources.yml"
            sources = read_yaml(sources_path)
            sources["sources"][0]["name"] = "not_raw_app"
            write_yaml(sources_path, sources)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            source_check = check(report, "raw_source_declared")
            self.assertFalse(source_check["valid"])
            self.assertEqual(source_check["sample"], ["raw_app"])

    def test_sources_must_match_data_contract_identifiers(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            sources_path = project / "models" / "sources.yml"
            sources = read_yaml(sources_path)
            sources["sources"][0]["tables"][0]["identifier"] = "raw_wrong_users"
            sources["sources"][0]["tables"] = sources["sources"][0]["tables"][:-1]
            write_yaml(sources_path, sources)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            contract_check = check(report, "sources_match_data_contract")
            self.assertFalse(contract_check["valid"])
            self.assertIn({"missing": "currency_rates"}, contract_check["sample"])
            self.assertIn(
                {
                    "source": "users",
                    "observed": "raw_wrong_users",
                    "expected": "raw_users",
                },
                contract_check["sample"],
            )

    def test_freshness_config_must_match_contract_column(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            sources_path = project / "models" / "sources.yml"
            sources = read_yaml(sources_path)
            sources["sources"][0]["tables"][2]["config"]["loaded_at_field"] = "loaded_at"
            del sources["sources"][0]["tables"][2]["config"]["freshness"]["error_after"]
            write_yaml(sources_path, sources)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            freshness_check = check(report, "sources_have_freshness_config")
            self.assertFalse(freshness_check["valid"])
            self.assertEqual(freshness_check["sample"][0]["source"], "orders")

    def test_staging_models_must_use_source_function(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            staging_model = project / "models" / "staging" / "stg_orders.sql"
            staging_model.write_text(
                "select * from raw.raw_orders\n",
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            source_check = check(report, "source_calls_stay_in_staging")
            raw_check = check(report, "sql_has_no_direct_raw_references")
            self.assertFalse(source_check["valid"])
            self.assertIn("stg_orders", source_check["sample"])
            self.assertFalse(raw_check["valid"])
            self.assertEqual(raw_check["sample"][0]["raw_identifiers"], ["raw_orders"])

    def test_downstream_model_cannot_read_source_directly(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            mart = project / "models" / "marts" / "mart_customer_revenue_health.sql"
            mart.write_text(
                "select user_id from {{ source('raw_app', 'users') }}\n",
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            source_check = check(report, "source_calls_stay_in_staging")
            ref_check = check(report, "downstream_models_use_ref")
            self.assertFalse(source_check["valid"])
            self.assertIn("mart_customer_revenue_health", source_check["sample"])
            self.assertFalse(ref_check["valid"])

    def test_downstream_models_need_ref_calls(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            intermediate = project / "models" / "intermediate" / "int_order_line_revenue.sql"
            intermediate.write_text(
                "select order_id, user_id from analytics.stg_orders\n",
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            ref_check = check(report, "downstream_models_use_ref")
            self.assertFalse(ref_check["valid"])
            self.assertEqual(ref_check["sample"], ["int_order_line_revenue"])

    def test_live_dbt_manifest_and_freshness_checks_pass(self) -> None:
        report = AUDITOR.validate_project(PROJECT, DATA_CONTRACT, run_dbt=True)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["freshness_state_counts"], {"pass": 8})
        self.assertTrue(check(report, "manifest_contains_declared_sources")["valid"])
        self.assertTrue(check(report, "manifest_downstream_uses_ref_graph")["valid"])

    def test_missing_csv_blocks_live_source_freshness(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            data_dir = Path(directory) / "data"
            shutil.copytree(DATA_CONTRACT.parent / "tiny", data_dir)
            (data_dir / "raw_orders.csv").unlink()
            with self.assertRaises(FileNotFoundError):
                AUDITOR.validate_project(project, DATA_CONTRACT, data_dir=data_dir, run_dbt=True)

    def test_cli_writes_report_and_returns_nonzero_for_invalid_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            output = Path(directory) / "audit.json"
            (project / "models" / "staging" / "stg_users.sql").write_text(
                "select * from raw.raw_users\n",
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
            self.assertFalse(check(report, "sql_has_no_direct_raw_references")["valid"])


if __name__ == "__main__":
    unittest.main()
