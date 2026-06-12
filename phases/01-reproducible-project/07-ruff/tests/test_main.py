from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "ruff_gate.py"
PROJECT = ROOT / "outputs" / "ruff_project"
SPEC = importlib.util.spec_from_file_location("ruff_gate", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
RUFF = ["uvx", "--offline", "--from", "ruff==0.15.17", "ruff"]


class RuffGateTest(unittest.TestCase):
    def copy_project(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary_directory = tempfile.TemporaryDirectory()
        project = Path(temporary_directory.name) / "project"
        shutil.copytree(PROJECT, project)
        return temporary_directory, project

    def test_clean_project_passes_real_ruff(self) -> None:
        report = GATE.evaluate(PROJECT, RUFF)

        self.assertTrue(report["ready"], report)

    def test_unused_import_fails_lint(self) -> None:
        temporary_directory, project = self.copy_project()
        self.addCleanup(temporary_directory.cleanup)
        (project / "src" / "bad.py").write_text("import os\n\nvalue = 1\n", encoding="utf-8")

        report = GATE.evaluate(project, RUFF)
        lint = next(check for check in report["checks"] if check["id"] == "lint")

        self.assertFalse(lint["passed"])
        self.assertIn("F401", lint["message"])

    def test_safe_fix_removes_unused_import(self) -> None:
        temporary_directory, project = self.copy_project()
        self.addCleanup(temporary_directory.cleanup)
        bad = project / "src" / "bad.py"
        bad.write_text("import os\n\nvalue = 1\n", encoding="utf-8")

        result = subprocess.run(
            [*RUFF, "check", "--fix", str(bad)],
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
            env=GATE.subprocess_environment(RUFF),
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("import os", bad.read_text(encoding="utf-8"))

    def test_format_check_detects_and_repairs_file(self) -> None:
        temporary_directory, project = self.copy_project()
        self.addCleanup(temporary_directory.cleanup)
        bad = project / "src" / "format_me.py"
        bad.write_text("def add(a,b): return a+b\n", encoding="utf-8")

        before = GATE.evaluate(project, RUFF)
        format_check = next(
            check for check in before["checks"] if check["id"] == "format"
        )
        self.assertFalse(format_check["passed"])

        result = subprocess.run(
            [*RUFF, "format", str(bad)],
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
            env=GATE.subprocess_environment(RUFF),
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("def add(a, b):", bad.read_text(encoding="utf-8"))

    def test_missing_rule_family_breaks_contract(self) -> None:
        temporary_directory, project = self.copy_project()
        self.addCleanup(temporary_directory.cleanup)
        config = project / "pyproject.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                'select = ["E", "F", "I", "UP", "B", "SIM"]',
                'select = ["E", "F"]',
            ),
            encoding="utf-8",
        )

        report = GATE.evaluate(project, RUFF)
        check = next(
            check for check in report["checks"] if check["id"] == "configuration"
        )

        self.assertFalse(check["passed"])
        self.assertIn("missing rule families", check["message"])

    def test_missing_binary_is_reported(self) -> None:
        report = GATE.evaluate(PROJECT, ["definitely-missing-ruff"])

        self.assertFalse(report["ready"])
        self.assertTrue(
            all(
                "command not found" in check["message"]
                for check in report["checks"]
                if check["id"] in {"lint", "format"}
            )
        )


if __name__ == "__main__":
    unittest.main()
