from __future__ import annotations

import argparse
import json
import re
from html import escape
from pathlib import Path
from typing import Any

from course_model import ROOT, lesson_dir_name, load_curriculum, phase_dir_name
from render_lesson_pages import build_lesson_page_outputs, lesson_site_url

REPOSITORY_URL = "https://github.com/stabuev/analyst_tools"
BRANCH = "main"
SITE_URL = "https://datascience.xyz/courses/analyst-tools/"
INDEXED_PAGES = ("", "catalog.html", "routes.html", "glossary.html")
STATUS_LABELS = {
    "complete": "Готов",
    "in-progress": "В работе",
    "designed": "Спроектирован",
    "draft": "Черновик",
    "planned": "Запланирован",
}


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
                "site_url": lesson_site_url(phase, lesson) if available else None,
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


def phase_number(number: int) -> str:
    return f"{number:02d}"


def render_catalog_rows(data: dict[str, Any]) -> str:
    rows: list[str] = []
    for phase in data["phases"]:
        for lesson in phase["lessons"]:
            link = lesson["site_url"]
            title = escape(lesson["title"])
            if link:
                title = f'<a href="{escape(link, quote=True)}">{title}</a>'
            source = "—"
            if lesson["url"]:
                source = (
                    f'<a class="text-link" href="{escape(lesson["url"], quote=True)}" '
                    'target="_blank" rel="noopener">Исходники</a>'
                )
            rows.append(
                "        <tr>"
                f'<td><span class="phase-chip">{phase_number(phase["number"])}</span></td>'
                f'<td class="catalog-title">{title}<small>{escape(lesson["outcome"])}</small></td>'
                f'<td>{lesson["time_minutes"] or "—"}</td>'
                f'<td>{escape(", ".join(lesson["tracks"]))}</td>'
                f'<td><span class="status-badge status-{lesson["status"]}">'
                f'{STATUS_LABELS.get(lesson["status"], lesson["status"])}</span></td>'
                f"<td>{source}</td>"
                "</tr>"
            )
    return "\n".join(rows)


def render_route_cards(data: dict[str, Any]) -> str:
    cards: list[str] = []
    for route in data["routes"]:
        phases: list[str] = []
        for index, phase in enumerate(route["phases"]):
            phases.append(
                f'<a class="route-phase status-{phase["status"]}" '
                f'href="index.html#phase-{phase_number(phase["number"])}">'
                f'<span>{phase_number(phase["number"])}</span>'
                f'<strong>{escape(phase["title"])}</strong></a>'
            )
            if index < len(route["phases"]) - 1:
                phases.append('<span class="route-arrow">→</span>')
        cards.append(
            '      <article class="route-detail">'
            '<div class="route-detail-head"><div><p class="eyebrow">'
            f'Профессиональный маршрут</p><h2>{escape(route["name"])}</h2></div>'
            f'<div class="route-detail-hours">{route["hours"]["min"]}–'
            f'{route["hours"]["max"]}<small>часов</small></div></div>'
            f'<p class="route-path">{escape(route["path"])}</p>'
            f'<div class="route-sequence">{"".join(phases)}</div></article>'
        )
    return "\n".join(cards)


def render_glossary_cards(data: dict[str, Any]) -> str:
    return "\n".join(
        '      <article class="term-card">'
        f'<h2>{escape(item["term"])}</h2><p>{escape(item["definition"])}</p></article>'
        for item in data["glossary"]
    )


def replace_generated_block(content: str, name: str, rendered: str) -> str:
    start = f"<!-- GENERATED:{name}:start -->"
    end = f"<!-- GENERATED:{name}:end -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
    replacement = f"{start}\n{rendered}\n{end}"
    updated, count = pattern.subn(replacement, content)
    if count != 1:
        raise ValueError(f"Expected one generated {name} block, found {count}.")
    return updated


def render_sitemap(data: dict[str, Any]) -> str:
    pages = list(INDEXED_PAGES)
    pages.extend(
        lesson["site_url"]
        for phase in data["phases"]
        for lesson in phase["lessons"]
        if lesson["site_url"]
    )
    urls = "\n".join(
        f"  <url><loc>{escape(SITE_URL + page)}</loc></url>" for page in pages
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )


def render_robots() -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}sitemap.xml\n"


def build_site_outputs(
    curriculum: dict[str, Any],
    root: Path = ROOT,
) -> dict[Path, str]:
    data = build_site_data(curriculum, root)
    site_root = root / "site"
    outputs = {
        site_root / "data.js": render_site_data(data),
        site_root / "sitemap.xml": render_sitemap(data),
        site_root / "robots.txt": render_robots(),
    }
    renderers = {
        "catalog.html": ("catalog", render_catalog_rows),
        "routes.html": ("routes", render_route_cards),
        "glossary.html": ("glossary", render_glossary_cards),
    }
    for filename, (name, renderer) in renderers.items():
        path = site_root / filename
        outputs[path] = replace_generated_block(
            path.read_text(encoding="utf-8"),
            name,
            renderer(data),
        )
    outputs.update(build_lesson_page_outputs(data, root, SITE_URL))
    return outputs


def write_site_data(root: Path = ROOT) -> None:
    for output, content in build_site_outputs(
        load_curriculum(root / "curriculum.json"), root
    ).items():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render static site data")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    expected = build_site_outputs(load_curriculum())
    if args.check:
        stale = [
            path.relative_to(ROOT)
            for path, content in expected.items()
            if not path.is_file() or path.read_text(encoding="utf-8") != content
        ]
        if stale:
            raise SystemExit(f"Generated site files are stale: {stale}")
        print("Site data and SEO files are up to date.")
        return

    write_site_data()
    print("Rendered site data, static content and SEO files.")


if __name__ == "__main__":
    main()
