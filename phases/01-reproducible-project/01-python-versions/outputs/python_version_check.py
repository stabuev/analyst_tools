from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VERSION_PATTERN = re.compile(r"^\d+(?:\.\d+){1,2}$")
CLAUSE_PATTERN = re.compile(
    r"^(~=|==|!=|<=|>=|<|>)\s*(\d+(?:\.\d+){1,2})(\.\*)?$"
)
PROJECT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$")


@dataclass(frozen=True)
class Version:
    release: tuple[int, int, int]
    precision: int

    @classmethod
    def parse(cls, value: str) -> "Version":
        candidate = value.strip()
        if not VERSION_PATTERN.fullmatch(candidate):
            raise ValueError(
                f"unsupported Python release '{value}'; expected MAJOR.MINOR[.PATCH]"
            )
        parts = tuple(int(part) for part in candidate.split("."))
        return cls(parts + (0,) * (3 - len(parts)), len(parts))

    def matches_prefix(self, other: "Version") -> bool:
        return self.release[: self.precision] == other.release[: self.precision]

    def __str__(self) -> str:
        return ".".join(str(part) for part in self.release[: self.precision])


@dataclass(frozen=True)
class Clause:
    operator: str
    version: Version
    wildcard: bool = False

    def contains(self, candidate: Version) -> bool:
        current = candidate.release
        expected = self.version.release
        if self.wildcard:
            matched = self.version.matches_prefix(candidate)
            return matched if self.operator == "==" else not matched
        if self.operator == "==":
            return current == expected
        if self.operator == "!=":
            return current != expected
        if self.operator == ">=":
            return current >= expected
        if self.operator == "<=":
            return current <= expected
        if self.operator == ">":
            return current > expected
        if self.operator == "<":
            return current < expected
        if self.operator == "~=":
            if current < expected:
                return False
            if self.version.precision == 2:
                upper = (expected[0] + 1, 0, 0)
            else:
                upper = (expected[0], expected[1] + 1, 0)
            return current < upper
        raise AssertionError(f"unknown operator: {self.operator}")

    def __str__(self) -> str:
        suffix = ".*" if self.wildcard else ""
        return f"{self.operator}{self.version}{suffix}"


def parse_specifier(value: str) -> list[Clause]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("requires-python must be a non-empty string")
    clauses: list[Clause] = []
    for raw_clause in value.split(","):
        candidate = raw_clause.strip()
        match = CLAUSE_PATTERN.fullmatch(candidate)
        if match is None:
            raise ValueError(
                f"unsupported requires-python clause '{candidate}'; "
                "use numeric release clauses such as >=3.11,<3.13"
            )
        operator, version_text, wildcard_text = match.groups()
        wildcard = bool(wildcard_text)
        if wildcard and operator not in {"==", "!="}:
            raise ValueError("wildcard releases are supported only with == or !=")
        version = Version.parse(version_text)
        if wildcard and version.precision < 2:
            raise ValueError("wildcard release requires at least MAJOR.MINOR")
        clauses.append(Clause(operator, version, wildcard))
    return clauses


def satisfies(version: Version, clauses: list[Clause]) -> bool:
    return all(clause.contains(version) for clause in clauses)


def normalize_project_name(value: str) -> str:
    candidate = value.strip()
    if not PROJECT_NAME_PATTERN.fullmatch(candidate):
        raise ValueError("project name must contain letters, digits, dots, underscores or dashes")
    return candidate


def initialize_contract(
    path: Path,
    project_name: str,
    requires_python: str,
    selector: str,
) -> dict[str, Any]:
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project directory does not exist: {root}")
    pyproject = root / "pyproject.toml"
    selector_path = root / ".python-version"
    if pyproject.exists() or selector_path.exists():
        raise ValueError(
            "pyproject.toml or .python-version already exists; "
            "edit the existing project contract deliberately"
        )

    project_name = normalize_project_name(project_name)
    clauses = parse_specifier(requires_python)
    selected = Version.parse(selector)
    if not satisfies(selected, clauses):
        raise ValueError(
            f"selected Python {selected} does not satisfy requires-python "
            f"'{requires_python}'"
        )

    pyproject.write_text(
        (
            "[project]\n"
            f'name = "{project_name}"\n'
            'version = "0.1.0"\n'
            f'requires-python = "{requires_python}"\n'
        ),
        encoding="utf-8",
    )
    selector_path.write_text(f"{selector}\n", encoding="utf-8")
    return {
        "root": str(root),
        "requires_python": requires_python,
        "selector": selector,
        "files": ["pyproject.toml", ".python-version"],
    }


def read_pyproject(root: Path) -> tuple[str | None, str | None]:
    path = root / "pyproject.toml"
    if not path.is_file():
        return None, "pyproject.toml is missing"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        return None, f"pyproject.toml is invalid: {error}"
    project = data.get("project")
    if not isinstance(project, dict):
        return None, "[project] table is missing"
    value = project.get("requires-python")
    if not isinstance(value, str) or not value.strip():
        return None, "[project].requires-python is missing"
    return value.strip(), None


def read_selector(root: Path) -> tuple[Version | None, str | None]:
    path = root / ".python-version"
    if not path.is_file():
        return None, ".python-version is missing"
    lines = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(lines) != 1:
        return None, ".python-version must contain one Python release"
    try:
        return Version.parse(lines[0]), None
    except ValueError as error:
        return None, str(error)


def resolve_root(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    if not candidate.is_dir():
        raise ValueError(f"project directory does not exist: {candidate}")
    return candidate


def runtime_version() -> Version:
    release = sys.version_info
    return Version((release.major, release.minor, release.micro), 3)


def evaluate_project(
    path: Path,
    candidates: list[str] | None = None,
    current_version: Version | None = None,
    executable: str | None = None,
) -> dict[str, Any]:
    root = resolve_root(path)
    requires_python, metadata_error = read_pyproject(root)
    selector, selector_error = read_selector(root)
    clauses: list[Clause] = []
    specifier_error = metadata_error
    if requires_python is not None:
        try:
            clauses = parse_specifier(requires_python)
        except ValueError as error:
            specifier_error = str(error)

    current = current_version or runtime_version()
    executable_path = executable if executable is not None else (sys.executable or "")
    current_supported = bool(clauses) and satisfies(current, clauses)
    selector_supported = (
        selector is not None and bool(clauses) and satisfies(selector, clauses)
    )
    selector_matches_runtime = (
        selector is not None and selector.matches_prefix(current)
    )

    matrix: list[dict[str, Any]] = []
    candidate_errors: list[str] = []
    for value in candidates or []:
        try:
            version = Version.parse(value)
        except ValueError as error:
            candidate_errors.append(str(error))
            continue
        matrix.append(
            {
                "version": str(version),
                "compatible": bool(clauses) and satisfies(version, clauses),
            }
        )

    checks = [
        {
            "id": "requires-python",
            "passed": specifier_error is None and bool(clauses),
            "message": (
                f"Project declares requires-python = '{requires_python}'."
                if specifier_error is None and clauses
                else specifier_error or "requires-python has no clauses"
            ),
        },
        {
            "id": "selector",
            "passed": selector_error is None and selector_supported,
            "message": (
                f".python-version selects {selector}, inside the supported range."
                if selector_error is None and selector_supported
                else selector_error
                or f"Selected Python {selector} is outside requires-python."
            ),
        },
        {
            "id": "runtime",
            "passed": bool(executable_path) and current_supported,
            "message": (
                f"Running Python {current} from {executable_path} is compatible."
                if executable_path and current_supported
                else (
                    f"Running Python {current} is outside requires-python."
                    if executable_path
                    else "sys.executable is unavailable."
                )
            ),
        },
        {
            "id": "selection-match",
            "passed": selector_error is None and selector_matches_runtime,
            "message": (
                f"Runtime {current} matches selector {selector}."
                if selector_error is None and selector_matches_runtime
                else selector_error
                or f"Runtime {current} does not match selector {selector}."
            ),
        },
        {
            "id": "candidate-input",
            "passed": not candidate_errors,
            "message": (
                "Candidate version inputs are valid."
                if not candidate_errors
                else "; ".join(candidate_errors)
            ),
        },
    ]
    return {
        "root": str(root),
        "ready": all(check["passed"] for check in checks),
        "requires_python": requires_python,
        "selector": str(selector) if selector else None,
        "runtime": {
            "version": str(current),
            "executable": executable_path,
            "implementation": platform.python_implementation(),
        },
        "checks": checks,
        "matrix": matrix,
    }


def render_markdown(report: dict[str, Any]) -> str:
    result = "compatible" if report["ready"] else "needs attention"
    lines = [
        "# Python version contract",
        "",
        f"- Project: `{report['root']}`",
        f"- Requires-Python: `{report['requires_python'] or 'missing'}`",
        f"- Selector: `{report['selector'] or 'missing'}`",
        f"- Runtime: `{report['runtime']['version']}`",
        f"- Executable: `{report['runtime']['executable'] or 'unknown'}`",
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

    lines.extend(["", "## Candidate matrix", ""])
    if report["matrix"]:
        lines.extend(["| Python | Compatible |", "|---|---|"])
        for item in report["matrix"]:
            compatible = "yes" if item["compatible"] else "no"
            lines.append(f"| `{item['version']}` | {compatible} |")
    else:
        lines.append("_No candidate versions requested._")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and check a Python version contract"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a minimal version contract")
    init_parser.add_argument("path", type=Path)
    init_parser.add_argument("--name", required=True)
    init_parser.add_argument("--requires", required=True, dest="requires_python")
    init_parser.add_argument("--select", required=True, dest="selector")

    check_parser = subparsers.add_parser("check", help="Check the project and runtime")
    check_parser.add_argument("path", type=Path)
    check_parser.add_argument("--candidate", action="append", default=[])
    check_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    check_parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize_contract(
                args.path,
                project_name=args.name,
                requires_python=args.requires_python,
                selector=args.selector,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        report = evaluate_project(args.path, candidates=args.candidate)
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
        parser.exit(2, f"python-version-check: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
