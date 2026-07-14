from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from course_model import ROOT, lesson_dir_name, load_curriculum, phase_dir_name
from render_outputs import build_output_index, render_output_index
from render_site import build_site_outputs

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LESSON_TYPES = {"build", "learn", "case"}
ARTIFACT_TYPES = {
    "function",
    "sql",
    "dbt-model",
    "data-contract",
    "test-suite",
    "report-template",
    "notebook",
    "cli",
    "app",
    "model-card",
    "prompt",
    "skill",
    "checklist",
    "workflow",
    "tool",
}
REQUIRED_HEADINGS = {
    "## Проблема",
    "## Концепция",
    "## Соберите это",
    "## Используйте это",
    "## Сломайте это",
    "## Проверьте это",
    "## Поставьте результат",
    "## Упражнения",
    "## Ключевые термины",
    "## Дополнительное чтение",
}
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def read_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        label = str(path.relative_to(ROOT))
    except ValueError:
        label = str(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"Invalid JSON in {label}: {error}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object.")
        return None
    return value


def contains_todo(value: Any) -> bool:
    if isinstance(value, str):
        return "TODO" in value.upper()
    if isinstance(value, dict):
        return any(contains_todo(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_todo(item) for item in value)
    return False


def validate_development_reading(
    docs: str,
    label: str,
    docs_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    heading = "## Дополнительное чтение"
    if heading not in docs:
        return [f"{label}: missing development reading section."]

    section = docs.split(heading, 1)[1]
    next_heading = re.search(r"^##\s+", section, flags=re.MULTILINE)
    if next_heading:
        section = section[: next_heading.start()]

    link_lines = [
        line.strip()
        for line in section.splitlines()
        if MARKDOWN_LINK_PATTERN.search(line)
    ]
    if len(link_lines) < 3:
        errors.append(f"{label}: development reading requires at least three links.")
    if len(link_lines) > 5:
        errors.append(f"{label}: development reading must contain at most five links.")

    external_links = 0
    for line in link_lines:
        match = MARKDOWN_LINK_PATTERN.search(line)
        if match is None:
            continue
        url = match.group(2).strip()
        annotation = line[match.end() :].strip().lstrip("-—:").strip()
        if len(annotation) < 12:
            errors.append(
                f"{label}: reading link '{match.group(1)}' needs a useful annotation."
            )
        if url.startswith("https://"):
            external_links += 1
        elif url.startswith("http://"):
            errors.append(f"{label}: reading link must use HTTPS: {url}")
        elif docs_path is not None:
            local_target = (docs_path.parent / url.split("#", 1)[0]).resolve()
            if not local_target.is_file():
                errors.append(f"{label}: reading link target does not exist: {url}")

    if external_links < 1:
        errors.append(
            f"{label}: development reading requires an external official or primary source."
        )
    return errors


def validate_quiz(quiz: dict[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    questions = quiz.get("questions")
    if not isinstance(questions, list):
        return [f"{label}: questions must be a list."]
    stages = {"pre": 0, "post": 0}
    ids: set[str] = set()
    for position, question in enumerate(questions, start=1):
        prefix = f"{label}: question {position}"
        if not isinstance(question, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        required = {"id", "stage", "question", "options", "correct", "explanation"}
        missing = required - set(question)
        if missing:
            errors.append(f"{prefix} misses fields: {sorted(missing)}")
            continue
        question_id = question["id"]
        if not isinstance(question_id, str) or not question_id:
            errors.append(f"{prefix} has invalid id.")
        elif question_id in ids:
            errors.append(f"{label}: duplicate question id {question_id}.")
        else:
            ids.add(question_id)
        stage = question["stage"]
        if stage not in stages:
            errors.append(f"{prefix} has invalid stage {stage}.")
        else:
            stages[stage] += 1
        options = question["options"]
        if not isinstance(options, list) or len(options) != 4:
            errors.append(f"{prefix} must have exactly four options.")
        elif any(not isinstance(option, str) or not option.strip() for option in options):
            errors.append(f"{prefix} options must be non-empty strings.")
        correct = question["correct"]
        if not isinstance(correct, int) or not 0 <= correct <= 3:
            errors.append(f"{prefix} has invalid correct answer index.")
        for field in ("question", "explanation"):
            if not isinstance(question[field], str) or not question[field].strip():
                errors.append(f"{prefix} has empty {field}.")
    if stages["pre"] < 2:
        errors.append(f"{label}: at least two pre questions are required.")
    if stages["post"] < 3:
        errors.append(f"{label}: at least three post questions are required.")
    return errors


def validate_complete_lesson(
    root: Path,
    phase: dict[str, Any],
    lesson: dict[str, Any],
    index: int,
) -> list[str]:
    errors: list[str] = []
    lesson_root = root / "phases" / phase_dir_name(phase) / lesson_dir_name(index, lesson)
    label = str(lesson_root.relative_to(root))
    required_files = (
        "code/main.py",
        "docs/ru.md",
        "tests/test_main.py",
        "outputs/artifact.json",
        "quiz.json",
        "lesson.json",
    )
    for relative in required_files:
        if not (lesson_root / relative).is_file():
            errors.append(f"{label}: missing {relative}.")
    if errors:
        return errors

    metadata = read_json(lesson_root / "lesson.json", errors)
    artifact = read_json(lesson_root / "outputs" / "artifact.json", errors)
    quiz = read_json(lesson_root / "quiz.json", errors)
    if metadata is None or artifact is None or quiz is None:
        return errors

    metadata_required = {
        "title",
        "type",
        "tracks",
        "prerequisites",
        "time_minutes",
        "outcome",
        "artifact",
    }
    missing_metadata = metadata_required - set(metadata)
    if missing_metadata:
        errors.append(f"{label}: lesson.json misses {sorted(missing_metadata)}.")
    if metadata.get("title") != lesson["title"]:
        errors.append(f"{label}: lesson title differs from curriculum.json.")
    if metadata.get("type") not in LESSON_TYPES:
        errors.append(f"{label}: invalid lesson type {metadata.get('type')}.")
    if not isinstance(metadata.get("tracks"), list) or not metadata["tracks"]:
        errors.append(f"{label}: lesson tracks must be a non-empty list.")
    if metadata.get("time_minutes") != lesson.get("time_minutes"):
        errors.append(f"{label}: lesson duration differs from curriculum.json.")
    if metadata.get("outcome") != lesson.get("outcome"):
        errors.append(f"{label}: lesson outcome differs from curriculum.json.")

    artifact_required = {"name", "type", "path", "description", "usage"}
    missing_artifact = artifact_required - set(artifact)
    if missing_artifact:
        errors.append(f"{label}: artifact.json misses {sorted(missing_artifact)}.")
    if artifact.get("type") not in ARTIFACT_TYPES:
        errors.append(f"{label}: invalid artifact type {artifact.get('type')}.")
    artifact_path = artifact.get("path")
    artifact_parts = Path(artifact_path).parts if isinstance(artifact_path, str) else ()
    if (
        not isinstance(artifact_path, str)
        or not artifact_parts
        or artifact_parts[0] != "outputs"
        or ".." in artifact_parts
    ):
        errors.append(f"{label}: artifact path must start with outputs/.")
    elif not (lesson_root / artifact_path).is_file():
        errors.append(f"{label}: artifact file does not exist: {artifact_path}.")
    if metadata.get("artifact") != {
        key: artifact.get(key) for key in ("name", "type", "path")
    }:
        errors.append(f"{label}: lesson and artifact manifests disagree.")

    errors.extend(validate_quiz(quiz, label))
    docs_path = lesson_root / "docs" / "ru.md"
    docs = docs_path.read_text(encoding="utf-8")
    code = (lesson_root / "code" / "main.py").read_text(encoding="utf-8")
    tests = (lesson_root / "tests" / "test_main.py").read_text(encoding="utf-8")
    missing_headings = sorted(REQUIRED_HEADINGS - set(docs.splitlines()))
    if missing_headings:
        errors.append(f"{label}: docs miss headings: {missing_headings}")
    errors.extend(validate_development_reading(docs, label, docs_path))
    if contains_todo(metadata) or contains_todo(artifact) or contains_todo(quiz) or "TODO" in docs:
        errors.append(f"{label}: completed lesson contains TODO placeholders.")
    if "NotImplementedError" in code or "self.fail(" in tests:
        errors.append(f"{label}: completed lesson contains scaffold placeholders.")
    if any("TODO" in path.name.upper() for path in lesson_root.rglob("*")):
        errors.append(f"{label}: completed lesson contains TODO-named files.")
    return errors


def validate_curriculum(curriculum: dict[str, Any], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    track_names = set(curriculum["tracks"])
    phases = curriculum["phases"]
    numbers = [phase["number"] for phase in phases]

    if numbers != list(range(len(phases))):
        errors.append("Phase numbers must be contiguous and start at 0.")

    total_min = sum(phase["hours"]["min"] for phase in phases)
    total_max = sum(phase["hours"]["max"] for phase in phases)
    course_hours = curriculum["course"]["hours"]
    if course_hours != {"min": total_min, "max": total_max}:
        errors.append(
            "Course hour range must equal the sum of phase ranges: "
            f"{total_min}-{total_max}."
        )

    for route in curriculum["routes"]:
        route_numbers = route.get("phase_numbers")
        if not isinstance(route_numbers, list) or not route_numbers:
            errors.append(f"Route {route.get('name')} must list phase_numbers.")
            continue
        if len(route_numbers) != len(set(route_numbers)):
            errors.append(f"Route {route['name']} contains duplicate phases.")
        missing_phases = set(route_numbers) - set(numbers)
        if missing_phases:
            errors.append(f"Route {route['name']} uses missing phases: {sorted(missing_phases)}")
            continue
        route_set = set(route_numbers)
        for number in route_numbers:
            missing_prerequisites = set(phases[number]["prerequisites"]) - route_set
            if missing_prerequisites:
                errors.append(
                    f"Route {route['name']} misses prerequisites "
                    f"{sorted(missing_prerequisites)} for phase {number:02d}."
                )

    phase_slugs: set[str] = set()
    for phase in phases:
        number = phase["number"]
        slug = phase["slug"]
        if not SLUG_PATTERN.fullmatch(slug):
            errors.append(f"Phase {number:02d} has invalid slug: {slug}")
        if slug in phase_slugs:
            errors.append(f"Duplicate phase slug: {slug}")
        phase_slugs.add(slug)

        unknown_tracks = set(phase["tracks"]) - track_names
        if unknown_tracks:
            errors.append(f"Phase {number:02d} uses unknown tracks: {sorted(unknown_tracks)}")

        for prerequisite in phase["prerequisites"]:
            if prerequisite not in numbers:
                errors.append(f"Phase {number:02d} references missing phase {prerequisite:02d}.")
            elif prerequisite >= number:
                errors.append(f"Phase {number:02d} prerequisite {prerequisite:02d} is not earlier.")

        if phase["hours"]["min"] <= 0 or phase["hours"]["max"] < phase["hours"]["min"]:
            errors.append(f"Phase {number:02d} has invalid hour range.")

        lesson_slugs: set[str] = set()
        for index, lesson in enumerate(phase["lessons"], start=1):
            lesson_slug = lesson["slug"]
            if not SLUG_PATTERN.fullmatch(lesson_slug):
                errors.append(f"Phase {number:02d} has invalid lesson slug: {lesson_slug}")
            if lesson_slug in lesson_slugs:
                errors.append(f"Phase {number:02d} has duplicate lesson slug: {lesson_slug}")
            lesson_slugs.add(lesson_slug)
            if lesson["status"] not in {"planned", "designed", "draft", "complete"}:
                errors.append(
                    f"Phase {number:02d} lesson {lesson_slug} has invalid status "
                    f"{lesson['status']}."
                )
            if lesson["status"] in {"designed", "draft", "complete"}:
                missing = {"time_minutes", "outcome", "artifact"} - set(lesson)
                if missing:
                    errors.append(
                        f"Phase {number:02d} lesson {lesson_slug} misses design fields: "
                        f"{sorted(missing)}"
                    )
                elif lesson["time_minutes"] <= 0:
                    errors.append(
                        f"Phase {number:02d} lesson {lesson_slug} has invalid duration."
                    )
            if lesson["status"] in {"draft", "complete"}:
                lesson_root = (
                    root
                    / "phases"
                    / phase_dir_name(phase)
                    / lesson_dir_name(index, lesson)
                )
                if not lesson_root.is_dir():
                    errors.append(
                        f"Phase {number:02d} lesson {lesson_slug} is {lesson['status']} "
                        "but its directory is missing."
                    )
            if lesson["status"] == "complete":
                errors.extend(validate_complete_lesson(root, phase, lesson, index))

        if all("time_minutes" in lesson for lesson in phase["lessons"]):
            lesson_hours = sum(lesson["time_minutes"] for lesson in phase["lessons"]) / 60
            if not phase["hours"]["min"] <= lesson_hours <= phase["hours"]["max"]:
                errors.append(
                    f"Phase {number:02d} lesson duration {lesson_hours:g}h is outside "
                    f"{phase['hours']['min']}-{phase['hours']['max']}h."
                )

        phase_readme = root / "phases" / phase_dir_name(phase) / "README.md"
        if not phase_readme.exists():
            errors.append(f"Missing phase page: {phase_readme.relative_to(root)}")

    if not (root / "ROADMAP.md").exists():
        errors.append("Missing ROADMAP.md.")
    required_project_paths = (
        "AGENTS.md",
        "README.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "CODE_OF_CONDUCT.md",
        "LICENSE",
        "LESSON_TEMPLATE.md",
        "pyproject.toml",
        "uv.lock",
        "docs/README.md",
        "docs/PROJECT_STATUS.md",
        "docs/research-baseline.md",
        "schemas/lesson.schema.json",
        "schemas/artifact.schema.json",
        "schemas/quiz.schema.json",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/new_lesson_proposal.md",
        ".github/workflows/pages.yml",
        ".agents/skills/find-your-level/SKILL.md",
        ".agents/skills/check-understanding/SKILL.md",
    )
    for relative in required_project_paths:
        if not (root / relative).is_file():
            errors.append(f"Missing project contract: {relative}")

    output_index = root / "outputs" / "index.json"
    if not output_index.is_file():
        errors.append("Missing outputs/index.json.")
    else:
        try:
            expected_output_index = render_output_index(build_output_index(curriculum, root))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"Cannot build output index: {error}")
        else:
            if output_index.read_text(encoding="utf-8") != expected_output_index:
                errors.append("outputs/index.json is stale.")

    try:
        expected_site_outputs = build_site_outputs(curriculum, root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"Cannot build site outputs: {error}")
    else:
        for path, expected in expected_site_outputs.items():
            if not path.is_file():
                errors.append(f"Missing generated site file: {path.relative_to(root)}.")
            elif path.read_text(encoding="utf-8") != expected:
                errors.append(f"Generated site file is stale: {path.relative_to(root)}.")
    return errors


def main() -> None:
    errors = validate_curriculum(load_curriculum())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("Course structure is valid.")


if __name__ == "__main__":
    main()
