from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = LESSON_ROOT / "outputs" / "secure_project.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("secure_project_test", TOOL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load secure project tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def write_file(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def commit(root: Path, message: str, *paths: str, force: bool = False) -> None:
    arguments = ["add"]
    if force:
        arguments.append("-f")
    arguments.extend(["--", *paths])
    git(root, *arguments)
    git(root, "commit", "-q", "-m", message)


def initialize_repository(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Course Student")
    git(root, "config", "user.email", "student@example.com")


def build_valid_project(root: Path, tool) -> None:
    initialize_repository(root)
    tool.initialize_template(
        root,
        owner="analytics-team",
        required_environment=["WAREHOUSE_DSN", "ANALYTICS_API_TOKEN"],
    )
    write_file(root, "README.md", "# Analytics project\n")
    write_file(root, "data/sample/orders.csv", "order_id,amount\n101,120\n")
    commit(
        root,
        "Add secure project template",
        ".gitignore",
        ".env.example",
        "config/security-policy.json",
        "src/settings.py",
        "README.md",
        "data/sample/orders.csv",
    )


class SecureProjectTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = load_tool()

    def test_generated_template_passes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_project(root, self.tool)
            report = self.tool.evaluate_project(root)

        self.assertTrue(report["ready"])
        self.assertTrue(all(check["passed"] for check in report["checks"]))
        self.assertEqual(
            report["required_environment"],
            ["WAREHOUSE_DSN", "ANALYTICS_API_TOKEN"],
        )

    def test_local_env_is_ignored_but_example_is_tracked(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_project(root, self.tool)
            write_file(root, ".env", "WAREHOUSE_DSN=local-demo-value\n")

            self.assertTrue(self.tool.is_ignored(root, ".env"))
            self.assertFalse(self.tool.is_ignored(root, ".env.example"))
            self.assertNotIn(".env", self.tool.tracked_files(root))
            self.assertIn(".env.example", self.tool.tracked_files(root))

    def test_tracked_env_fails_even_after_ignore_rule_exists(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_project(root, self.tool)
            write_file(root, ".env", "WAREHOUSE_DSN=local-demo-value\n")
            commit(root, "Accidentally track local env", ".env", force=True)
            report = self.tool.evaluate_project(root)

        check = next(
            item for item in report["checks"] if item["id"] == "tracked-sensitive"
        )
        self.assertFalse(check["passed"])
        self.assertIn(".env", check["message"])

    def test_hardcoded_secret_reports_location_without_value(self) -> None:
        secret_value = "-".join(("course", "secret", "value", "12345"))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_project(root, self.tool)
            write_file(root, "src/job.py", f'API_TOKEN = "{secret_value}"\n')
            commit(root, "Add unsafe token", "src/job.py")
            report = self.tool.evaluate_project(root)
            markdown = self.tool.render_markdown(report)
            serialized = json.dumps(report)

        check = next(
            item for item in report["checks"] if item["id"] == "hardcoded-secrets"
        )
        self.assertFalse(check["passed"])
        self.assertIn("src/job.py:1", markdown)
        self.assertNotIn(secret_value, markdown)
        self.assertNotIn(secret_value, serialized)

    def test_restricted_data_fails_policy_even_when_forced_into_git(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_project(root, self.tool)
            write_file(root, "data/raw/customers.csv", "customer_id,email\n1,user@example.com\n")
            commit(
                root,
                "Accidentally add restricted extract",
                "data/raw/customers.csv",
                force=True,
            )
            report = self.tool.evaluate_project(root)

        check = next(item for item in report["checks"] if item["id"] == "data-policy")
        self.assertFalse(check["passed"])
        self.assertIn("data/raw/customers.csv", check["message"])

    def test_missing_required_variable_fails_example_contract(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_project(root, self.tool)
            write_file(root, ".env.example", "WAREHOUSE_DSN=\n")
            commit(root, "Break environment contract", ".env.example")
            report = self.tool.evaluate_project(root)

        check = next(item for item in report["checks"] if item["id"] == "env-example")
        self.assertFalse(check["passed"])
        self.assertIn("ANALYTICS_API_TOKEN", check["message"])

    def test_extra_filled_variable_fails_without_exposing_value(self) -> None:
        example_value = "-".join(("local", "demo", "value", "12345"))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_project(root, self.tool)
            write_file(
                root,
                ".env.example",
                (
                    "WAREHOUSE_DSN=\n"
                    "ANALYTICS_API_TOKEN=\n"
                    f"UNDECLARED_TOKEN={example_value}\n"
                ),
            )
            commit(root, "Add unsafe example value", ".env.example")
            report = self.tool.evaluate_project(root)
            markdown = self.tool.render_markdown(report)

        check = next(item for item in report["checks"] if item["id"] == "env-example")
        self.assertFalse(check["passed"])
        self.assertIn("UNDECLARED_TOKEN", check["message"])
        self.assertNotIn(example_value, markdown)
