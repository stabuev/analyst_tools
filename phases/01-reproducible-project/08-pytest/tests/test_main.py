from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "pytest_gate.py"
PROJECT = ROOT / "outputs" / "pytest_project"
SPEC = importlib.util.spec_from_file_location("pytest_gate", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class PytestGateTest(unittest.TestCase):
    def copy_project(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary_directory = tempfile.TemporaryDirectory()
        project = Path(temporary_directory.name) / "project"
        shutil.copytree(PROJECT, project)
        return temporary_directory, project

    def test_behavioral_suite_passes(self) -> None:
        report = GATE.evaluate(PROJECT)

        self.assertTrue(report["ready"], report)

    def test_broken_business_logic_makes_suite_fail(self) -> None:
        temporary_directory, project = self.copy_project()
        self.addCleanup(temporary_directory.cleanup)
        implementation = project / "src" / "funnel.py"
        implementation.write_text(
            implementation.read_text(encoding="utf-8").replace(
                "conversion_rate=len(converters) / len(entrants)",
                "conversion_rate=0.5",
            ),
            encoding="utf-8",
        )

        report = GATE.evaluate(project)

        self.assertFalse(report["ready"])
        self.assertNotEqual(report["returncode"], 0)

    def test_configuration_requires_strict_markers(self) -> None:
        temporary_directory, project = self.copy_project()
        self.addCleanup(temporary_directory.cleanup)
        config = project / "pyproject.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(" --strict-markers", ""),
            encoding="utf-8",
        )

        report = GATE.evaluate(project)
        check = next(
            check for check in report["checks"] if check["id"] == "configuration"
        )

        self.assertFalse(check["passed"])

    def test_missing_pytest_command_is_reported(self) -> None:
        report = GATE.evaluate(PROJECT, ["definitely-missing-pytest"])

        self.assertFalse(report["ready"])
        self.assertEqual(report["returncode"], 127)

    def test_suite_collects_all_parametrized_cases(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=PROJECT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            "tests/test_funnel.py: 8" in result.stdout
            or "8 tests collected" in result.stdout
        )

    def test_suite_uses_core_pytest_features(self) -> None:
        source = (PROJECT / "tests" / "test_funnel.py").read_text(encoding="utf-8")

        self.assertIn("@pytest.fixture", source)
        self.assertIn("@pytest.mark.parametrize", source)
        self.assertIn("pytest.approx", source)
        self.assertIn("pytest.raises", source)


if __name__ == "__main__":
    unittest.main()
