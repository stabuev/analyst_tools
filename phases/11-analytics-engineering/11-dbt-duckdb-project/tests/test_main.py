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


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "analytics_mart_packager.py"
PROJECT = ROOT / "outputs" / "analytics-mart-dbt"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("analytics_mart_packager", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PACKAGER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGER)


def check(report: dict[str, Any], check_id: str) -> dict[str, Any]:
    return next(item for item in report["checks"] if item["id"] == check_id)


class AnalyticsMartPackageTest(unittest.TestCase):
    def copy_project(self, tmp: str) -> Path:
        destination = Path(tmp) / "analytics-mart-dbt"
        shutil.copytree(PROJECT, destination)
        return destination

    def test_valid_package_contains_release_artifacts_and_quality_reports(self) -> None:
        report = PACKAGER.validate_project(PROJECT, DATA_CONTRACT, build_package=False)
        self.assertTrue(report["valid"])
        self.assertTrue(check(report, "release_files_exist")["valid"])
        self.assertTrue(check(report, "dbt_test_report_has_no_blocking_failures")["valid"])
        self.assertTrue(check(report, "sqlfluff_report_has_zero_violations")["valid"])
        self.assertEqual(report["summary"]["release_files"], 10)

        test_report = json.loads((PROJECT / "quality" / "dbt-test-report.json").read_text(encoding="utf-8"))
        self.assertEqual(test_report["status"], "pass")
        self.assertEqual(test_report["warning_test_count"], 1)
        self.assertEqual(test_report["counts_by_status"], {"pass": 86, "warn": 1})

    def test_live_build_refreshes_release_package_on_temp_copy(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            PACKAGER.clean_release_outputs(project)
            report = PACKAGER.validate_project(project, DATA_CONTRACT, build_package=True)
            self.assertTrue(report["valid"])
            self.assertTrue((project / "target-artifacts" / "manifest.json").is_file())
            self.assertTrue((project / "quality" / "sqlfluff-report.json").is_file())
            self.assertTrue(check(report, "dbt_local_gate_succeeds")["valid"])
            self.assertEqual(report["summary"]["artifact_counts"]["run_results"], 87)

    def test_models_cannot_reference_raw_relations_directly(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            model = project / "models" / "staging" / "stg_orders.sql"
            model.write_text("select * from raw.raw_orders\n", encoding="utf-8")
            report = PACKAGER.validate_project(project, DATA_CONTRACT, build_package=False)
            self.assertFalse(check(report, "sources_are_complete_and_models_do_not_reference_raw_relations")["valid"])

    def test_incremental_fact_requires_late_arrival_window(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            fact = project / "models" / "marts" / "fct_order_revenue_daily.sql"
            fact.write_text(fact.read_text(encoding="utf-8").replace("interval '2 days'", "interval '10 days'"), encoding="utf-8")
            report = PACKAGER.validate_project(project, DATA_CONTRACT, build_package=False)
            self.assertFalse(check(report, "incremental_fact_has_unique_key_late_window_and_full_refresh_policy")["valid"])

    def test_sqlfluff_dbt_templater_is_required(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            config = project / ".sqlfluff"
            config.write_text(config.read_text(encoding="utf-8").replace("templater = dbt", "templater = jinja"), encoding="utf-8")
            report = PACKAGER.validate_project(project, DATA_CONTRACT, build_package=False)
            self.assertFalse(check(report, "sqlfluff_uses_duckdb_dbt_templater")["valid"])

    def test_report_claims_must_resolve_to_manifest_nodes(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            report_md = project / "report.md"
            report_md.write_text(
                report_md.read_text(encoding="utf-8").replace(
                    "test.analytics_mart_dbt.assert_paid_revenue_reconciles",
                    "test.analytics_mart_dbt.missing_assert_paid_revenue_reconciles",
                ),
                encoding="utf-8",
            )
            report = PACKAGER.validate_project(project, DATA_CONTRACT, build_package=False)
            self.assertFalse(check(report, "report_claims_resolve_to_manifest_nodes")["valid"])

    def test_checksum_manifest_detects_tampering(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            contract = project / "docs" / "mart_contract.md"
            contract.write_text(contract.read_text(encoding="utf-8") + "\nUnreleased local edit.\n", encoding="utf-8")
            report = PACKAGER.validate_project(project, DATA_CONTRACT, build_package=False)
            self.assertFalse(check(report, "checksum_manifest_matches_release_files")["valid"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            output = Path(directory) / "audit.json"
            dbt_project = project / "dbt_project.yml"
            dbt_project.write_text(dbt_project.read_text(encoding="utf-8").replace("analytics_mart_dbt", "broken_project", 1), encoding="utf-8")
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
            self.assertFalse(check(report, "dbt_project_identity_is_final")["valid"])


if __name__ == "__main__":
    unittest.main()
