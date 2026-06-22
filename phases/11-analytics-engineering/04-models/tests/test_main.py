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
ARTIFACT = ROOT / "outputs" / "materialization_reporter.py"
PROJECT = ROOT / "outputs" / "materialization_project"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("materialization_reporter", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
REPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORTER)


def check(report: dict, check_id: str) -> dict:
    return next(item for item in report["checks"] if item["id"] == check_id)


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def model_spec(properties: dict, name: str) -> dict:
    return next(item for item in properties["models"] if item["name"] == name)


class MaterializationReporterTest(unittest.TestCase):
    def copy_project(self, tmp: str) -> Path:
        destination = Path(tmp) / "project"
        shutil.copytree(PROJECT, destination)
        return destination

    def test_valid_project_declares_materialization_policy(self) -> None:
        report = REPORTER.validate_project(PROJECT, DATA_CONTRACT, run_dbt=False)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["materialization_counts"], {"ephemeral": 2, "table": 1, "view": 10})
        self.assertTrue(check(report, "materializations_match_policy")["valid"])
        self.assertTrue(check(report, "materialization_decisions_documented")["valid"])

    def test_staging_model_cannot_be_materialized_as_table(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            properties_path = project / "models" / "properties.yml"
            properties = read_yaml(properties_path)
            model_spec(properties, "stg_orders")["config"]["materialized"] = "table"
            write_yaml(properties_path, properties)
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            policy_check = check(report, "materializations_match_policy")
            self.assertFalse(policy_check["valid"])
            self.assertIn(
                {"model": "stg_orders", "observed": "table", "expected": "view"},
                policy_check["sample"],
            )

    def test_materialization_reason_is_required_for_every_model(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            properties_path = project / "models" / "properties.yml"
            properties = read_yaml(properties_path)
            del model_spec(properties, "mart_customer_revenue_health")["meta"]["materialization_reason"]
            write_yaml(properties_path, properties)
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            docs_check = check(report, "materialization_decisions_documented")
            self.assertFalse(docs_check["valid"])
            self.assertEqual(docs_check["sample"][0]["model"], "mart_customer_revenue_health")

    def test_future_incremental_materialization_is_reserved_for_later_lesson(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            properties_path = project / "models" / "properties.yml"
            properties = read_yaml(properties_path)
            model_spec(properties, "mart_customer_revenue_health")["config"]["materialized"] = "incremental"
            write_yaml(properties_path, properties)
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "materializations_match_policy")["valid"])
            future_check = check(report, "no_future_materializations_in_this_lesson")
            self.assertFalse(future_check["valid"])
            self.assertEqual(future_check["sample"], ["mart_customer_revenue_health"])

    def test_staging_direct_raw_reference_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            (project / "models" / "staging" / "stg_orders.sql").write_text(
                "select * from raw.raw_orders\n",
                encoding="utf-8",
            )
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "source_calls_stay_in_staging")["valid"])
            raw_check = check(report, "sql_has_no_direct_raw_references")
            self.assertFalse(raw_check["valid"])
            self.assertEqual(raw_check["sample"][0]["raw_identifiers"], ["raw_orders"])

    def test_mart_cannot_read_source_directly(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            (project / "models" / "marts" / "mart_customer_revenue_health.sql").write_text(
                "select user_id from {{ source('raw_app', 'users') }}\n",
                encoding="utf-8",
            )
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "source_calls_stay_in_staging")["valid"])
            self.assertFalse(check(report, "downstream_models_use_ref")["valid"])
            self.assertFalse(check(report, "mart_uses_required_upstream_models")["valid"])

    def test_ephemeral_model_cannot_gain_wide_fanout(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            for relative in (
                "models/intermediate/int_support_by_user.sql",
                "models/intermediate/int_subscription_latest.sql",
            ):
                (project / relative).write_text(
                    "select * from {{ ref('int_order_line_revenue') }}\n",
                    encoding="utf-8",
                )
            report = REPORTER.validate_project(project, DATA_CONTRACT, run_dbt=False)
            fanout_check = check(report, "ephemeral_models_have_limited_fanout")
            self.assertFalse(fanout_check["valid"])
            self.assertEqual(fanout_check["sample"][0]["model"], "int_order_line_revenue")

    def test_live_dbt_run_builds_expected_physical_relations_and_mart(self) -> None:
        report = REPORTER.validate_project(PROJECT, DATA_CONTRACT, run_dbt=True)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["physical_relation_counts"], {"table": 1, "view": 10})
        self.assertEqual(report["summary"]["mart_row_count"], 5)
        self.assertTrue(check(report, "compiled_mart_inlines_ephemeral_models")["valid"])
        self.assertTrue(check(report, "mart_matches_independent_control")["valid"])

    def test_missing_currency_rate_breaks_live_mart_control(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            data_dir = Path(directory) / "data"
            shutil.copytree(DATA_CONTRACT.parent / "tiny", data_dir)
            rates = (data_dir / "raw_currency_rates.csv").read_text(encoding="utf-8").splitlines()
            (data_dir / "raw_currency_rates.csv").write_text(
                "\n".join(line for line in rates if not line.startswith("USD,")) + "\n",
                encoding="utf-8",
            )
            report = REPORTER.validate_project(project, DATA_CONTRACT, data_dir=data_dir, run_dbt=True)
            self.assertFalse(report["valid"])
            self.assertTrue(check(report, "dbt_parse_compile_run_succeed")["valid"])
            self.assertFalse(check(report, "mart_matches_independent_control")["valid"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            output = Path(directory) / "report.json"
            properties_path = project / "models" / "properties.yml"
            properties = read_yaml(properties_path)
            model_spec(properties, "int_order_line_revenue")["config"]["materialized"] = "table"
            write_yaml(properties_path, properties)
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
            self.assertFalse(check(report, "materializations_match_policy")["valid"])


if __name__ == "__main__":
    unittest.main()
