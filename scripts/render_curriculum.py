from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from course_model import ROOT, lesson_dir_name, load_curriculum, phase_dir_name


GENERATED_NOTICE = "<!-- Generated from curriculum.json. Do not edit manually. -->"


def render_routes(curriculum: dict[str, Any]) -> list[str]:
    lines = ["## Маршруты", ""]
    phase_map = {phase["number"]: phase for phase in curriculum["phases"]}
    for route in curriculum["routes"]:
        phases = [phase_map[number] for number in route["phase_numbers"]]
        minimum = sum(phase["hours"]["min"] for phase in phases)
        maximum = sum(phase["hours"]["max"] for phase in phases)
        lines.append(
            f"- **{route['name']}**: `{route['path']}` (~{minimum}-{maximum} часов)"
        )
    return lines


def render_roadmap(curriculum: dict[str, Any]) -> str:
    course = curriculum["course"]
    lines = [
        GENERATED_NOTICE,
        "",
        f"# Дорожная карта: {course['title']}",
        "",
        (
            f"**Версия:** {course['version']}  \n"
            f"**Полный маршрут:** ~{course['hours']['min']}-{course['hours']['max']} часов"
        ),
        "",
        "## Обзор",
        "",
        "| Фаза | Название | Треки | Пререквизиты | Часы |",
        "|---:|---|---|---|---:|",
    ]

    for phase in curriculum["phases"]:
        number = phase["number"]
        directory = phase_dir_name(phase)
        tracks = ", ".join(phase["tracks"])
        prerequisites = ", ".join(f"{item:02d}" for item in phase["prerequisites"]) or "-"
        hours = f"{phase['hours']['min']}-{phase['hours']['max']}"
        lines.append(
            f"| {number:02d} | [{phase['title']}](phases/{directory}) | "
            f"{tracks} | {prerequisites} | {hours} |"
        )

    lines.extend(["", *render_routes(curriculum), "", "## Граф зависимостей", "", "```mermaid"])
    lines.extend(curriculum["dependency_graph"])
    lines.extend(["```", ""])

    for phase in curriculum["phases"]:
        directory = phase_dir_name(phase)
        tracks = ", ".join(phase["tracks"])
        prerequisites = ", ".join(f"Фаза {item:02d}" for item in phase["prerequisites"]) or "Нет"
        lines.extend(
            [
                f"## Фаза {phase['number']:02d}: {phase['title']}",
                "",
                f"- **Треки:** {tracks}",
                f"- **Пререквизиты:** {prerequisites}",
                f"- **Время:** ~{phase['hours']['min']}-{phase['hours']['max']} часов",
                f"- **Итоговый артефакт:** {phase['artifact']}",
                "",
                "| № | Урок | Статус |",
                "|---:|---|---|",
            ]
        )
        for index, lesson in enumerate(phase["lessons"], start=1):
            lesson_dir = lesson_dir_name(index, lesson)
            title = lesson["title"]
            if lesson.get("status") in {"draft", "complete"}:
                title = f"[{title}](phases/{directory}/{lesson_dir})"
            lines.append(f"| {index:02d} | {title} | {lesson.get('status', 'planned')} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_phase_readme(phase: dict[str, Any]) -> str:
    tracks = ", ".join(phase["tracks"])
    prerequisites = ", ".join(f"Фаза {item:02d}" for item in phase["prerequisites"]) or "Нет"
    lines = [
        GENERATED_NOTICE,
        "",
        f"# Фаза {phase['number']:02d}: {phase['title']}",
        "",
        f"> {phase['summary']}",
        "",
        f"- **Треки:** {tracks}",
        f"- **Пререквизиты:** {prerequisites}",
        f"- **Время:** ~{phase['hours']['min']}-{phase['hours']['max']} часов",
        f"- **Итоговый артефакт:** {phase['artifact']}",
        "",
    ]
    learning_guide = ROOT / "docs" / f"phase-{phase['number']:02d}-learning-guide.md"
    if learning_guide.is_file():
        lines.extend(
            [
                "## Учебный путеводитель",
                "",
                (
                    f"Перед уроками откройте [пошаговый путеводитель фазы]"
                    f"(../../docs/phase-{phase['number']:02d}-learning-guide.md). "
                    "Он связывает короткие уроки в один сквозной пример, показывает "
                    "ожидаемые промежуточные результаты и точки самопроверки."
                ),
                "",
            ]
        )
    lines.extend(["## Уроки", ""])
    detailed = all(
        {"time_minutes", "outcome", "artifact"} <= set(lesson) for lesson in phase["lessons"]
    )
    if detailed:
        lines.extend(
            [
                "| № | Урок | Время | Проверяемый результат | Артефакт | Статус |",
                "|---:|---|---:|---|---|---|",
            ]
        )
    else:
        lines.extend(["| № | Урок | Статус |", "|---:|---|---|"])
    for index, lesson in enumerate(phase["lessons"], start=1):
        directory = lesson_dir_name(index, lesson)
        title = lesson["title"]
        if lesson["status"] in {"draft", "complete"}:
            title = f"[{title}]({directory})"
        if detailed:
            lines.append(
                f"| {index:02d} | {title} | {lesson['time_minutes']} мин | "
                f"{lesson['outcome']} | {lesson['artifact']} | {lesson['status']} |"
            )
        else:
            lines.append(f"| {index:02d} | {title} | {lesson['status']} |")
    lines.extend(
        [
            "",
            "## Как проходить фазу",
            "",
            "1. Ответьте на входные вопросы до чтения reference implementation.",
            "2. Для каждого урока воспроизведите ручной механизм в локальной папке `work/`.",
            "3. Запустите пример, один failure mode и тесты урока.",
            "4. Выполните хотя бы одно упражнение, которое меняет данные или правило.",
            "5. После фазы пройдите перемешанную самопроверку:",
            "",
            "```bash",
            (
                "uv run --locked python scripts/run_quiz.py "
                f"--phase {phase['number']} --stage post --limit 8"
            ),
            "```",
            "",
            "Кнопка прогресса на сайте является ручной отметкой, а не сертификатом. "
            "Критерий освоения — объяснить решение, воспроизвести расчёт и диагностировать "
            "хотя бы одну поломку.",
            "",
            "## Критерий завершения",
            "",
            phase["completion"],
            "",
            "[Вернуться к общей дорожной карте](../../ROADMAP.md)",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_curriculum(root: Path = ROOT) -> None:
    curriculum = load_curriculum(root / "curriculum.json")
    (root / "ROADMAP.md").write_text(render_roadmap(curriculum), encoding="utf-8")
    phases_root = root / "phases"
    phases_root.mkdir(exist_ok=True)
    for phase in curriculum["phases"]:
        phase_root = phases_root / phase_dir_name(phase)
        phase_root.mkdir(exist_ok=True)
        (phase_root / "README.md").write_text(render_phase_readme(phase), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render roadmap and phase pages")
    parser.add_argument("--check", action="store_true", help="Fail when generated files differ")
    args = parser.parse_args()

    if not args.check:
        write_curriculum()
        print("Rendered ROADMAP.md and phase README files.")
        return

    curriculum = load_curriculum()
    mismatches: list[str] = []
    roadmap = ROOT / "ROADMAP.md"
    if not roadmap.exists() or roadmap.read_text(encoding="utf-8") != render_roadmap(curriculum):
        mismatches.append("ROADMAP.md")
    for phase in curriculum["phases"]:
        path = ROOT / "phases" / phase_dir_name(phase) / "README.md"
        if not path.exists() or path.read_text(encoding="utf-8") != render_phase_readme(phase):
            mismatches.append(str(path.relative_to(ROOT)))
    if mismatches:
        raise SystemExit("Generated files are stale: " + ", ".join(mismatches))
    print("Generated curriculum files are up to date.")


if __name__ == "__main__":
    main()
