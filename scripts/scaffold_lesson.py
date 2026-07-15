from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from course_model import ROOT

LESSON_PATTERN = re.compile(r"^\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")


def scaffold(
    phase: str,
    lesson: str,
    title: str,
    root: Path = ROOT,
    practice_mode: str = "executable",
) -> Path:
    if not LESSON_PATTERN.fullmatch(lesson):
        raise ValueError("Lesson must match NN-kebab-case.")
    if practice_mode not in {"executable", "guided-artifact"}:
        raise ValueError(f"Unknown practice mode: {practice_mode}")
    phase_root = root / "phases" / phase
    if not phase_root.is_dir():
        raise ValueError(f"Unknown phase directory: {phase}")
    lesson_root = phase_root / lesson
    if lesson_root.exists():
        raise ValueError(f"Lesson already exists: {lesson_root.relative_to(root)}")

    directories = ["notebook", "docs", "outputs"]
    if practice_mode == "executable":
        directories.extend(["code", "tests"])
    for directory in directories:
        (lesson_root / directory).mkdir(parents=True, exist_ok=True)

    metadata = {
        "title": title,
        "type": "build",
        "tracks": [],
        "prerequisites": [],
        "time_minutes": 75,
        "outcome": "TODO",
        "artifact": {
            "name": "TODO",
            "type": "tool",
            "path": "outputs/TODO.md",
        },
    }
    if practice_mode == "guided-artifact":
        metadata["practice"] = {
            "mode": "guided-artifact",
            "path": "outputs/TODO.md",
            "verification": "outputs/TODO-rubric.md",
        }
    (lesson_root / "lesson.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (lesson_root / "docs" / "ru.md").write_text(
        f"# {title}\n\n> TODO: ключевая мысль урока.\n\n"
        "**Тип:** Build  \n**Треки:** TODO  \n**Пререквизиты:** TODO  \n"
        "**Время:** ~75 минут\n\n"
        "## Цели обучения\n\n- TODO\n\n"
        "## Проблема\n\nTODO\n\n"
        "## Концепция\n\nTODO\n\n"
        "## Соберите это\n\nTODO\n\n"
        "## Используйте это\n\nTODO\n\n"
        "## Сломайте это\n\nTODO\n\n"
        "## Проверьте это\n\nTODO\n\n"
        "## Поставьте результат\n\nTODO\n\n"
        "## Упражнения\n\n1. TODO\n2. TODO\n3. TODO\n\n"
        "## Ключевые термины\n\n"
        "| Термин | Распространенное заблуждение | "
        "Точное значение |\n"
        "|---|---|---|\n"
        "| TODO | TODO | TODO |\n\n"
        "## Дополнительное чтение\n\n"
        "- [Официальная документация](https://example.com/TODO) — "
        "TODO: что именно прочитать и зачем.\n"
        "- [Первичный источник](https://example.com/TODO) — "
        "TODO: какую концепцию или предположение "
        "он раскрывает.\n"
        "- [Практический разбор](https://example.com/TODO) — "
        "TODO: какой сценарий или failure mode "
        "он помогает освоить.\n",
        encoding="utf-8",
    )
    if practice_mode == "executable":
        (lesson_root / "code" / "main.py").write_text(
            'def main() -> None:\n    raise NotImplementedError("Implement the lesson")\n\n\n'
            'if __name__ == "__main__":\n    main()\n',
            encoding="utf-8",
        )
        (lesson_root / "tests" / "test_main.py").write_text(
            "from unittest import TestCase\n\n\n"
            "class LessonTest(TestCase):\n"
            "    def test_lesson_is_implemented(self) -> None:\n"
            '        self.fail("Replace with a real behavioral test")\n',
            encoding="utf-8",
        )
    quiz = {
        "questions": [
            {
                "id": "pre-1",
                "stage": "pre",
                "question": "TODO",
                "options": ["TODO A", "TODO B", "TODO C", "TODO D"],
                "correct": 1,
                "explanation": "TODO",
            },
            {
                "id": "pre-2",
                "stage": "pre",
                "question": "TODO",
                "options": ["TODO A", "TODO B", "TODO C", "TODO D"],
                "correct": 2,
                "explanation": "TODO",
            },
            {
                "id": "post-1",
                "stage": "post",
                "question": "TODO",
                "options": ["TODO A", "TODO B", "TODO C", "TODO D"],
                "correct": 3,
                "explanation": "TODO",
            },
            {
                "id": "post-2",
                "stage": "post",
                "question": "TODO",
                "options": ["TODO A", "TODO B", "TODO C", "TODO D"],
                "correct": 0,
                "explanation": "TODO",
            },
            {
                "id": "post-3",
                "stage": "post",
                "question": "TODO",
                "options": ["TODO A", "TODO B", "TODO C", "TODO D"],
                "correct": 0,
                "explanation": "TODO",
            },
        ]
    }
    (lesson_root / "quiz.json").write_text(
        json.dumps(quiz, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    artifact = {
        "name": "TODO",
        "type": "tool",
        "path": "outputs/TODO.md",
        "description": "TODO",
        "usage": "TODO",
    }
    (lesson_root / "outputs" / "artifact.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (lesson_root / "outputs" / "TODO.md").write_text("# TODO\n", encoding="utf-8")
    if practice_mode == "guided-artifact":
        (lesson_root / "outputs" / "TODO-rubric.md").write_text(
            "# TODO: rubric\n",
            encoding="utf-8",
        )
    (lesson_root / "notebook" / ".gitkeep").touch()
    return lesson_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a lesson from the course template")
    parser.add_argument("phase", help="Phase directory, for example 03-pandas")
    parser.add_argument("lesson", help="Lesson directory, for example 05-groupby")
    parser.add_argument("title")
    parser.add_argument(
        "--practice-mode",
        choices=("executable", "guided-artifact"),
        default="executable",
        help="How the lesson practice is verified.",
    )
    args = parser.parse_args()
    path = scaffold(
        args.phase,
        args.lesson,
        args.title,
        practice_mode=args.practice_mode,
    )
    print(f"Created {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
