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
ARTIFACT = ROOT / "outputs" / "documentation_lineage_auditor.py"
PROJECT = ROOT / "outputs" / "documentation_project"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("documentation_lineage_auditor", ARTIFACT)
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


def exposure_doc(exposures: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in exposures["exposures"] if item["name"] == name)


class DocumentationLineageAuditorTest(unittest.TestCase):
    def copy_project(self, tmp: str) -> Path:
        destination = Path(tmp) / "project"
        shutil.copytree(PROJECT, destination)
        return destination

    def test_valid_project_declares_documentation_contract(self) -> None:
        report = AUDITOR.validate_project(PROJECT, DATA_CONTRACT, run_dbt=False)
        self.assertTrue(report["valid"])
        self.assertTrue(check(report, "docs_blocks_exist")["valid"])
        self.assertTrue(check(report, "sources_have_descriptions_owners_and_freshness")["valid"])
        self.assertTrue(check(report, "exposure_claims_link_to_models_and_tests")["valid"])
        self.assertEqual(report["summary"]["exposure"]["maturity"], "high")

    def test_live_dbt_docs_generate_produces_manifest_catalog_and_lineage(self) -> None:
        report = AUDITOR.validate_project(PROJECT, DATA_CONTRACT, run_dbt=True)
        self.assertTrue(report["valid"])
        self.assertTrue(check(report, "dbt_docs_generate_succeeds")["valid"])
        self.assertTrue(check(report, "docs_generate_writes_manifest_and_catalog")["valid"])
        self.assertTrue(check(report, "manifest_exposure_lineage_resolves")["valid"])
        self.assertGreaterEqual(report["summary"]["artifact_counts"]["nodes"], 100)
        self.assertEqual(report["summary"]["artifact_counts"]["exposures"], 1)

    def test_exposure_owner_is_required(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            exposures_path = project / "models" / "exposures.yml"
            exposures = read_yaml(exposures_path)
            exposure_doc(exposures, "customer_revenue_health_dashboard")["owner"] = {}
            write_yaml(exposures_path, exposures)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "exposure_declares_downstream_owner")["valid"])

    def test_exposure_cannot_depend_on_raw_source_directly(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            exposures_path = project / "models" / "exposures.yml"
            exposures = read_yaml(exposures_path)
            exposure_doc(exposures, "customer_revenue_health_dashboard")["depends_on"].append("source('raw_app', 'orders')")
            write_yaml(exposures_path, exposures)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "exposure_depends_on_documented_models_not_raw_sources")["valid"])

    def test_decision_claims_must_link_to_required_tests(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            exposures_path = project / "models" / "exposures.yml"
            exposures = read_yaml(exposures_path)
            claims = exposure_doc(exposures, "customer_revenue_health_dashboard")["meta"]["decision_claims"]
            claims[0]["required_tests"] = []
            write_yaml(exposures_path, exposures)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "exposure_claims_link_to_models_and_tests")["valid"])

    def test_docs_block_is_required_for_overview_and_consumer_resources(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            docs_path = project / "models" / "docs.md"
            docs_path.write_text(
                docs_path.read_text(encoding="utf-8").replace("{% docs mart_customer_revenue_health_docs %}", "{% docs mart_docs_missing %}"),
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "docs_blocks_exist")["valid"])

    def test_key_model_owner_and_column_docs_are_required(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            properties_path = project / "models" / "properties.yml"
            properties = read_yaml(properties_path)
            mart = model_doc(properties, "mart_customer_revenue_health")
            mart["meta"].pop("owner")
            for column in mart["columns"]:
                if column["name"] == "paid_revenue_rub":
                    column.pop("description")
            write_yaml(properties_path, properties)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "key_models_have_owner_grain_and_column_docs")["valid"])

    def test_source_freshness_column_must_be_described(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            sources_path = project / "models" / "sources.yml"
            sources = read_yaml(sources_path)
            raw_orders = next(table for table in sources["sources"][0]["tables"] if table["identifier"] == "raw_orders")
            raw_orders["config"]["loaded_at_field"] = "loaded_at"
            write_yaml(sources_path, sources)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "sources_have_descriptions_owners_and_freshness")["valid"])

    def test_singular_data_test_descriptions_are_required(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            tests_path = project / "tests" / "schema.yml"
            tests = read_yaml(tests_path)
            tests["data_tests"] = [item for item in tests["data_tests"] if item["name"] != "assert_daily_revenue_reconciles"]
            write_yaml(tests_path, tests)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "singular_data_tests_have_descriptions")["valid"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            output = Path(directory) / "report.json"
            exposures_path = project / "models" / "exposures.yml"
            exposures = read_yaml(exposures_path)
            exposure_doc(exposures, "customer_revenue_health_dashboard")["maturity"] = "low"
            write_yaml(exposures_path, exposures)
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
            self.assertFalse(check(report, "exposure_declares_downstream_owner")["valid"])


if __name__ == "__main__":
    unittest.main()
