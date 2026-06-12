from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = LESSON_ROOT / "outputs" / "python_version_check.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("python_version_test", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load Python version checker")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def current_contract(tool, root: Path) -> tuple[str, str]:
    current = sys.version_info
    selector = f"{current.major}.{current.minor}"
    upper = f"{current.major}.{current.minor + 1}"
    requires_python = f">={selector},<{upper}"
    tool.initialize_contract(
        root,
        project_name="analytics-project",
        requires_python=requires_python,
        selector=selector,
    )
    return requires_python, selector


def write_contract(root: Path, requires_python: str, selector: str | None) -> None:
    root.joinpath("pyproject.toml").write_text(
        (
            "[project]\n"
            'name = "analytics-project"\n'
            'version = "0.1.0"\n'
            f'requires-python = "{requires_python}"\n'
        ),
        encoding="utf-8",
    )
    if selector is not None:
        root.joinpath(".python-version").write_text(f"{selector}\n", encoding="utf-8")


class PythonVersionContractTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = load_tool()

    def test_generated_contract_matches_current_interpreter(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            requires_python, selector = current_contract(self.tool, root)
            report = self.tool.evaluate_project(root)

        self.assertTrue(report["ready"])
        self.assertEqual(report["requires_python"], requires_python)
        self.assertEqual(report["selector"], selector)
        self.assertEqual(report["runtime"]["executable"], sys.executable)

    def test_candidate_matrix_marks_range_boundaries(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_contract(root, ">=3.11,<3.13", "3.11")
            report = self.tool.evaluate_project(
                root,
                candidates=["3.10.14", "3.11.9", "3.12.4", "3.13.0"],
                current_version=self.tool.Version.parse("3.11.9"),
                executable="/example/python",
            )

        matrix = {
            item["version"]: item["compatible"]
            for item in report["matrix"]
        }
        self.assertEqual(
            matrix,
            {
                "3.10.14": False,
                "3.11.9": True,
                "3.12.4": True,
                "3.13.0": False,
            },
        )

    def test_runtime_outside_range_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_contract(root, ">=3.11,<3.13", "3.11")
            report = self.tool.evaluate_project(
                root,
                current_version=self.tool.Version.parse("3.10.14"),
                executable="/example/python",
            )

        runtime = next(item for item in report["checks"] if item["id"] == "runtime")
        self.assertFalse(runtime["passed"])
        self.assertFalse(report["ready"])

    def test_selector_outside_supported_range_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_contract(root, ">=3.11,<3.13", "3.13")
            report = self.tool.evaluate_project(
                root,
                current_version=self.tool.Version.parse("3.13.1"),
                executable="/example/python",
            )

        selector = next(item for item in report["checks"] if item["id"] == "selector")
        self.assertFalse(selector["passed"])
        self.assertIn("outside", selector["message"])

    def test_compatible_and_wildcard_clauses_are_supported(self) -> None:
        compatible = self.tool.parse_specifier("~=3.11.2,!=3.11.5")
        wildcard = self.tool.parse_specifier("==3.12.*")

        self.assertTrue(
            self.tool.satisfies(self.tool.Version.parse("3.11.9"), compatible)
        )
        self.assertFalse(
            self.tool.satisfies(self.tool.Version.parse("3.12.0"), compatible)
        )
        self.assertTrue(
            self.tool.satisfies(self.tool.Version.parse("3.12.7"), wildcard)
        )

    def test_missing_selector_and_invalid_spec_are_reported(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            write_contract(root, "Python 3.11 or newer", None)
            report = self.tool.evaluate_project(
                root,
                current_version=self.tool.Version.parse("3.11.9"),
                executable="/example/python",
            )
            markdown = self.tool.render_markdown(report)

        requires = next(
            item for item in report["checks"] if item["id"] == "requires-python"
        )
        selector = next(item for item in report["checks"] if item["id"] == "selector")
        self.assertFalse(requires["passed"])
        self.assertFalse(selector["passed"])
        self.assertIn(".python-version is missing", markdown)
