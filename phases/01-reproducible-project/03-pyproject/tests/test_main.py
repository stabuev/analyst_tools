from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ARTIFACT = (
    Path(__file__).resolve().parents[1] / "outputs" / "pyproject_audit.py"
)
SPEC = importlib.util.spec_from_file_location("pyproject_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class PyprojectAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def initialize(self) -> None:
        AUDIT.initialize_manifest(
            self.root,
            project_name="analytics-lab",
            description='Проект с "кавычками" в описании',
            requires_python=">=3.11,<3.14",
        )

    def check_message(self, check_id: str) -> str:
        report = AUDIT.evaluate_manifest(self.root)
        return next(
            check["message"] for check in report["checks"] if check["id"] == check_id
        )

    def test_generated_manifest_is_valid_and_escaped(self) -> None:
        self.initialize()

        report = AUDIT.evaluate_manifest(self.root)

        self.assertTrue(report["ready"])
        self.assertEqual(report["project"]["name"], "analytics-lab")

    def test_missing_readme_breaks_metadata_contract(self) -> None:
        self.initialize()
        (self.root / "README.md").unlink()

        self.assertIn("README target does not exist", self.check_message("metadata"))

    def test_normalized_runtime_duplicates_are_detected(self) -> None:
        self.initialize()
        manifest = self.root / "pyproject.toml"
        text = manifest.read_text(encoding="utf-8")
        manifest.write_text(
            text.replace(
                'dependencies = ["numpy>=2,<3"]',
                'dependencies = ["My_Package>=1", "my-package<3"]',
            ),
            encoding="utf-8",
        )

        self.assertIn(
            "duplicate runtime dependencies: my-package",
            self.check_message("dependencies"),
        )

    def test_development_tool_in_runtime_is_rejected(self) -> None:
        self.initialize()
        manifest = self.root / "pyproject.toml"
        text = manifest.read_text(encoding="utf-8")
        manifest.write_text(
            text.replace(
                'dependencies = ["numpy>=2,<3"]',
                'dependencies = ["numpy>=2,<3", "pytest>=8"]',
            ),
            encoding="utf-8",
        )

        self.assertIn(
            "development tools belong in dependency-groups: pytest",
            self.check_message("dependencies"),
        )

    def test_tool_configuration_requires_matching_dev_dependency(self) -> None:
        self.initialize()
        manifest = self.root / "pyproject.toml"
        text = manifest.read_text(encoding="utf-8")
        manifest.write_text(
            text.replace(
                'dev = ["pytest>=8", "ruff>=0.6"]',
                'dev = ["pytest>=8"]',
            ),
            encoding="utf-8",
        )

        self.assertIn(
            "tool.ruff is configured but ruff is absent from dev group",
            self.check_message("tools"),
        )

    def test_dependency_cannot_be_runtime_and_development(self) -> None:
        self.initialize()
        manifest = self.root / "pyproject.toml"
        text = manifest.read_text(encoding="utf-8")
        manifest.write_text(
            text.replace(
                'dev = ["pytest>=8", "ruff>=0.6"]',
                'dev = ["pytest>=8", "ruff>=0.6", "NumPy>=2"]',
            ),
            encoding="utf-8",
        )

        self.assertIn(
            "dependencies appear in runtime and dev groups: numpy",
            self.check_message("groups"),
        )

    def test_invalid_script_target_is_detected(self) -> None:
        self.initialize()
        manifest = self.root / "pyproject.toml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8")
            + '\n[project.scripts]\nreport = "analysis.py"\n',
            encoding="utf-8",
        )

        self.assertIn("script target is invalid: report", self.check_message("scripts"))


if __name__ == "__main__":
    unittest.main()
