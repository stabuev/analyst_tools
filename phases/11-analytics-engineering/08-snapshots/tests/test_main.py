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
ARTIFACT = ROOT / "outputs" / "snapshot_history_auditor.py"
PROJECT = ROOT / "outputs" / "snapshot_project"
RUNBOOK = ROOT / "outputs" / "snapshot_history_runbook.md"
DATA_CONTRACT = ROOT.parent / "data" / "contract.json"
SPEC = importlib.util.spec_from_file_location("snapshot_history_auditor", ARTIFACT)
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


def snapshot_doc(snapshot_yaml: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in snapshot_yaml["snapshots"] if item["name"] == name)


def model_doc(properties: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in properties["models"] if item["name"] == name)


class SnapshotHistoryAuditorTest(unittest.TestCase):
    def copy_project(self, tmp: str) -> Path:
        base = Path(tmp)
        destination = base / "project"
        shutil.copytree(PROJECT, destination)
        shutil.copy(RUNBOOK, base / RUNBOOK.name)
        return destination

    def test_valid_project_declares_snapshot_contract(self) -> None:
        report = AUDITOR.validate_project(PROJECT, DATA_CONTRACT, run_dbt=False)
        self.assertTrue(report["valid"])
        contract = report["summary"]["snapshot_contract"]
        self.assertEqual(contract["unique_key"], "subscription_id")
        self.assertEqual(contract["strategy"], "check")
        self.assertEqual(contract["check_cols"], ["plan", "status", "started_at", "ended_at"])
        self.assertEqual(contract["excluded_noisy_columns"], ["updated_at"])
        self.assertTrue(check(report, "snapshots_use_yaml_not_legacy_sql")["valid"])
        self.assertTrue(check(report, "subscription_staging_is_snapshot_safe")["valid"])

    def test_live_snapshot_captures_business_changes_but_not_noisy_updated_at(self) -> None:
        report = AUDITOR.validate_project(PROJECT, DATA_CONTRACT, run_dbt=True)
        self.assertTrue(report["valid"])
        self.assertEqual(
            report["summary"]["initial_history_output"],
            {
                "row_count": 4,
                "subscription_count": 4,
                "current_rows": 4,
                "closed_rows": 0,
                "s001_versions": 1,
                "s002_versions": 1,
                "s004_versions": 1,
                "s005_versions": 0,
                "s002_current_plus": 0,
                "s004_current_cancelled": 0,
                "overlap_count": 0,
            },
        )
        self.assertEqual(
            report["summary"]["changed_history_output"],
            {
                "row_count": 7,
                "subscription_count": 5,
                "current_rows": 5,
                "closed_rows": 2,
                "s001_versions": 1,
                "s002_versions": 2,
                "s004_versions": 2,
                "s005_versions": 1,
                "s002_current_plus": 1,
                "s004_current_cancelled": 1,
                "overlap_count": 0,
            },
        )

    def test_unique_key_and_updated_at_are_required(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            snapshot_path = project / "snapshots" / "subscription_status_history.yml"
            snapshot_yaml = read_yaml(snapshot_path)
            config = snapshot_doc(snapshot_yaml, "subscription_status_snapshot")["config"]
            config.pop("unique_key")
            config.pop("updated_at")
            write_yaml(snapshot_path, snapshot_yaml)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "snapshot_config_is_explicit")["valid"])

    def test_check_cols_all_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            snapshot_path = project / "snapshots" / "subscription_status_history.yml"
            snapshot_yaml = read_yaml(snapshot_path)
            snapshot_doc(snapshot_yaml, "subscription_status_snapshot")["config"]["check_cols"] = "all"
            write_yaml(snapshot_path, snapshot_yaml)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "snapshot_config_is_explicit")["valid"])
            self.assertFalse(check(report, "snapshot_excludes_noisy_columns")["valid"])

    def test_updated_at_cannot_be_in_check_cols(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            snapshot_path = project / "snapshots" / "subscription_status_history.yml"
            snapshot_yaml = read_yaml(snapshot_path)
            snapshot_doc(snapshot_yaml, "subscription_status_snapshot")["config"]["check_cols"].append("updated_at")
            write_yaml(snapshot_path, snapshot_yaml)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "snapshot_config_is_explicit")["valid"])
            self.assertFalse(check(report, "snapshot_excludes_noisy_columns")["valid"])

    def test_legacy_sql_snapshot_file_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            (project / "snapshots" / "legacy_snapshot.sql").write_text(
                "{% snapshot legacy_snapshot %} select 1 as id {% endsnapshot %}\n",
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "snapshots_use_yaml_not_legacy_sql")["valid"])

    def test_history_model_contract_is_required(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            properties_path = project / "models" / "properties.yml"
            properties = read_yaml(properties_path)
            model_doc(properties, "int_subscription_history")["meta"].pop("snapshot_contract")
            write_yaml(properties_path, properties)
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "history_model_repeats_snapshot_contract")["valid"])

    def test_staging_must_handle_nullable_ended_at_and_timestamp_type(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            staging_path = project / "models" / "staging" / "stg_subscriptions.sql"
            staging_path.write_text(
                staging_path.read_text(encoding="utf-8")
                .replace("cast(nullif(cast(ended_at as varchar), '') as timestamptz)", "cast(nullif(ended_at, '') as timestamptz)")
                .replace("cast(updated_at as timestamp)", "cast(updated_at as timestamptz)"),
                encoding="utf-8",
            )
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "subscription_staging_is_snapshot_safe")["valid"])

    def test_runbook_must_name_schedule_and_hard_delete_policy(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            playbook = Path(directory) / RUNBOOK.name
            playbook.write_text("Run dbt snapshot sometimes.\n", encoding="utf-8")
            report = AUDITOR.validate_project(project, DATA_CONTRACT, run_dbt=False)
            self.assertFalse(check(report, "snapshot_runbook_exists")["valid"])

    def test_cli_writes_report_and_returns_nonzero_for_invalid_project(self) -> None:
        with TemporaryDirectory() as directory:
            project = self.copy_project(directory)
            output = Path(directory) / "report.json"
            snapshot_path = project / "snapshots" / "subscription_status_history.yml"
            snapshot_yaml = read_yaml(snapshot_path)
            snapshot_doc(snapshot_yaml, "subscription_status_snapshot")["config"]["strategy"] = "timestamp"
            write_yaml(snapshot_path, snapshot_yaml)
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
            self.assertFalse(check(report, "snapshot_config_is_explicit")["valid"])


if __name__ == "__main__":
    unittest.main()
