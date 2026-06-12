from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from course_model import ROOT, lesson_dir_name, load_curriculum, phase_dir_name


REPOSITORY_URL = "https://github.com/stabuev/analyst_tools"
BRANCH = "main"
SITE_DATA_PATH = ROOT / "site" / "data.js"


def parse_glossary(path: Path) -> list[dict[str, str]]:
    terms: list[dict[str, str]] = []
    current_term: str | None = None
    paragraphs: list[str] = []

    def flush() -> None:
        nonlocal current_term, paragraphs
        if current_term:
            terms.append(
                {
                    "term": current_term,
                    "definition": " ".join(paragraphs).strip(),
                }
            )
        current_term = None
        paragraphs = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            flush()
            current_term = line[3:].strip()
        elif current_term and line:
            paragraphs.append(line)
    flush()
    return terms


def phase_status(lessons: list[dict[str, Any]]) -> str:
    statuses = {lesson["status"] for lesson in lessons}
    if statuses == {"complete"}:
        return "complete"
    if statuses & {"complete", "draft"}:
        return "in-progress"
    if "designed" in statuses:
        return "designed"
    return "planned"


def build_site_data(
    curriculum: dict[str, Any],
    root: Path = ROOT,
) -> dict[str, Any]:
    phases: list[dict[str, Any]] = []
    complete_lessons = 0
    total_lessons = 0

    for phase in curriculum["phases"]:
        phase_directory = phase_dir_name(phase)
        lessons: list[dict[str, Any]] = []
        for index, lesson in enumerate(phase["lessons"], start=1):
            total_lessons += 1
            lesson_directory = lesson_dir_name(index, lesson)
            relative_path = f"phases/{phase_directory}/{lesson_directory}"
            lesson_root = root / relative_path
            metadata_path = lesson_root / "lesson.json"
            metadata: dict[str, Any] = {}
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

            available = lesson["status"] in {"draft", "complete"} and lesson_root.is_dir()
            if lesson["status"] == "complete":
                complete_lessons += 1

            entry = {
                "number": index,
                "slug": lesson["slug"],
                "title": lesson["title"],
                "status": lesson["status"],
                "time_minutes": lesson.get("time_minutes"),
                "outcome": lesson.get("outcome", ""),
                "artifact": lesson.get("artifact", ""),
                "type": metadata.get("type", ""),
                "tracks": metadata.get("tracks", phase["tracks"]),
                "path": relative_path,
                "available": available,
                "url": (
                    f"{REPOSITORY_URL}/tree/{BRANCH}/{relative_path}"
                    if available
                    else None
                ),
                "docs_url": (
                    f"{REPOSITORY_URL}/blob/{BRANCH}/{relative_path}/docs/ru.md"
                    if available and (lesson_root / "docs" / "ru.md").is_file()
                    else None
                ),
            }
            lessons.append(entry)

        phases.append(
            {
                "number": phase["number"],
                "slug": phase["slug"],
                "title": phase["title"],
                "summary": phase["summary"],
                "tracks": phase["tracks"],
                "prerequisites": phase["prerequisites"],
                "hours": phase["hours"],
                "artifact": phase["artifact"],
                "completion": phase["completion"],
                "status": phase_status(lessons),
                "url": f"{REPOSITORY_URL}/tree/{BRANCH}/phases/{phase_directory}",
                "lessons": lessons,
            }
        )

    phase_map = {phase["number"]: phase for phase in phases}
    routes: list[dict[str, Any]] = []
    for route in curriculum["routes"]:
        route_phases = [phase_map[number] for number in route["phase_numbers"]]
        routes.append(
            {
                **route,
                "hours": {
                    "min": sum(phase["hours"]["min"] for phase in route_phases),
                    "max": sum(phase["hours"]["max"] for phase in route_phases),
                },
                "phases": [
                    {
                        "number": phase["number"],
                        "title": phase["title"],
                        "status": phase["status"],
                    }
                    for phase in route_phases
                ],
            }
        )

    return {
        "course": curriculum["course"],
        "repository": {
            "url": REPOSITORY_URL,
            "branch": BRANCH,
            "issues_url": f"{REPOSITORY_URL}/issues/new",
        },
        "tracks": curriculum["tracks"],
        "routes": routes,
        "phases": phases,
        "glossary": parse_glossary(root / "glossary" / "terms.md"),
        "stats": {
            "phases": len(phases),
            "lessons": total_lessons,
            "complete_lessons": complete_lessons,
            "hours": curriculum["course"]["hours"],
        },
    }


def render_site_data(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    return (
        "// Generated by scripts/render_site.py. Do not edit manually.\n"
        f"window.COURSE_DATA = {payload};\n"
    )


def write_site_data(root: Path = ROOT) -> None:
    output = root / "site" / "data.js"
    output.parent.mkdir(exist_ok=True)
    curriculum = load_curriculum(root / "curriculum.json")
    output.write_text(
        render_site_data(build_site_data(curriculum, root)),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render static site data")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    expected = render_site_data(build_site_data(load_curriculum()))
    if args.check:
        if not SITE_DATA_PATH.is_file() or SITE_DATA_PATH.read_text(encoding="utf-8") != expected:
            raise SystemExit("site/data.js is stale.")
        print("Site data is up to date.")
        return

    write_site_data()
    print("Rendered site/data.js.")


if __name__ == "__main__":
    main()
