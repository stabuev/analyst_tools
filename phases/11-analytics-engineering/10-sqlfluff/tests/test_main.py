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
ARTIFACT = ROOT / "outputs" / "sqlfluff_quality_gate.py"
PROJECT = ROOT / "outputs" / "sqlfluff_project"
BAD_EXAMPLE = ROOT / "outputs" / "bad_style_example.sql"
REPORT = ROOT / "outputs" / "sqlfluff_lint_report.json"
SPEC = importlib.util.spec_from_file_location("sqlfluff_quality_gate", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def check(report: dict[str, Any], check_id: str) -> dict[str, Any]:
    return next(item for item in report["checks"] if item["id"] == check_id)


class SQLFluffQualityGateTest(unittest.TestCase):
    def copy_project(self, tmp: str) -> Path:
        destination = Path(tmp) / "project"
        shutil.copytree(PROJECT, destination)
        return destination

    def copy_bad_example(self, tmp: str) -> Path:
        destination = Path(tmp) / "bad_style_example.sql"
        shutil.copy2(BAD_EXAMPLE, destination)
        return destination

    def test_valid_project_declares_sqlfluff_contract(self) -> None:
        report = GATE.validate_project(PROJECT, BAD_EXAMPLE, run_lint=False)
        self.assertTrue(report["valid"])
        self.assertTrue(check(report, "sqlfluff_core_config_declares_duckdb_dbt_style_gate")["valid"])
        self.assertTrue(check(report, "dbt_templater_is_explicit_and_local")["valid"])
        self.assertEqual(report["summary"]["sql_files"], 22)

    def test_live_sqlfluff_lint_passes_and_bad_example_fails(self) -> None:
        report = GATE.validate_project(PROJECT, BAD_EXAMPLE, run_lint=True)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["lint"]["violations"], 0)
        self.assertEqual(report["summary"]["lint"]["files"], 22)
        self.assertGreaterEqual(report["summary"]["bad_example"]["violations"], 3)
        self.assertIn("LT09", report["summary"]["bad_example"]["codes"])

    def test_committed_report_matches_live_summary(self) -> None:
        committed = json.loads(REPORT.read_text(encoding="utf-8"))
        live = GATE.validate_project(PROJECT, BAD_EXAMPLE, run_lint=True)
        self.assertTrue(committed["valid"])
        self.assertEqual(committed["summary"]["lint"], live["summary"]["lint"])
        self.assertEqual(committed["summary"]["bad_example"]["codes"], live["summary"]["bad_example"]["codes"])

    def test_templater_cannot_be_downgraded_to_jinja_for_dbt_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            config = project / ".sqlfluff"
            config.write_text(config.read_text(encoding="utf-8").replace("templater = dbt", "templater = jinja"), encoding="utf-8")
            report = GATE.validate_project(project, BAD_EXAMPLE, run_lint=False)
            self.assertFalse(check(report, "sqlfluff_core_config_declares_duckdb_dbt_style_gate")["valid"])

    def test_global_ignore_and_exclude_rules_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            config = project / ".sqlfluff"
            config.write_text(
                config.read_text(encoding="utf-8").replace(
                    "max_line_length = 120",
                    "max_line_length = 120\nignore = parsing,templating",
                ),
                encoding="utf-8",
            )
            report = GATE.validate_project(project, BAD_EXAMPLE, run_lint=False)
            self.assertFalse(check(report, "sqlfluff_core_config_declares_duckdb_dbt_style_gate")["valid"])

    def test_generated_artifacts_must_be_ignored(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            ignore = project / ".sqlfluffignore"
            ignore.write_text("target/\ndbt_packages/\n*.duckdb\n", encoding="utf-8")
            report = GATE.validate_project(project, BAD_EXAMPLE, run_lint=False)
            self.assertFalse(check(report, "generated_artifacts_are_ignored")["valid"])

    def test_keyword_like_aliases_are_rejected_before_lint_noise_spreads(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            mart = project / "models" / "marts" / "mart_customer_revenue_health.sql"
            mart.write_text(mart.read_text(encoding="utf-8").replace("as user_rows", "as users"), encoding="utf-8")
            report = GATE.validate_project(project, BAD_EXAMPLE, run_lint=False)
            self.assertFalse(check(report, "keyword_like_aliases_are_removed")["valid"])

    def test_profile_must_use_safe_local_duckdb(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            profile = project / "profiles.yml"
            profile.write_text(profile.read_text(encoding="utf-8").replace("type: duckdb", "type: postgres"), encoding="utf-8")
            report = GATE.validate_project(project, BAD_EXAMPLE, run_lint=False)
            self.assertFalse(check(report, "profile_uses_safe_local_duckdb")["valid"])

    def test_commands_must_keep_dbt_test_as_separate_gate(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            commands = project / "commands.md"
            commands.write_text(commands.read_text(encoding="utf-8").replace("dbt test", "dbt build"), encoding="utf-8")
            report = GATE.validate_project(project, BAD_EXAMPLE, run_lint=False)
            self.assertFalse(check(report, "commands_separate_style_gate_from_semantic_tests")["valid"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            bad_example = self.copy_bad_example(directory)
            output = Path(directory) / "report.json"
            config = project / ".sqlfluff"
            config.write_text(config.read_text(encoding="utf-8").replace("dialect = duckdb", "dialect = postgres"), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--project",
                    project,
                    "--bad-example",
                    bad_example,
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
            self.assertFalse(check(report, "sqlfluff_core_config_declares_duckdb_dbt_style_gate")["valid"])


if __name__ == "__main__":
    unittest.main()
