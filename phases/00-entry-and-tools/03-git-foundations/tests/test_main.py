from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = LESSON_ROOT / "outputs" / "git_history_check.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("git_history_check_test", CHECKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load git history checker")
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


def build_valid_repository(root: Path) -> None:
    initialize_repository(root)
    commit_files(
        root,
        {
            "README.md": "# Project\n",
            ".gitignore": ".venv/\n__pycache__/\n.env\ndata/raw/\n",
        },
        "Initialize analytics project",
    )
    commit_files(
        root,
        {"src/metric.py": "def metric() -> int:\n    return 1\n"},
        "Add metric calculation",
    )
    commit_files(
        root,
        {"docs/assumptions.md": "# Assumptions\n"},
        "Document metric assumptions",
    )


class GitHistoryCheckTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.checker = load_checker()

    def test_focused_clean_repository_passes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_repository(root)
            report = self.checker.evaluate_repository(root)

        self.assertTrue(report["ready"])
        self.assertEqual(len(report["history"]), 3)
        self.assertTrue(all(check["passed"] for check in report["checks"]))

    def test_dirty_working_tree_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_repository(root)
            (root / "README.md").write_text("# Changed\n", encoding="utf-8")
            report = self.checker.evaluate_repository(root)

        check = next(item for item in report["checks"] if item["id"] == "clean-tree")
        self.assertFalse(check["passed"])
        self.assertFalse(report["ready"])

    def test_tracked_file_stays_visible_after_it_is_ignored(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            commit_files(
                root,
                {
                    "README.md": "# Project\n",
                    ".gitignore": ".venv/\n",
                },
                "Initialize analytics project",
            )
            commit_files(
                root,
                {"data/raw/orders.csv": "order_id\n101\n"},
                "Add raw order sample",
            )
            commit_files(
                root,
                {".gitignore": ".venv/\ndata/raw/\n"},
                "Ignore raw data directory",
            )
            report = self.checker.evaluate_repository(root)

        check = next(
            item for item in report["checks"] if item["id"] == "tracked-ignored"
        )
        self.assertFalse(check["passed"])
        self.assertIn("data/raw/orders.csv", check["message"])

    def test_generic_subject_and_wide_commit_fail_policy(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            commit_files(
                root,
                {
                    "README.md": "# Project\n",
                    ".gitignore": ".venv/\n",
                },
                "Initialize analytics project",
            )
            commit_files(
                root,
                {"src/metric.py": "VALUE = 1\n"},
                "Add metric baseline",
            )
            files = {f"notes/note-{index}.md": "note\n" for index in range(5)}
            commit_files(root, files, "update")
            report = self.checker.evaluate_repository(
                root,
                max_files_per_commit=4,
            )

        subjects = next(item for item in report["checks"] if item["id"] == "subjects")
        focus = next(item for item in report["checks"] if item["id"] == "focus")
        self.assertFalse(subjects["passed"])
        self.assertFalse(focus["passed"])

    def test_markdown_report_contains_checks_and_history(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            build_valid_repository(root)
            markdown = self.checker.render_markdown(
                self.checker.evaluate_repository(root)
            )

        self.assertIn("**ready**", markdown)
        self.assertIn("`tracked-ignored`", markdown)
        self.assertIn("Document metric assumptions", markdown)
