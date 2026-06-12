from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from course_model import load_curriculum  # noqa: E402
from render_curriculum import render_phase_readme, render_roadmap  # noqa: E402
from render_outputs import build_output_index, render_output_index  # noqa: E402
from scaffold_lesson import scaffold  # noqa: E402
from validate_course import validate_complete_lesson, validate_curriculum  # noqa: E402


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

    def test_schema_files_are_valid_json(self) -> None:
        for path in (ROOT / "schemas").glob("*.json"):
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_phase_pages_are_up_to_date(self) -> None:
        curriculum = load_curriculum()
        for phase in curriculum["phases"]:
            directory = f"{phase['number']:02d}-{phase['slug']}"
            actual = (ROOT / "phases" / directory / "README.md").read_text(encoding="utf-8")
            self.assertEqual(actual, render_phase_readme(phase))

    def test_unwritten_lessons_do_not_create_broken_links(self) -> None:
        roadmap = render_roadmap(load_curriculum())
        self.assertNotIn("phases/00-entry-and-tools/02-python-and-sql-diagnostic", roadmap)

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
                "\n## Дополнительное чтение\n\nИсточник.\n"
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
