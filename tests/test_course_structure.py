from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from course_model import load_curriculum  # noqa: E402
from render_curriculum import render_phase_readme, render_roadmap  # noqa: E402
from render_outputs import build_output_index, render_output_index  # noqa: E402
from render_site import SITE_URL, build_site_data, build_site_outputs  # noqa: E402
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

    def test_extended_phases_document_scale_exception(self) -> None:
        for phase in load_curriculum()["phases"]:
            actual_hours = sum(
                lesson["time_minutes"] for lesson in phase["lessons"]
            ) / 60
            if phase["number"] not in {0, 18} and actual_hours > 18:
                self.assertTrue(
                    phase.get("scale_exception"),
                    f"phase {phase['number']:02d} has {actual_hours:g} hours",
                )

    def test_roadmap_is_up_to_date(self) -> None:
        expected = render_roadmap(load_curriculum())
        self.assertEqual((ROOT / "ROADMAP.md").read_text(encoding="utf-8"), expected)

    def test_output_index_is_up_to_date(self) -> None:
        expected = render_output_index(build_output_index(load_curriculum(), ROOT))
        self.assertEqual((ROOT / "outputs" / "index.json").read_text(encoding="utf-8"), expected)

    def test_generated_site_files_are_up_to_date(self) -> None:
        for path, expected in build_site_outputs(load_curriculum(), ROOT).items():
            self.assertEqual(path.read_text(encoding="utf-8"), expected, path.name)

    def test_completed_lessons_have_local_site_pages(self) -> None:
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
            self.assertTrue(lesson["site_url"].startswith("lessons/"))
            self.assertTrue((ROOT / "site" / lesson["site_url"] / "index.html").is_file())
            self.assertTrue((ROOT / lesson["path"] / "docs" / "ru.md").is_file())

    def test_static_site_entrypoints_exist(self) -> None:
        for relative in (
            "site/index.html",
            "site/catalog.html",
            "site/routes.html",
            "site/glossary.html",
            "site/404.html",
            "site/favicon.svg",
            "site/robots.txt",
            "site/sitemap.xml",
            "site/style.css",
            "site/common.js",
            "site/app.js",
            "site/lesson.js",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_site_has_indexable_static_content(self) -> None:
        data = build_site_data(load_curriculum(), ROOT)
        catalog = (ROOT / "site" / "catalog.html").read_text(encoding="utf-8")
        routes = (ROOT / "site" / "routes.html").read_text(encoding="utf-8")
        glossary = (ROOT / "site" / "glossary.html").read_text(encoding="utf-8")
        self.assertEqual(catalog.count('<tr><td><span class="phase-chip">'), 201)
        self.assertEqual(routes.count('<article class="route-detail">'), len(data["routes"]))
        self.assertEqual(
            glossary.count('<article class="term-card">'),
            len(data["glossary"]),
        )

    def test_indexed_pages_have_unique_search_metadata(self) -> None:
        pages = {
            "index.html": SITE_URL,
            "catalog.html": SITE_URL + "catalog.html",
            "routes.html": SITE_URL + "routes.html",
            "glossary.html": SITE_URL + "glossary.html",
        }
        titles: set[str] = set()
        descriptions: set[str] = set()
        for filename, canonical in pages.items():
            html = (ROOT / "site" / filename).read_text(encoding="utf-8")
            title = re.search(r"<title>([^<]+)</title>", html)
            description = re.search(
                r'<meta name="description" content="([^"]+)">', html
            )
            self.assertIsNotNone(title, filename)
            self.assertIsNotNone(description, filename)
            self.assertIn(f'<link rel="canonical" href="{canonical}">', html)
            self.assertIn('<meta name="robots" content="index, follow', html)
            self.assertIn('<meta property="og:title"', html)
            self.assertIn(f'<meta property="og:url" content="{canonical}">', html)
            self.assertEqual(html.count("<h1>"), 1, filename)
            titles.add(title.group(1))
            descriptions.add(description.group(1))
        self.assertEqual(len(titles), len(pages))
        self.assertEqual(len(descriptions), len(pages))

    def test_homepage_structured_data_is_valid_json_ld(self) -> None:
        html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        match = re.search(
            r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        graph = payload["@graph"]
        self.assertEqual({item["@type"] for item in graph}, {"WebSite", "Course"})
        course = next(item for item in graph if item["@type"] == "Course")
        self.assertTrue(course["isAccessibleForFree"])
        self.assertEqual(course["inLanguage"], "ru")

    def test_sitemap_and_404_indexing_policy(self) -> None:
        sitemap = (ROOT / "site" / "sitemap.xml").read_text(encoding="utf-8")
        for suffix in ("", "catalog.html", "routes.html", "glossary.html"):
            self.assertIn(f"<loc>{SITE_URL}{suffix}</loc>", sitemap)
        data = build_site_data(load_curriculum(), ROOT)
        lesson_urls = [
            lesson["site_url"]
            for phase in data["phases"]
            for lesson in phase["lessons"]
        ]
        self.assertEqual(len(lesson_urls), 201)
        self.assertEqual(sitemap.count("<url>"), 4 + len(lesson_urls))
        for lesson_url in lesson_urls:
            self.assertIn(f"<loc>{SITE_URL}{lesson_url}</loc>", sitemap)
        robots = (ROOT / "site" / "robots.txt").read_text(encoding="utf-8")
        self.assertIn(f"Sitemap: {SITE_URL}sitemap.xml", robots)
        not_found = (ROOT / "site" / "404.html").read_text(encoding="utf-8")
        self.assertIn('<meta name="robots" content="noindex, follow">', not_found)

    def test_lesson_pages_embed_course_content_and_practice(self) -> None:
        data = build_site_data(load_curriculum(), ROOT)
        canonicals: set[str] = set()
        for phase in data["phases"]:
            for lesson in phase["lessons"]:
                page = ROOT / "site" / lesson["site_url"] / "index.html"
                html = page.read_text(encoding="utf-8")
                canonical = SITE_URL + lesson["site_url"]
                self.assertIn(f'<link rel="canonical" href="{canonical}">', html)
                self.assertIn('<article class="lesson-article">', html)
                self.assertIn('class="lesson-quiz" data-stage="pre"', html)
                self.assertIn('class="lesson-quiz" data-stage="post"', html)
                self.assertIn('class="lesson-files" id="lesson-files"', html)
                self.assertIn('src="../../../lesson.js"', html)
                self.assertIn('type="application/ld+json"', html)
                canonicals.add(canonical)
        self.assertEqual(len(canonicals), 201)

    def test_tracked_lesson_outputs_do_not_embed_home_paths(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "phases"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        home_path = re.compile(r"(?:/(?:Users|home)/[^/\s\"']+/|[A-Za-z]:\\\\Users\\\\)")
        offenders: list[str] = []
        for raw_relative in tracked:
            if not raw_relative:
                continue
            relative = raw_relative.decode("utf-8")
            if "/outputs/" not in relative:
                continue
            content = (ROOT / relative).read_bytes().decode("utf-8", errors="ignore")
            if home_path.search(content):
                offenders.append(relative)
        self.assertEqual(offenders, [])

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

    def test_root_environment_contract_is_locked(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
        workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")

        self.assertIn("altair>=6.2.1,<6.3", pyproject["project"]["dependencies"])
        self.assertIn("numpy>=2.4.6,<2.5", pyproject["project"]["dependencies"])
        self.assertIn("pandas>=3.0.3,<3.1", pyproject["project"]["dependencies"])
        self.assertIn("duckdb>=1.5.3,<1.6", pyproject["project"]["dependencies"])
        self.assertIn("beautifulsoup4>=4.14,<5", pyproject["project"]["dependencies"])
        self.assertIn("matplotlib>=3.11,<3.12", pyproject["project"]["dependencies"])
        self.assertIn("openpyxl>=3.1,<3.2", pyproject["project"]["dependencies"])
        self.assertIn("plotly>=6.8,<6.9", pyproject["project"]["dependencies"])
        self.assertIn("pyarrow>=24,<25", pyproject["project"]["dependencies"])
        self.assertIn("requests>=2.34,<3", pyproject["project"]["dependencies"])
        self.assertIn("scipy>=1.17,<1.18", pyproject["project"]["dependencies"])
        self.assertIn("seaborn>=0.13.2,<0.14", pyproject["project"]["dependencies"])
        self.assertIn("sqlalchemy>=2.0,<2.1", pyproject["project"]["dependencies"])
        self.assertIn("statsmodels>=0.14.6,<0.15", pyproject["project"]["dependencies"])
        self.assertIn("markdown-it-py>=4.0,<5", pyproject["project"]["dependencies"])
        self.assertIn("pyyaml>=6.0.3,<7", pyproject["dependency-groups"]["dev"])
        self.assertIn("pytest>=9.0.3,<10", pyproject["dependency-groups"]["dev"])
        self.assertIn("ruff>=0.15.17,<0.16", pyproject["dependency-groups"]["dev"])
        locked = {package["name"]: package["version"] for package in lock["package"]}
        self.assertEqual(locked["altair"], "6.2.1")
        self.assertEqual(locked["numpy"], "2.4.6")
        self.assertEqual(locked["pandas"], "3.0.3")
        self.assertEqual(locked["duckdb"], "1.5.3")
        self.assertEqual(locked["beautifulsoup4"], "4.15.0")
        self.assertEqual(locked["matplotlib"], "3.11.0")
        self.assertEqual(locked["openpyxl"], "3.1.5")
        self.assertEqual(locked["plotly"], "6.8.0")
        self.assertEqual(locked["pyarrow"], "24.0.0")
        self.assertEqual(locked["requests"], "2.34.2")
        self.assertEqual(locked["scipy"], "1.17.1")
        self.assertEqual(locked["seaborn"], "0.13.2")
        self.assertEqual(locked["sqlalchemy"], "2.0.50")
        self.assertEqual(locked["statsmodels"], "0.14.6")
        self.assertEqual(locked["markdown-it-py"], "4.2.0")
        self.assertEqual(locked["patsy"], "1.0.2")
        self.assertEqual(locked["pyyaml"], "6.0.3")
        self.assertEqual(locked["pytest"], "9.0.3")
        self.assertEqual(locked["ruff"], "0.15.17")
        self.assertIn("uv sync --locked --dev", workflow)
        self.assertIn("uv run --locked python scripts/run_lesson_tests.py", workflow)

    def test_phase_03_is_complete(self) -> None:
        phase = load_curriculum()["phases"][3]
        lessons = phase["lessons"]

        self.assertEqual(phase["slug"], "pandas")
        self.assertTrue(all(lesson["status"] == "complete" for lesson in lessons))
        self.assertEqual(sum(lesson["time_minutes"] for lesson in lessons), 990)
        self.assertEqual(
            sum(bool(lesson.get("integration_project")) for lesson in lessons),
            1,
        )

        previous = "02-numpy/09-numerical-precision"
        for index, lesson in enumerate(lessons, start=1):
            self.assertIn(lesson["type"], {"build", "learn", "case"})
            self.assertEqual(lesson["prerequisites"], [previous])
            self.assertTrue(lesson["outcome"])
            self.assertTrue(lesson["artifact"])
            previous = f"03-pandas/{index:02d}-{lesson['slug']}"

    def test_pandas_3_semantics_are_the_course_baseline(self) -> None:
        self.assertEqual(pd.__version__, "3.0.3")
        self.assertEqual(str(pd.Series(["paid", "pending"]).dtype), "str")

        orders = pd.DataFrame({"amount": [100, 200]})
        subset = orders[["amount"]]
        subset.loc[0, "amount"] = 999
        self.assertEqual(orders.loc[0, "amount"], 100)

    def test_phase_03_tiny_data_is_reproducible(self) -> None:
        data_root = ROOT / "phases" / "03-pandas" / "data"
        committed_root = data_root / "tiny"
        contract = json.loads((data_root / "contract.json").read_text(encoding="utf-8"))
        manifest = json.loads((committed_root / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(set(contract["tables"]), {"users", "orders", "order_items"})
        self.assertEqual(
            set(manifest["files"]),
            {"users.csv", "orders.csv", "order_items.csv"},
        )
        for table in contract["tables"].values():
            self.assertTrue(table["grain"])
            self.assertTrue(table["primary_key"])
            self.assertTrue(table["columns"])
            self.assertIn("known_defects", table)
            self.assertIn("generation_rules", table)
            self.assertIn("time_range", table)

        with TemporaryDirectory() as directory:
            generated_root = Path(directory) / "tiny"
            subprocess.run(
                [
                    sys.executable,
                    str(data_root / "generate_tiny.py"),
                    "--output",
                    str(generated_root),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            for filename, metadata in manifest["files"].items():
                committed = (committed_root / filename).read_bytes()
                generated = (generated_root / filename).read_bytes()
                self.assertEqual(generated, committed, filename)
                self.assertEqual(
                    hashlib.sha256(committed).hexdigest(),
                    metadata["sha256"],
                    filename,
                )

    def test_phase_04_is_complete(self) -> None:
        phase = load_curriculum()["phases"][4]
        lessons = phase["lessons"]

        self.assertEqual(phase["slug"], "sql-and-duckdb")
        self.assertTrue(all(lesson["status"] == "complete" for lesson in lessons))
        self.assertEqual(sum(lesson["time_minutes"] for lesson in lessons), 1050)
        self.assertEqual(
            sum(bool(lesson.get("integration_project")) for lesson in lessons),
            1,
        )

        previous = "03-pandas/11-export-and-handoff"
        for index, lesson in enumerate(lessons, start=1):
            self.assertIn(lesson["type"], {"build", "learn", "case"})
            self.assertEqual(lesson["prerequisites"], [previous])
            self.assertTrue(lesson["outcome"])
            self.assertTrue(lesson["artifact"])
            previous = f"04-sql-and-duckdb/{index:02d}-{lesson['slug']}"

    def test_duckdb_1_5_is_the_course_baseline(self) -> None:
        self.assertEqual(duckdb.__version__, "1.5.3")
        result = duckdb.sql(
            "SELECT count(*) FILTER (WHERE value IS NULL) FROM (VALUES (1), (NULL)) t(value)"
        ).fetchone()
        self.assertEqual(result, (1,))

    def test_phase_04_tiny_data_is_reproducible(self) -> None:
        data_root = ROOT / "phases" / "04-sql-and-duckdb" / "data"
        committed_root = data_root / "tiny"
        contract = json.loads((data_root / "contract.json").read_text(encoding="utf-8"))
        manifest = json.loads((committed_root / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(
            set(contract["tables"]),
            {"users", "orders", "order_items", "events"},
        )
        self.assertGreater(
            sum(contract["profiles"]["sample"]["default_rows"].values()),
            500_000,
        )
        self.assertFalse(contract["profiles"]["sample"]["tracked"])
        self.assertEqual(
            set(manifest["files"]),
            {"users.csv", "orders.csv", "order_items.csv", "events.csv"},
        )
        for table in contract["tables"].values():
            self.assertTrue(table["grain"])
            self.assertTrue(table["primary_key"])
            self.assertTrue(table["columns"])
            self.assertIn("known_defects", table)
            self.assertIn("generation_rules", table)
            self.assertIn("time_range", table)

        with TemporaryDirectory() as directory:
            generated_root = Path(directory) / "tiny"
            subprocess.run(
                [
                    sys.executable,
                    str(data_root / "generate_data.py"),
                    "--profile",
                    "tiny",
                    "--output",
                    str(generated_root),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            for filename, metadata in manifest["files"].items():
                committed = (committed_root / filename).read_bytes()
                generated = (generated_root / filename).read_bytes()
                self.assertEqual(generated, committed, filename)
                self.assertEqual(
                    hashlib.sha256(committed).hexdigest(),
                    metadata["sha256"],
                    filename,
                )

        users_path = committed_root / "users.csv"
        orders_path = committed_root / "orders.csv"
        relation_counts = duckdb.sql(
            """
            SELECT
                (SELECT count(*) FROM read_csv_auto(?)) AS users,
                (SELECT count(*) FROM read_csv_auto(?)) AS orders
            """,
            params=[str(users_path), str(orders_path)],
        ).fetchone()
        self.assertEqual(relation_counts, (8, 12))

    def test_phase_05_is_complete(self) -> None:
        phase = load_curriculum()["phases"][5]
        lessons = phase["lessons"]

        self.assertEqual(phase["slug"], "sources-and-formats")
        self.assertTrue(all(lesson["status"] == "complete" for lesson in lessons))
        self.assertEqual(sum(lesson["time_minutes"] for lesson in lessons), 840)
        self.assertEqual(
            sum(bool(lesson.get("integration_project")) for lesson in lessons),
            1,
        )

        previous = "04-sql-and-duckdb/12-sql-vs-dataframes"
        for index, lesson in enumerate(lessons, start=1):
            self.assertIn(lesson["type"], {"build", "learn", "case"})
            self.assertEqual(lesson["prerequisites"], [previous])
            self.assertTrue(lesson["outcome"])
            self.assertTrue(lesson["artifact"])
            previous = f"05-sources-and-formats/{index:02d}-{lesson['slug']}"

    def test_phase_05_tiny_data_is_reproducible(self) -> None:
        data_root = ROOT / "phases" / "05-sources-and-formats" / "data"
        committed_root = data_root / "tiny"
        manifest = json.loads((committed_root / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(len(manifest["files"]), 14)
        self.assertEqual(
            {metadata["kind"] for metadata in manifest["files"].values()},
            {"api-page", "csv", "html", "http-body", "json", "sqlite", "xlsx"},
        )
        for filename, metadata in manifest["files"].items():
            fixture = committed_root / filename
            self.assertTrue(fixture.is_file(), filename)
            self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), metadata["sha256"])

        for contract in (
            "contract.json",
            "db_contract.json",
            "excel_spec.json",
            "html_contract.json",
            "json_contract.json",
            "parquet_schema.json",
        ):
            self.assertIsInstance(
                json.loads((data_root / contract).read_text(encoding="utf-8")),
                dict,
                contract,
            )

        subprocess.run(
            [sys.executable, str(data_root / "generate_data.py"), "--check"],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_phase_06_is_complete(self) -> None:
        phase = load_curriculum()["phases"][6]
        lessons = phase["lessons"]

        self.assertEqual(phase["slug"], "eda-and-visualization")
        self.assertTrue(all(lesson["status"] == "complete" for lesson in lessons))
        self.assertEqual(sum(lesson["time_minutes"] for lesson in lessons), 930)
        self.assertEqual(
            sum(bool(lesson.get("integration_project")) for lesson in lessons),
            1,
        )

        previous = "05-sources-and-formats/11-caching-and-checksums"
        for index, lesson in enumerate(lessons, start=1):
            self.assertIn(lesson["type"], {"build", "learn", "case"})
            self.assertEqual(lesson["prerequisites"], [previous])
            self.assertTrue(lesson["outcome"])
            self.assertTrue(lesson["artifact"])
            previous = f"06-eda-and-visualization/{index:02d}-{lesson['slug']}"

    def test_phase_06_design_decisions_are_documented(self) -> None:
        design = (ROOT / "docs" / "phase-06-design.md").read_text(encoding="utf-8")

        for marker in (
            "user_journeys",
            "Matplotlib",
            "Seaborn",
            "Plotly",
            "Altair",
            "фазе 17",
            "Интеграционный мини-проект",
        ):
            self.assertIn(marker, design)

    def test_readme_course_counts_match_curriculum(self) -> None:
        curriculum = load_curriculum()
        phase_count = len(curriculum["phases"])
        lesson_count = sum(len(phase["lessons"]) for phase in curriculum["phases"])
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"phases-{phase_count}-", readme)
        self.assertIn(f"lessons-{lesson_count}-", readme)

    def test_site_uses_hosting_safe_relative_assets(self) -> None:
        site_root = ROOT / "site"
        for html_path in site_root.rglob("*.html"):
            html = html_path.read_text(encoding="utf-8")
            references = re.findall(r'(?:href|src)="([^"]+)"', html)
            for reference in references:
                if reference.startswith(("https://", "http://", "#", "data:")):
                    continue
                self.assertFalse(reference.startswith("/"), reference)
                local_path = reference.split("#", 1)[0].split("?", 1)[0]
                if local_path:
                    resolved = html_path.parent / local_path
                    self.assertTrue(
                        resolved.is_file() or (resolved / "index.html").is_file(),
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
        self.assertIn("phases/01-reproducible-project/02-uv-environments", roadmap)
        self.assertIn("phases/01-reproducible-project/03-pyproject", roadmap)
        self.assertIn("phases/01-reproducible-project/04-jupyter-kernels", roadmap)
        self.assertIn(
            "phases/01-reproducible-project/05-notebook-reproducibility",
            roadmap,
        )
        self.assertIn(
            "phases/01-reproducible-project/06-modules-and-scripts",
            roadmap,
        )
        self.assertIn("phases/01-reproducible-project/07-ruff", roadmap)
        self.assertIn("phases/01-reproducible-project/08-pytest", roadmap)
        self.assertIn(
            "phases/01-reproducible-project/09-continuous-integration",
            roadmap,
        )
        self.assertIn("phases/02-numpy/01-arrays", roadmap)
        self.assertIn("phases/02-numpy/02-shape-and-axes", roadmap)
        self.assertIn("phases/02-numpy/03-dtypes", roadmap)
        self.assertIn("phases/02-numpy/04-indexing-and-masks", roadmap)
        self.assertIn("phases/02-numpy/05-broadcasting", roadmap)
        self.assertIn("phases/02-numpy/06-aggregations", roadmap)
        self.assertIn("phases/02-numpy/07-random-simulations", roadmap)
        self.assertIn("phases/02-numpy/08-vectorization", roadmap)
        self.assertIn("phases/02-numpy/09-numerical-precision", roadmap)

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
