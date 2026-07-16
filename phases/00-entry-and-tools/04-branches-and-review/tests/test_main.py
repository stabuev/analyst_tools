from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


LESSON_ROOT = Path(__file__).resolve().parents[1]
PACKET_PATH = LESSON_ROOT / "outputs" / "pr_review_packet.py"


def load_packet_builder():
    spec = importlib.util.spec_from_file_location("pr_review_packet_test", PACKET_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load pull request packet builder")
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


def commit(root: Path, message: str, *paths: str) -> None:
    git(root, "add", "--", *paths)
    git(root, "commit", "-q", "-m", message)


def initialize_repository(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "Course Student")
    git(root, "config", "user.email", "student@example.com")
    write_file(root, "README.md", "# Project\n")
    commit(root, "Initialize analytics project", "README.md")
    git(root, "branch", "-M", "main")


def valid_body(root: Path) -> Path:
    path = root.parent / f"{root.name}-PR.md"
    path.write_text(
        (
            "## Что изменено\n\n"
            "Добавлена проверка продуктовой метрики на контрольном примере.\n\n"
            "## Проверка\n\n"
            "Запущены unit tests и ручной расчет на небольшом наборе.\n\n"
            "## Решения и ограничения\n\n"
            "Расчет ожидает одну строку на пользователя и не исправляет grain.\n"
        ),
        encoding="utf-8",
    )
    return path


def add_feature(root: Path, filename: str = "src/metric.py") -> Path:
    git(root, "switch", "-q", "-c", "feature/metric-check")
    write_file(root, filename, "VALUE = 1\n")
    body = valid_body(root)
    commit(root, "Add metric validation", filename)
    return body


class PullRequestPacketTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packet = load_packet_builder()

    def test_feature_branch_with_complete_body_passes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body = add_feature(root)
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
            )

        self.assertTrue(report["ready"])
        self.assertEqual(report["head"], "feature/metric-check")
        self.assertIn("src/metric.py", report["files"])

    def test_base_only_commit_is_not_in_three_dot_diff(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body = add_feature(root)
            git(root, "switch", "-q", "main")
            write_file(root, "docs/base-only.md", "base\n")
            commit(root, "Update base documentation", "docs/base-only.md")
            git(root, "switch", "-q", "feature/metric-check")
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
            )

        self.assertTrue(report["ready"])
        self.assertGreater(report["behind"], 0)
        self.assertNotIn("docs/base-only.md", report["files"])
        self.assertIn("src/metric.py", report["files"])

    def test_missing_description_sections_fail(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body = add_feature(root)
            body.write_text(
                "## Что изменено\n\nКороткое описание изменения без остальных разделов.\n",
                encoding="utf-8",
            )
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
            )

        check = next(item for item in report["checks"] if item["id"] == "description")
        self.assertFalse(check["passed"])
        self.assertIn("Проверка", check["message"])

    def test_dirty_tree_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body = add_feature(root)
            write_file(root, "notes.txt", "uncommitted\n")
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
            )

        check = next(item for item in report["checks"] if item["id"] == "clean-tree")
        self.assertFalse(check["passed"])
        self.assertFalse(report["ready"])

    def test_sql_change_adds_analytical_review_questions(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body = add_feature(root, filename="models/orders.sql")
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
            )

        questions = " ".join(report["review_questions"])
        self.assertIn("grain", questions)
        self.assertIn("NULL", questions)
        markdown = self.packet.render_markdown(report)
        self.assertIn("## Review checklist", markdown)
        self.assertIn("`models/orders.sql`", markdown)
