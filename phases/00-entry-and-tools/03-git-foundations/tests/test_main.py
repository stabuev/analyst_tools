from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = LESSON_ROOT / "outputs" / "git_project_check.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("git_project_check_test", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load Git project checker")
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


def initialize_repository(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Course Student")
    git(root, "config", "user.email", "student@example.com")


def commit_files(root: Path, files: dict[str, str], message: str) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(root, "add", "--", *files)
    git(root, "commit", "-q", "-m", message)


def full_gitignore() -> str:
    return (
        ".venv/\n"
        "__pycache__/\n"
        "*.py[cod]\n"
        ".ipynb_checkpoints/\n"
        ".env\n"
        "data/raw/\n"
        "outputs/local/\n"
    )


def build_valid_repository(root: Path) -> None:
    initialize_repository(root)
    commit_files(
        root,
        {
            "README.md": "# Revenue project\n",
            ".gitignore": full_gitignore(),
        },
        "Initialize revenue project",
    )
    commit_files(
        root,
        {
            "queries/revenue.sql": "SELECT SUM(amount) FROM orders;\n",
            "docs/metric.md": "# Revenue\n",
        },
        "Add revenue calculation",
    )


class GitProjectCheckTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checker = load_checker()

    def test_clean_repository_with_basic_safety_passes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_repository(root)
            raw_extract = root / "data" / "raw" / "orders.csv"
            raw_extract.parent.mkdir(parents=True)
            raw_extract.write_text("order_id\n101\n", encoding="utf-8")
            report = self.checker.evaluate_repository(root)

        self.assertTrue(report["ready"])
        self.assertEqual(len(report["history"]), 2)
        self.assertTrue(all(check["passed"] for check in report["checks"]))

    def test_repository_with_one_commit_fails_history_check(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            commit_files(
                root,
                {"README.md": "# Project\n", ".gitignore": full_gitignore()},
                "Initialize project",
            )
            report = self.checker.evaluate_repository(root)

        check = next(item for item in report["checks"] if item["id"] == "history")
        self.assertFalse(check["passed"])
        self.assertFalse(report["ready"])

    def test_uncommitted_change_fails_clean_tree_check(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_repository(root)
            (root / "README.md").write_text("# Changed\n", encoding="utf-8")
            report = self.checker.evaluate_repository(root)

        check = next(item for item in report["checks"] if item["id"] == "clean-tree")
        self.assertFalse(check["passed"])
        self.assertFalse(report["ready"])

    def test_missing_local_output_rule_is_reported(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            incomplete_gitignore = ".env\ndata/raw/\n"
            commit_files(
                root,
                {"README.md": "# Project\n", ".gitignore": incomplete_gitignore},
                "Initialize project",
            )
            commit_files(root, {"query.sql": "SELECT 1;\n"}, "Add query")
            report = self.checker.evaluate_repository(root)

        check = next(item for item in report["checks"] if item["id"] == "ignore-rules")
        self.assertFalse(check["passed"])
        self.assertIn("outputs/local/report.html", check["message"])

    def test_tracked_env_is_reported_even_when_rule_exists(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            commit_files(
                root,
                {"README.md": "# Project\n", ".env": "TOKEN=example\n"},
                "Initialize unsafe project",
            )
            commit_files(
                root,
                {".gitignore": full_gitignore()},
                "Add ignore rules",
            )
            report = self.checker.evaluate_repository(root)

        check = next(
            item for item in report["checks"] if item["id"] == "protected-paths"
        )
        self.assertFalse(check["passed"])
        self.assertIn(".env", check["message"])

    def test_markdown_report_shows_checks_and_history(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_repository(root)
            markdown = self.checker.render_markdown(
                self.checker.evaluate_repository(root)
            )

        self.assertIn("**ready**", markdown)
        self.assertIn("`ignore-rules`", markdown)
        self.assertIn("Add revenue calculation", markdown)
