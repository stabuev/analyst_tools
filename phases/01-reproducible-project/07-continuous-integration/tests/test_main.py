from __future__ import annotations

import copy
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "outputs" / "ci_project"
ARTIFACT = PROJECT / "tools" / "workflow_audit.py"
WORKFLOW = PROJECT / ".github" / "workflows" / "quality.yml"
SPEC = importlib.util.spec_from_file_location("workflow_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class WorkflowAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = AUDIT.load_workflow(WORKFLOW)

    def failed_check(self, report, check_id: str) -> bool:
        return not next(
            check for check in report["checks"] if check["id"] == check_id
        )["passed"]

    def test_quality_workflow_passes_contract(self) -> None:
        report = AUDIT.evaluate(self.workflow)

        self.assertTrue(report["ready"], report)

    def test_pull_request_trigger_is_required(self) -> None:
        workflow = copy.deepcopy(self.workflow)
        workflow["on"].pop("pull_request")

        report = AUDIT.evaluate(workflow)

        self.assertTrue(self.failed_check(report, "triggers"))

    def test_write_permissions_are_rejected(self) -> None:
        workflow = copy.deepcopy(self.workflow)
        workflow["permissions"] = {"contents": "write"}

        report = AUDIT.evaluate(workflow)

        self.assertTrue(self.failed_check(report, "permissions"))

    def test_setup_uv_must_use_expected_sha(self) -> None:
        workflow = copy.deepcopy(self.workflow)
        steps = workflow["jobs"]["quality"]["steps"]
        setup_uv = next(step for step in steps if "astral-sh/setup-uv@" in step.get("uses", ""))
        setup_uv["uses"] = "astral-sh/setup-uv@v8"

        report = AUDIT.evaluate(workflow)

        self.assertTrue(self.failed_check(report, "actions"))

    def test_continue_on_error_is_rejected(self) -> None:
        workflow = copy.deepcopy(self.workflow)
        workflow["jobs"]["quality"]["steps"][-1]["continue-on-error"] = "true"

        report = AUDIT.evaluate(workflow)

        self.assertTrue(self.failed_check(report, "commands"))

    def test_locked_sync_is_required(self) -> None:
        workflow = copy.deepcopy(self.workflow)
        sync = next(
            step
            for step in workflow["jobs"]["quality"]["steps"]
            if step.get("name") == "Sync locked environment"
        )
        sync["run"] = "uv sync"

        report = AUDIT.evaluate(workflow)

        self.assertTrue(self.failed_check(report, "commands"))

    def test_uv_lock_is_current(self) -> None:
        environment = os.environ | {
            "UV_CACHE_DIR": str(
                Path(tempfile.gettempdir()) / "analyst-tools-ci-lock-cache"
            )
        }
        result = subprocess.run(
            ["uv", "lock", "--check"],
            cwd=PROJECT,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sample_project_tests_pass(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "pytest"],
            cwd=PROJECT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("4 passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
