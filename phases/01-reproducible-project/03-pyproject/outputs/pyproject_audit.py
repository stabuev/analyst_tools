from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any


NAME_PATTERN = re.compile(r"^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$")
VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+){1,2}(?:[A-Za-z0-9.-]+)?$")
REQUIRES_PYTHON_PATTERN = re.compile(r"[<>=!~]\s*\d+\.\d+")
SCRIPT_TARGET_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$"
)
DEPENDENCY_NAME_PATTERN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
DEV_TOOLS = {"pytest", "ruff"}
URL_CREDENTIAL_PATTERN = re.compile(r"https?://[^/\s:@]+:[^/\s@]+@")


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def dependency_name(value: str) -> str | None:
    match = DEPENDENCY_NAME_PATTERN.match(value)
    return normalize_name(match.group(1)) if match else None


def string_list(value: Any, label: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        errors.append(f"{label} must be a list of non-empty strings")
        return []
    return [item.strip() for item in value]


def duplicate_dependencies(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        name = dependency_name(value)
        if name is None:
            continue
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    return sorted(duplicates)


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def template(project_name: str, description: str, requires_python: str) -> str:
    return (
        "[project]\n"
        f"name = {toml_string(project_name)}\n"
        'version = "0.1.0"\n'
        f"description = {toml_string(description)}\n"
        'readme = "README.md"\n'
        f"requires-python = {toml_string(requires_python)}\n"
        'dependencies = ["numpy>=2,<3"]\n\n'
        "[dependency-groups]\n"
        'dev = ["pytest>=8", "ruff>=0.6"]\n\n'
        "[tool.pytest.ini_options]\n"
        'testpaths = ["tests"]\n'
        'addopts = "-q"\n\n'
        "[tool.ruff]\n"
        'target-version = "py311"\n'
        "line-length = 100\n\n"
        "[tool.ruff.lint]\n"
        'select = ["E", "F", "I", "UP", "B", "SIM"]\n'
    )


def initialize_manifest(
    path: Path,
    project_name: str,
    description: str,
    requires_python: str,
) -> dict[str, Any]:
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project directory does not exist: {root}")
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        raise ValueError("pyproject.toml already exists")
    if not NAME_PATTERN.fullmatch(project_name):
        raise ValueError("invalid project name")
    if not description.strip() or "\n" in description:
        raise ValueError("description must be one non-empty line")
    if not REQUIRES_PYTHON_PATTERN.search(requires_python):
        raise ValueError("requires-python must contain a version comparison")

    pyproject.write_text(
        template(project_name, description.strip(), requires_python.strip()),
        encoding="utf-8",
    )
    readme = root / "README.md"
    if not readme.exists():
        readme.write_text(f"# {project_name}\n", encoding="utf-8")
    (root / "tests").mkdir(exist_ok=True)
    return {
        "root": str(root),
        "files": ["pyproject.toml", "README.md", "tests/"],
    }


def evaluate_manifest(path: Path) -> dict[str, Any]:
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project directory does not exist: {root}")
    manifest = root / "pyproject.toml"
    parse_error = ""
    data: dict[str, Any] = {}
    if not manifest.is_file():
        parse_error = "pyproject.toml is missing"
    else:
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            parse_error = f"invalid TOML: {error}"

    errors: dict[str, list[str]] = {
        "metadata": [],
        "dependencies": [],
        "groups": [],
        "tools": [],
        "scripts": [],
    }
    project = data.get("project", {}) if not parse_error else {}
    if not isinstance(project, dict):
        errors["metadata"].append("[project] must be a table")
        project = {}

    name = project.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        errors["metadata"].append("project.name is missing or invalid")
    version = project.get("version")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        errors["metadata"].append("project.version is missing or invalid")
    description = project.get("description")
    if (
        not isinstance(description, str)
        or not description.strip()
        or "\n" in description
    ):
        errors["metadata"].append("project.description must be one non-empty line")
    requires_python = project.get("requires-python")
    if (
        not isinstance(requires_python, str)
        or not REQUIRES_PYTHON_PATTERN.search(requires_python)
    ):
        errors["metadata"].append("project.requires-python is missing or invalid")

    readme = project.get("readme")
    readme_path: Path | None = None
    if isinstance(readme, str):
        readme_path = root / readme
    elif isinstance(readme, dict) and isinstance(readme.get("file"), str):
        readme_path = root / readme["file"]
    else:
        errors["metadata"].append("project.readme must reference a file")
    if readme_path is not None and not readme_path.is_file():
        errors["metadata"].append(f"README target does not exist: {readme_path.name}")

    runtime = string_list(
        project.get("dependencies", []),
        "project.dependencies",
        errors["dependencies"],
    )
    duplicates = duplicate_dependencies(runtime)
    if duplicates:
        errors["dependencies"].append(
            "duplicate runtime dependencies: " + ", ".join(duplicates)
        )
    runtime_names = {
        dependency
        for item in runtime
        if (dependency := dependency_name(item)) is not None
    }
    misplaced = sorted(runtime_names & DEV_TOOLS)
    if misplaced:
        errors["dependencies"].append(
            "development tools belong in dependency-groups: " + ", ".join(misplaced)
        )
    if any(URL_CREDENTIAL_PATTERN.search(item) for item in runtime):
        errors["dependencies"].append("dependency URL contains inline credentials")

    groups = data.get("dependency-groups", {})
    if not isinstance(groups, dict):
        errors["groups"].append("[dependency-groups] must be a table")
        groups = {}
    dev = string_list(groups.get("dev", []), "dependency-groups.dev", errors["groups"])
    dev_duplicates = duplicate_dependencies(dev)
    if dev_duplicates:
        errors["groups"].append(
            "duplicate development dependencies: " + ", ".join(dev_duplicates)
        )
    dev_names = {
        dependency
        for item in dev
        if (dependency := dependency_name(item)) is not None
    }
    overlapping = sorted(runtime_names & dev_names)
    if overlapping:
        errors["groups"].append(
            "dependencies appear in runtime and dev groups: " + ", ".join(overlapping)
        )

    tools = data.get("tool", {})
    if not isinstance(tools, dict):
        errors["tools"].append("[tool] must be a table")
        tools = {}
    configured_tools = sorted(tools)
    for tool_name in DEV_TOOLS:
        if tool_name in tools and tool_name not in dev_names:
            errors["tools"].append(
                f"tool.{tool_name} is configured but {tool_name} is absent from dev group"
            )

    scripts = project.get("scripts", {})
    if scripts and not isinstance(scripts, dict):
        errors["scripts"].append("project.scripts must be a table")
        scripts = {}
    if isinstance(scripts, dict):
        for command, target in scripts.items():
            if not isinstance(command, str) or not command.strip():
                errors["scripts"].append("script command name is invalid")
            if not isinstance(target, str) or not SCRIPT_TARGET_PATTERN.fullmatch(target):
                errors["scripts"].append(f"script target is invalid: {command}")

    checks = [
        {
            "id": "toml",
            "passed": not parse_error,
            "message": "pyproject.toml is valid TOML." if not parse_error else parse_error,
        },
        *[
            {
                "id": section,
                "passed": not section_errors,
                "message": (
                    f"{section} contract is valid."
                    if not section_errors
                    else "; ".join(section_errors)
                ),
            }
            for section, section_errors in errors.items()
        ],
    ]
    return {
        "root": str(root),
        "ready": all(check["passed"] for check in checks),
        "project": {
            "name": name if isinstance(name, str) else None,
            "version": version if isinstance(version, str) else None,
            "requires_python": (
                requires_python if isinstance(requires_python, str) else None
            ),
        },
        "runtime_dependencies": runtime,
        "development_dependencies": dev,
        "configured_tools": configured_tools,
        "scripts": scripts if isinstance(scripts, dict) else {},
        "checks": checks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    result = "valid contract" if report["ready"] else "needs attention"
    lines = [
        "# pyproject contract",
        "",
        f"- Project: `{report['root']}`",
        f"- Name: `{report['project']['name'] or 'missing'}`",
        f"- Version: `{report['project']['version'] or 'missing'}`",
        f"- Requires-Python: `{report['project']['requires_python'] or 'missing'}`",
        f"- Runtime dependencies: {len(report['runtime_dependencies'])}",
        f"- Development dependencies: {len(report['development_dependencies'])}",
        f"- Result: **{result}**",
        "",
        "## Checks",
        "",
        "| Check | Result | Details |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        lines.append(f"| `{check['id']}` | {status} | {check['message']} |")
    lines.extend(["", "## Tool configuration", ""])
    if report["configured_tools"]:
        lines.extend(f"- `[tool.{name}]`" for name in report["configured_tools"])
    else:
        lines.append("_No tool tables configured._")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and audit a pyproject.toml contract"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("path", type=Path)
    init_parser.add_argument("--name", required=True)
    init_parser.add_argument("--description", required=True)
    init_parser.add_argument("--requires-python", default=">=3.11")

    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("path", type=Path)
    check_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    check_parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize_manifest(
                args.path,
                args.name,
                args.description,
                args.requires_python,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        report = evaluate_manifest(args.path)
        rendered = (
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            if args.format == "json"
            else render_markdown(report)
        )
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0 if report["ready"] else 1
    except (OSError, ValueError) as error:
        parser.exit(2, f"pyproject-audit: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
