from __future__ import annotations

import copy
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
ARTIFACT = ROOT / "outputs" / "dbt_project_auditor.py"
SKELETON = ROOT / "outputs" / "dbt_project_skeleton"
SPEC = importlib.util.spec_from_file_location("dbt_project_auditor", ARTIFACT)
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


class DbtProjectAuditorTest(unittest.TestCase):
    def copy_skeleton(self, tmp: str) -> Path:
        destination = Path(tmp) / "project"
        shutil.copytree(SKELETON, destination)
        return destination

    def test_valid_skeleton_passes_static_contract(self) -> None:
        report = AUDITOR.validate_project(SKELETON, run_dbt=False)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["project_name"], "analytics_engineering_skeleton")
        self.assertTrue(check(report, "resource_directories_exist")["valid"])
        self.assertTrue(check(report, "commands_document_debug_parse_compile")["valid"])

    def test_required_configuration_files_are_checked(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_skeleton(directory)
            (project / "dbt_project.yml").unlink()
            report = AUDITOR.validate_project(project, run_dbt=False)
            config_check = check(report, "required_configuration_files_exist")
            self.assertFalse(config_check["valid"])
            self.assertEqual(config_check["sample"], ["dbt_project.yml"])

    def test_project_profile_must_exist_in_profile_example(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_skeleton(directory)
            config = read_yaml(project / "dbt_project.yml")
            config["profile"] = "missing_profile"
            write_yaml(project / "dbt_project.yml", config)
            report = AUDITOR.validate_project(project, run_dbt=False)
            profile_check = check(report, "project_profile_exists")
            self.assertFalse(profile_check["valid"])
            self.assertEqual(profile_check["sample"], ["missing_profile"])

    def test_resource_directories_must_exist(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_skeleton(directory)
            shutil.rmtree(project / "snapshots")
            report = AUDITOR.validate_project(project, run_dbt=False)
            directory_check = check(report, "resource_directories_exist")
            self.assertFalse(directory_check["valid"])
            self.assertIn("snapshots", directory_check["sample"])

    def test_layer_directories_need_smoke_models(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_skeleton(directory)
            (project / "models" / "marts" / "mart_project_smoke.sql").unlink()
            report = AUDITOR.validate_project(project, run_dbt=False)
            layer_check = check(report, "layer_directories_have_smoke_models")
            self.assertFalse(layer_check["valid"])
            self.assertEqual(layer_check["sample"], ["marts"])

    def test_profile_must_use_local_duckdb(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_skeleton(directory)
            profile = read_yaml(project / "profiles.yml.example")
            dev = profile["analytics_engineering_skeleton"]["outputs"]["dev"]
            dev["type"] = "postgres"
            dev["path"] = "md:cloud_database"
            write_yaml(project / "profiles.yml.example", profile)
            report = AUDITOR.validate_project(project, run_dbt=False)
            duckdb_check = check(report, "profile_uses_local_duckdb")
            self.assertFalse(duckdb_check["valid"])
            self.assertIn("type must be duckdb", duckdb_check["sample"])

    def test_profile_cannot_contain_secret_like_fields(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_skeleton(directory)
            profile = read_yaml(project / "profiles.yml.example")
            dev = profile["analytics_engineering_skeleton"]["outputs"]["dev"]
            dev["password"] = "{{ env_var('WAREHOUSE_PASSWORD') }}"
            write_yaml(project / "profiles.yml.example", profile)
            report = AUDITOR.validate_project(project, run_dbt=False)
            secret_check = check(report, "profile_contains_no_secret_fields")
            self.assertFalse(secret_check["valid"])
            self.assertEqual(
                secret_check["sample"],
                ["analytics_engineering_skeleton.outputs.dev.password"],
            )

    def test_commands_must_document_debug_parse_and_compile(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_skeleton(directory)
            commands = (project / "commands.md").read_text(encoding="utf-8")
            (project / "commands.md").write_text(
                commands.replace("dbt compile", "dbt ls"),
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, run_dbt=False)
            commands_check = check(report, "commands_document_debug_parse_compile")
            self.assertFalse(commands_check["valid"])
            self.assertEqual(commands_check["sample"], ["compile"])

    def test_live_dbt_debug_parse_and_compile_succeed_in_temporary_copy(self) -> None:
        report = AUDITOR.validate_project(SKELETON, run_dbt=True)
        self.assertTrue(report["valid"])
        live_check = check(report, "dbt_debug_parse_compile_succeed")
        self.assertTrue(live_check["valid"])
        self.assertEqual(
            [item["returncode"] for item in report["summary"]["dbt_commands"]],
            [0, 0, 0],
        )

    def test_cli_writes_report_and_returns_nonzero_for_invalid_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_skeleton(directory)
            shutil.rmtree(project / "macros")
            output_path = Path(directory) / "audit.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--project",
                    project,
                    "--output",
                    output_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertFalse(report["valid"])
            self.assertFalse(check(report, "resource_directories_exist")["valid"])

    def test_static_report_is_not_mutated_by_callers(self) -> None:
        report = AUDITOR.validate_project(SKELETON, run_dbt=False)
        cloned = copy.deepcopy(report)
        cloned["checks"][0]["valid"] = False
        fresh = AUDITOR.validate_project(SKELETON, run_dbt=False)
        self.assertTrue(fresh["checks"][0]["valid"])


if __name__ == "__main__":
    unittest.main()
