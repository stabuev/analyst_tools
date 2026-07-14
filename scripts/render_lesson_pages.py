from __future__ import annotations

import base64
import json
import mimetypes
import re
from html import escape
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt

REPOSITORY_URL = "https://github.com/stabuev/analyst_tools"
BRANCH = "main"
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}
TEXT_PREVIEW_LIMIT = 160_000


def lesson_site_url(phase: dict, lesson: dict) -> str:
    return f"lessons/{phase['slug']}/{lesson['slug']}/"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zа-яё0-9]+", "-", value.lower(), flags=re.IGNORECASE)
    return slug.strip("-") or "section"


def extract_description(markdown: str, fallback: str, limit: int = 170) -> str:
    lines = markdown.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if re.match(r"^##\s+Проблема", line)),
        -1,
    )
    candidates = lines[start + 1 :] if start >= 0 else lines
    paragraph: list[str] = []
    for line in candidates:
        stripped = line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.startswith(("#", "```", "|", "- ", "* ", ">")):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    text = " ".join(paragraph) or fallback
    text = re.sub(r"!?\[([^]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


def _repo_relative(path: Path, root: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def render_markdown(
    markdown: str,
    *,
    source_path: Path,
    root: Path,
    source_to_site: dict[str, str],
) -> str:
    md = MarkdownIt("commonmark", {"html": True, "linkify": True}).enable("table")
    def render_link_open(tokens, index, options, env):
        token = tokens[index]
        href = token.attrGet("href") or ""
        parsed = urlsplit(href)
        if parsed.scheme in {"http", "https", "mailto"} or href.startswith("//"):
            token.attrSet("target", "_blank")
            token.attrSet("rel", "noopener")
            return md.renderer.renderToken(tokens, index, options, env)
        if href.startswith("#"):
            return md.renderer.renderToken(tokens, index, options, env)

        target = (source_path.parent / unquote(parsed.path)).resolve()
        relative = _repo_relative(target, root)
        replacement: str | None = None
        if relative in source_to_site:
            replacement = "../../../" + source_to_site[relative]
        elif relative == "ROADMAP.md":
            replacement = "../../../index.html#roadmap"
        elif relative == "glossary/terms.md":
            replacement = "../../../glossary.html"
        elif relative and any(
            part in {"code", "tests", "outputs"} for part in Path(relative).parts
        ):
            replacement = "#lesson-files"
        elif relative:
            replacement = f"{REPOSITORY_URL}/blob/{BRANCH}/{relative}"
            token.attrSet("target", "_blank")
            token.attrSet("rel", "noopener")
        if replacement:
            if parsed.fragment and not replacement.startswith("#"):
                replacement += "#" + parsed.fragment
            token.attrSet("href", replacement)
        return md.renderer.renderToken(tokens, index, options, env)

    def render_image(tokens, index, options, env):
        token = tokens[index]
        src = token.attrGet("src") or ""
        parsed = urlsplit(src)
        if parsed.scheme in {"http", "https"}:
            token.attrSet("loading", "lazy")
            token.attrSet("class", "lesson-figure")
            return md.renderer.renderToken(tokens, index, options, env)
        target = (source_path.parent / unquote(parsed.path)).resolve()
        relative = _repo_relative(target, root)
        if relative and target.is_file():
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            encoded = base64.b64encode(target.read_bytes()).decode("ascii")
            token.attrSet("src", f"data:{mime};base64,{encoded}")
        token.attrSet("loading", "lazy")
        token.attrSet("class", "lesson-figure")
        return md.renderer.renderToken(tokens, index, options, env)

    def render_fence(tokens, index, options, env):
        token = tokens[index]
        language = (token.info.strip().split() or [""])[0]
        class_name = f' class="language-{escape(language, quote=True)}"' if language else ""
        label = f'<span class="code-language">{escape(language)}</span>' if language else ""
        return (
            '<div class="code-block">'
            f"{label}<button class=\"copy-button\" type=\"button\">Копировать</button>"
            f"<pre><code{class_name}>{escape(token.content)}</code></pre></div>"
        )

    md.renderer.rules["link_open"] = render_link_open
    md.renderer.rules["image"] = render_image
    md.renderer.rules["fence"] = render_fence

    tokens = md.parse(markdown)
    used_ids: dict[str, int] = {}
    for index, token in enumerate(tokens[:-1]):
        if token.type != "heading_open" or tokens[index + 1].type != "inline":
            continue
        base = slugify(tokens[index + 1].content)
        used_ids[base] = used_ids.get(base, 0) + 1
        suffix = f"-{used_ids[base]}" if used_ids[base] > 1 else ""
        token.attrSet("id", base + suffix)
    return md.renderer.render(tokens, md.options, {})


def render_quiz(questions: list[dict], stage: str) -> str:
    selected = [question for question in questions if question["stage"] == stage]
    if not selected:
        return ""
    title = "Проверка перед уроком" if stage == "pre" else "Проверьте себя"
    intro = (
        "Ответьте до чтения: результат поможет заметить исходные предположения."
        if stage == "pre"
        else "Ответьте после практики. Объяснение появится сразу после выбора."
    )
    cards: list[str] = []
    for number, question in enumerate(selected, start=1):
        options = "".join(
            f'<button type="button" class="quiz-option" data-choice="{index}">'
            f"{escape(option)}</button>"
            for index, option in enumerate(question["options"])
        )
        cards.append(
            f'<article class="quiz-question" data-correct="{question["correct"]}">'
            f'<p class="quiz-number">{number:02d}</p>'
            f'<h3>{escape(question["question"])}</h3>'
            f'<div class="quiz-options">{options}</div>'
            f'<p class="quiz-feedback" hidden>{escape(question["explanation"])}</p>'
            "</article>"
        )
    return (
        f'<section class="lesson-quiz" data-stage="{stage}">'
        f'<p class="eyebrow">Quiz · {len(selected)} вопроса</p>'
        f"<h2>{title}</h2><p>{intro}</p>{''.join(cards)}</section>"
    )


def _lesson_files(lesson_root: Path, folder: str) -> list[Path]:
    base = lesson_root / folder
    if not base.is_dir():
        return []
    return sorted(
        path
        for path in base.rglob("*")
        if path.is_file()
        and not any(part in SKIP_PARTS for part in path.parts)
        and path.suffix not in {".pyc", ".pyo"}
        and path.name not in {".DS_Store"}
    )


def render_file(path: Path, lesson_root: Path, source_url: str) -> str:
    relative = path.relative_to(lesson_root).as_posix()
    raw = path.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(raw).decode("ascii")
        preview = ""
        if mime.startswith("image/"):
            preview = (
                f'<img class="artifact-preview" src="data:{mime};base64,{encoded}" '
                f'alt="{escape(path.name, quote=True)}">'
            )
        return (
            '<article class="binary-file">'
            f"<h4>{escape(relative)}</h4>{preview}"
            f'<a class="text-link" download="{escape(path.name, quote=True)}" '
            f'href="data:{mime};base64,{encoded}">Скачать файл · {len(raw) // 1024 + 1} КБ</a>'
            "</article>"
        )

    content = content.replace("\r\n", "\n").replace("\r", "\n")
    truncated = len(content) > TEXT_PREVIEW_LIMIT
    shown = content[:TEXT_PREVIEW_LIMIT]
    note = (
        '<p class="file-note">Предпросмотр сокращён. Полная версия доступна в исходниках.</p>'
        if truncated
        else ""
    )
    source_path = quote(relative, safe="/")
    return (
        '<details class="source-file">'
        f"<summary><span>{escape(relative)}</span><span>Показать</span></summary>{note}"
        '<div class="code-block file-code">'
        '<button class="copy-button" type="button">Копировать</button>'
        f"<pre><code>{escape(shown)}</code></pre></div>"
        f'<a class="file-source-link" href="{source_url}/{source_path}" '
        'target="_blank" rel="noopener">Файл в репозитории</a>'
        "</details>"
    )


def render_lesson_files(lesson_root: Path, repository_path: str) -> str:
    groups = (
        ("tests", "Тесты — это техническое задание"),
        ("code", "Эталонный код"),
        ("outputs", "Артефакт и результаты"),
    )
    sections: list[str] = []
    source_url = f"{REPOSITORY_URL}/blob/{BRANCH}/{repository_path}"
    for folder, title in groups:
        files = _lesson_files(lesson_root, folder)
        if not files:
            continue
        rendered = "".join(render_file(path, lesson_root, source_url) for path in files)
        sections.append(
            f'<section class="lesson-files-group"><h3>{title}</h3>{rendered}</section>'
        )
    return (
        '<section class="lesson-files" id="lesson-files">'
        '<p class="eyebrow">Практика без перехода на GitHub</p>'
        '<h2>Файлы урока</h2>'
        '<p>Тесты, reference-код и артефакты встроены в страницу. Сначала попробуйте '
        "решить задачу самостоятельно, затем раскройте нужный файл и сравните подход.</p>"
        f"{''.join(sections)}</section>"
    )


def render_sidebar(phase: dict, current: dict) -> str:
    links = []
    for lesson in phase["lessons"]:
        active = lesson["slug"] == current["slug"]
        links.append(
            f'<a class="lesson-sidebar-link{" is-active" if active else ""}" '
            f'href="../../../{lesson["site_url"]}">'
            f'<span>{lesson["number"]:02d}</span>{escape(lesson["title"])}</a>'
        )
    return (
        '<aside class="lesson-sidebar">'
        f'<p class="eyebrow">Фаза {phase["number"]:02d}</p>'
        f'<h2>{escape(phase["title"])}</h2>'
        f'<nav aria-label="Уроки фазы">{"".join(links)}</nav></aside>'
    )


def json_ld(
    *,
    title: str,
    description: str,
    canonical: str,
    phase: dict,
    lesson: dict,
    site_url: str,
) -> str:
    payload = [
        {
            "@context": "https://schema.org",
            "@type": "LearningResource",
            "name": title,
            "description": description,
            "url": canonical,
            "inLanguage": "ru",
            "learningResourceType": "Lesson",
            "timeRequired": f"PT{lesson['time_minutes']}M",
            "isAccessibleForFree": True,
            "isPartOf": {
                "@type": "Course",
                "name": "Инструменты аналитика",
                "url": site_url,
            },
        },
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "Инструменты аналитика",
                    "item": site_url,
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": f"Фаза {phase['number']:02d}: {phase['title']}",
                    "item": site_url + f"catalog.html?phase={phase['number']}",
                },
                {
                    "@type": "ListItem",
                    "position": 3,
                    "name": title,
                    "item": canonical,
                },
            ],
        },
    ]
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def fill_template(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    unresolved = re.findall(r"{{[A-Z_]+}}", template)
    if unresolved:
        raise ValueError(f"Unresolved lesson template variables: {unresolved}")
    return template


def build_lesson_page_outputs(
    data: dict,
    root: Path,
    site_url: str,
) -> dict[Path, str]:
    template = (root / "scripts" / "templates" / "lesson.html").read_text(
        encoding="utf-8"
    )
    flat: list[tuple[dict, dict]] = [
        (phase, lesson) for phase in data["phases"] for lesson in phase["lessons"]
    ]
    source_to_site = {
        f"{lesson['path']}/docs/ru.md": lesson["site_url"]
        for _, lesson in flat
    }
    outputs: dict[Path, str] = {}
    for index, (phase, lesson) in enumerate(flat):
        lesson_root = root / lesson["path"]
        source_path = lesson_root / "docs" / "ru.md"
        markdown = source_path.read_text(encoding="utf-8")
        quiz = json.loads((lesson_root / "quiz.json").read_text(encoding="utf-8"))
        description = extract_description(markdown, lesson["outcome"])
        canonical = site_url + lesson["site_url"]
        previous = flat[index - 1][1] if index else None
        next_lesson = flat[index + 1][1] if index + 1 < len(flat) else None
        previous_link = (
            f'<a class="lesson-nav-card" href="../../../{previous["site_url"]}">'
            f'<span>← Предыдущий урок</span><strong>{escape(previous["title"])}</strong></a>'
            if previous
            else "<span></span>"
        )
        next_link = (
            f'<a class="lesson-nav-card is-next" href="../../../{next_lesson["site_url"]}">'
            f'<span>Следующий урок →</span><strong>{escape(next_lesson["title"])}</strong></a>'
            if next_lesson
            else "<span></span>"
        )
        article = render_markdown(
            markdown,
            source_path=source_path,
            root=root,
            source_to_site=source_to_site,
        )
        page = fill_template(
            template,
            {
                "TITLE": escape(lesson["title"]),
                "PAGE_TITLE": escape(f"{lesson['title']} — Инструменты аналитика"),
                "DESCRIPTION": escape(description, quote=True),
                "CANONICAL": escape(canonical, quote=True),
                "JSON_LD": json_ld(
                    title=lesson["title"],
                    description=description,
                    canonical=canonical,
                    phase=phase,
                    lesson=lesson,
                    site_url=site_url,
                ),
                "SIDEBAR": render_sidebar(phase, lesson),
                "POSITION": str(index + 1),
                "TOTAL": str(len(flat)),
                "PHASE_NUMBER": f"{phase['number']:02d}",
                "PHASE_TITLE": escape(phase["title"]),
                "TIME": str(lesson["time_minutes"]),
                "PROGRESS_PATH": escape(lesson["path"], quote=True),
                "PRE_QUIZ": render_quiz(quiz["questions"], "pre"),
                "ARTICLE": article,
                "POST_QUIZ": render_quiz(quiz["questions"], "post"),
                "FILES": render_lesson_files(lesson_root, lesson["path"]),
                "PREVIOUS": previous_link,
                "NEXT": next_link,
                "SOURCE_URL": escape(lesson["url"], quote=True),
            },
        )
        output = root / "site" / lesson["site_url"] / "index.html"
        outputs[output] = page
    return outputs
