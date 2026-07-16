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
    write_file(root, "README.md", "# Revenue project\n")
    commit(root, "Initialize revenue project", "README.md")
    git(root, "branch", "-M", "main")


def write_documents(root: Path) -> tuple[Path, Path]:
    body = root.parent / f"{root.name}-pull-request.md"
    body.write_text(
        (
            "## Задача\n\nДобавить число заказов в дневной отчёт по выручке.\n\n"
            "## Что изменено\n\nВ запрос и определение метрики добавлен счётчик заказов.\n\n"
            "## Как проверено\n\nПроверены полный diff ветки и ручной контрольный пример.\n\n"
            "## Ограничения\n\nРасчёт предполагает одну строку на заказ в источнике.\n"
        ),
        encoding="utf-8",
    )
    review = root.parent / f"{root.name}-review.md"
    review.write_text(
        (
            "## Решение\n\nRequest changes\n\n"
            "## Файл и строки\n\nreview_case.sql, SUM после соединения с товарами.\n\n"
            "## Наблюдение\n\nОдин заказ повторяется для каждой товарной позиции.\n\n"
            "## Риск\n\nВыручка завышается и становится зависимой от числа товаров.\n\n"
            "## Что исправить\n\nАгрегировать товары до одной строки на заказ до соединения.\n\n"
            "## Как проверить\n\nСверить выручку с независимой суммой таблицы заказов.\n"
        ),
        encoding="utf-8",
    )
    return body, review


def add_feature(root: Path) -> tuple[Path, Path]:
    git(root, "switch", "-q", "-c", "feature/paid-order-count")
    write_file(
        root,
        "queries/revenue_by_day.sql",
        "SELECT order_date, SUM(amount), COUNT(*) FROM orders GROUP BY order_date;\n",
    )
    commit(root, "Add paid order count", "queries/revenue_by_day.sql")
    return write_documents(root)


class PullRequestPacketTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packet = load_packet_builder()

    def test_complete_branch_description_and_review_pass(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body, review = add_feature(root)
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
                review_path=review,
            )

        self.assertTrue(report["ready"])
        self.assertEqual(report["head"], "feature/paid-order-count")
        self.assertEqual(report["review_decision"], "Request changes")
        self.assertIn("queries/revenue_by_day.sql", report["files"])

    def test_base_only_commit_is_not_in_proposed_diff(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body, review = add_feature(root)
            git(root, "switch", "-q", "main")
            write_file(root, "docs/base-only.md", "Base documentation\n")
            commit(root, "Update base documentation", "docs/base-only.md")
            git(root, "switch", "-q", "feature/paid-order-count")
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
                review_path=review,
            )

        self.assertTrue(report["ready"])
        self.assertGreater(report["behind"], 0)
        self.assertNotIn("docs/base-only.md", report["files"])

    def test_missing_pr_section_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body, review = add_feature(root)
            body.write_text(
                "## Задача\n\nДобавить число заказов в дневной отчёт по выручке.\n",
                encoding="utf-8",
            )
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
                review_path=review,
            )

        check = next(item for item in report["checks"] if item["id"] == "pr-description")
        self.assertFalse(check["passed"])
        self.assertIn("Как проверено", check["message"])

    def test_missing_review_section_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body, review = add_feature(root)
            review.write_text(
                (
                    "## Решение\n\nRequest changes\n\n"
                    "## Файл и строки\n\nreview_case.sql, строка с SUM после JOIN.\n"
                ),
                encoding="utf-8",
            )
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
                review_path=review,
            )

        check = next(item for item in report["checks"] if item["id"] == "review")
        self.assertFalse(check["passed"])
        self.assertIn("Риск", check["message"])

    def test_invalid_review_decision_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body, review = add_feature(root)
            content = review.read_text(encoding="utf-8")
            review.write_text(content.replace("Request changes", "Looks good"), encoding="utf-8")
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
                review_path=review,
            )

        check = next(item for item in report["checks"] if item["id"] == "review")
        self.assertFalse(check["passed"])
        self.assertIn("Comment, Approve", check["message"])

    def test_dirty_tree_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body, review = add_feature(root)
            write_file(root, "notes.txt", "uncommitted\n")
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
                review_path=review,
            )

        check = next(item for item in report["checks"] if item["id"] == "clean-tree")
        self.assertFalse(check["passed"])
        self.assertFalse(report["ready"])

    def test_markdown_contains_review_decision(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_repository(root)
            body, review = add_feature(root)
            report = self.packet.evaluate_pull_request(
                root,
                base="main",
                body_path=body,
                review_path=review,
            )
            markdown = self.packet.render_markdown(report)

        self.assertIn("Review decision: **Request changes**", markdown)
        self.assertIn("`queries/revenue_by_day.sql`", markdown)
