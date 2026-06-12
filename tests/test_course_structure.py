from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from course_model import load_curriculum  # noqa: E402
from render_curriculum import render_phase_readme, render_roadmap  # noqa: E402
from render_outputs import build_output_index, render_output_index  # noqa: E402
from render_site import build_site_data, render_site_data  # noqa: E402
from scaffold_lesson import scaffold  # noqa: E402
from validate_course import (  # noqa: E402
    validate_complete_lesson,
    validate_curriculum,
    validate_development_reading,
)


class CourseStructureTest(TestCase):
    def test_curriculum_is_valid(self) -> None:
        self.assertEqual(validate_curriculum(load_curriculum(), ROOT), [])

    def test_course_hours_equal_phase_hours(self) -> None:
        curriculum = load_curriculum()
        self.assertEqual(
            curriculum["course"]["hours"],
            {
                "min": sum(phase["hours"]["min"] for phase in curriculum["phases"]),
                "max": sum(phase["hours"]["max"] for phase in curriculum["phases"]),
            },
        )

    def test_roadmap_is_up_to_date(self) -> None:
        expected = render_roadmap(load_curriculum())
        self.assertEqual((ROOT / "ROADMAP.md").read_text(encoding="utf-8"), expected)

    def test_output_index_is_up_to_date(self) -> None:
        expected = render_output_index(build_output_index(load_curriculum(), ROOT))
        self.assertEqual((ROOT / "outputs" / "index.json").read_text(encoding="utf-8"), expected)

    def test_site_data_is_up_to_date(self) -> None:
        expected = render_site_data(build_site_data(load_curriculum(), ROOT))
        self.assertEqual((ROOT / "site" / "data.js").read_text(encoding="utf-8"), expected)

    def test_completed_lessons_have_github_links_on_site(self) -> None:
        data = build_site_data(load_curriculum(), ROOT)
        completed = [
            lesson
            for phase in data["phases"]
            for lesson in phase["lessons"]
            if lesson["status"] == "complete"
        ]
        self.assertTrue(completed)
        for lesson in completed:
            self.assertTrue(lesson["available"])
            self.assertTrue(lesson["url"].startswith("https://github.com/stabuev/analyst_tools/"))
            self.assertTrue((ROOT / lesson["path"] / "docs" / "ru.md").is_file())

    def test_static_site_entrypoints_exist(self) -> None:
        for relative in (
            "site/index.html",
            "site/catalog.html",
            "site/routes.html",
            "site/glossary.html",
            "site/style.css",
            "site/common.js",
            "site/app.js",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_handoff_context_exists(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        status = (ROOT / "docs" / "PROJECT_STATUS.md").read_text(encoding="utf-8")
        baseline = (ROOT / "docs" / "research-baseline.md").read_text(encoding="utf-8")
        self.assertIn("docs/PROJECT_STATUS.md", agents)
        self.assertIn("curriculum.json", agents)
        self.assertIn("site/", agents)
        self.assertIn("Следующий содержательный шаг", status)
        self.assertIn("От tool-first к problem-first", baseline)

    def test_public_repository_documents_exist(self) -> None:
        expected_markers = {
            "README.md": "Участие в проекте",
            "CONTRIBUTING.md": "Pull request",
            "CHANGELOG.md": "[Unreleased]",
            "CODE_OF_CONDUCT.md": "Кодекс поведения",
            "docs/README.md": "Документация проекта",
            ".github/PULL_REQUEST_TEMPLATE.md": "Как проверить вручную",
            ".github/ISSUE_TEMPLATE/bug_report.md": "Как воспроизвести",
            ".github/ISSUE_TEMPLATE/new_lesson_proposal.md": "Рабочая проблема",
        }
        for relative, marker in expected_markers.items():
            content = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(marker, content, relative)

    def test_readme_course_counts_match_curriculum(self) -> None:
        curriculum = load_curriculum()
        phase_count = len(curriculum["phases"])
        lesson_count = sum(len(phase["lessons"]) for phase in curriculum["phases"])
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"phases-{phase_count}-", readme)
        self.assertIn(f"lessons-{lesson_count}-", readme)

    def test_site_uses_hosting_safe_relative_assets(self) -> None:
        site_root = ROOT / "site"
        for html_path in site_root.glob("*.html"):
            html = html_path.read_text(encoding="utf-8")
            references = re.findall(r'(?:href|src)="([^"]+)"', html)
            for reference in references:
                if reference.startswith(("https://", "http://", "#", "data:")):
                    continue
                self.assertFalse(reference.startswith("/"), reference)
                local_path = reference.split("#", 1)[0].split("?", 1)[0]
                if local_path:
                    self.assertTrue(
                        (site_root / local_path).is_file(),
                        f"{html_path.name}: missing {reference}",
                    )

    def test_schema_files_are_valid_json(self) -> None:
        for path in (ROOT / "schemas").glob("*.json"):
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_development_reading_contract(self) -> None:
        valid = (
            "## Дополнительное чтение\n\n"
            "- [Документация](https://example.com/docs) — "
            "прочитайте описание API и его ограничений.\n"
            "- [Концепция](concept.md) — "
            "разберите модель и основные предположения "
            "метода.\n"
            "- [Практика](practice.md) — "
            "перенесите подход на граничный рабочий "
            "сценарий.\n"
        )
        with TemporaryDirectory() as directory:
            docs_path = Path(directory) / "docs" / "ru.md"
            docs_path.parent.mkdir()
            docs_path.write_text(valid, encoding="utf-8")
            (docs_path.parent / "concept.md").write_text("Concept", encoding="utf-8")
            (docs_path.parent / "practice.md").write_text("Practice", encoding="utf-8")
            self.assertEqual(
                validate_development_reading(valid, "lesson", docs_path),
                [],
            )

    def test_development_reading_rejects_bare_link_list(self) -> None:
        docs = (
            "## Дополнительное чтение\n\n"
            "- [Одна](https://example.com/one)\n"
            "- [Две](https://example.com/two)\n"
        )
        errors = validate_development_reading(docs, "lesson")
        self.assertTrue(any("at least three" in error for error in errors))
        self.assertTrue(any("useful annotation" in error for error in errors))

    def test_phase_pages_are_up_to_date(self) -> None:
        curriculum = load_curriculum()
        for phase in curriculum["phases"]:
            directory = f"{phase['number']:02d}-{phase['slug']}"
            actual = (ROOT / "phases" / directory / "README.md").read_text(encoding="utf-8")
            self.assertEqual(actual, render_phase_readme(phase))

    def test_only_completed_lessons_create_links(self) -> None:
        roadmap = render_roadmap(load_curriculum())
        self.assertIn("phases/00-entry-and-tools/02-python-and-sql-diagnostic", roadmap)
        self.assertIn("phases/00-entry-and-tools/03-terminal-and-filesystem", roadmap)
        self.assertIn("phases/00-entry-and-tools/04-git-foundations", roadmap)
        self.assertIn("phases/00-entry-and-tools/05-branches-and-review", roadmap)
        self.assertIn("phases/00-entry-and-tools/06-secrets-and-sensitive-data", roadmap)
        self.assertIn("phases/01-reproducible-project/01-python-versions", roadmap)
        self.assertNotIn("phases/01-reproducible-project/02-uv-environments", roadmap)

    def test_lesson_scaffolder_creates_required_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "phases" / "00-example").mkdir(parents=True)
            lesson = scaffold("00-example", "01-first-lesson", "Первый урок", root)
            required = {
                "code/main.py",
                "docs/ru.md",
                "tests/test_main.py",
                "outputs/artifact.json",
                "outputs/TODO.md",
                "quiz.json",
                "lesson.json",
            }
            self.assertEqual(
                {str(path.relative_to(lesson)) for path in lesson.rglob("*") if path.is_file()}
                - {"notebook/.gitkeep"},
                required,
            )
            docs = (lesson / "docs" / "ru.md").read_text(encoding="utf-8")
            self.assertIn("## Дополнительное чтение", docs)
            self.assertEqual(docs.count("https://example.com/TODO"), 3)

    def test_complete_lesson_contract(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            phase = {"number": 0, "slug": "example"}
            lesson = {
                "slug": "first-lesson",
                "title": "Первый урок",
                "time_minutes": 75,
                "outcome": "Проверяет результат",
            }
            (root / "phases" / "00-example").mkdir(parents=True)
            lesson_root = scaffold(
                "00-example",
                "01-first-lesson",
                lesson["title"],
                root,
            )
            metadata = json.loads((lesson_root / "lesson.json").read_text(encoding="utf-8"))
            metadata.update(
                {
                    "tracks": ["core"],
                    "outcome": lesson["outcome"],
                    "artifact": {
                        "name": "checker",
                        "type": "tool",
                        "path": "outputs/checker.md",
                    },
                }
            )
            (lesson_root / "lesson.json").write_text(
                json.dumps(metadata, ensure_ascii=False),
                encoding="utf-8",
            )
            artifact = {
                "name": "checker",
                "type": "tool",
                "path": "outputs/checker.md",
                "description": "Проверяет результат",
                "usage": "Откройте outputs/checker.md",
            }
            (lesson_root / "outputs" / "artifact.json").write_text(
                json.dumps(artifact, ensure_ascii=False),
                encoding="utf-8",
            )
            (lesson_root / "outputs" / "checker.md").write_text(
                "# Checker\n",
                encoding="utf-8",
            )
            (lesson_root / "outputs" / "TODO.md").unlink()
            quiz = json.loads((lesson_root / "quiz.json").read_text(encoding="utf-8"))
            for question in quiz["questions"]:
                question["question"] = f"Вопрос {question['id']}"
                question["options"] = ["A", "B", "C", "D"]
                question["explanation"] = "Объяснение"
            (lesson_root / "quiz.json").write_text(
                json.dumps(quiz, ensure_ascii=False),
                encoding="utf-8",
            )
            docs = (lesson_root / "docs" / "ru.md").read_text(encoding="utf-8")
            docs = docs.replace("TODO", "Содержимое")
            docs += (
                "\n## Ключевые термины\n\nТермин.\n"
                "\n## Дополнительное чтение\n\n"
                "- [Документация](https://example.com/docs) — "
                "прочитайте контракт API и ограничения.\n"
                "- [Концепция](https://example.com/concept) — "
                "разберите модель и ее предположения.\n"
                "- [Практика](https://example.com/practice) — "
                "перенесите метод на граничный сценарий.\n"
            )
            (lesson_root / "docs" / "ru.md").write_text(docs, encoding="utf-8")
            (lesson_root / "code" / "main.py").write_text(
                "def main() -> None:\n    print('ok')\n",
                encoding="utf-8",
            )
            (lesson_root / "tests" / "test_main.py").write_text(
                "def test_ok() -> None:\n    assert True\n",
                encoding="utf-8",
            )
            self.assertEqual(validate_complete_lesson(root, phase, lesson, 1), [])

    def test_scaffold_cannot_pass_as_complete(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            phase = {"number": 0, "slug": "example"}
            lesson = {
                "slug": "first-lesson",
                "title": "Первый урок",
                "time_minutes": 75,
                "outcome": "Проверяет результат",
            }
            (root / "phases" / "00-example").mkdir(parents=True)
            scaffold("00-example", "01-first-lesson", lesson["title"], root)
            errors = validate_complete_lesson(root, phase, lesson, 1)
            self.assertTrue(errors)
            self.assertTrue(any("TODO" in error or "placeholder" in error for error in errors))
