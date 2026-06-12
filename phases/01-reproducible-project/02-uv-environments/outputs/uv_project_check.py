from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any


MODULE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
URL_CREDENTIAL_PATTERN = re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@")
TOKEN_PATTERN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16})\b"
)


def redact(value: str) -> str:
    cleaned = URL_CREDENTIAL_PATTERN.sub(r"\1***@", value)
    return TOKEN_PATTERN.sub("***", cleaned)


def resolve_project(path: Path) -> Path:
    root = path.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project directory does not exist: {root}")
    return root


def parse_project(root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    path = root / "pyproject.toml"
    if not path.is_file():
        return None, ["pyproject.toml is missing"]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        return None, [f"pyproject.toml is invalid: {error}"]

    errors: list[str] = []
    project = data.get("project")
    if not isinstance(project, dict):
        errors.append("[project] table is missing")
        project = {}
    requires_python = project.get("requires-python")
    if not isinstance(requires_python, str) or not requires_python.strip():
        errors.append("[project].requires-python is missing")

    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) or not item.strip() for item in dependencies
    ):
        errors.append("[project].dependencies must be a list of strings")
        dependencies = []

    groups = data.get("dependency-groups", {})
    if not isinstance(groups, dict):
        errors.append("[dependency-groups] must be a table")
        groups = {}
    group_dependencies: list[str] = []
    for group_name, group_items in groups.items():
        if not isinstance(group_items, list) or any(
            not isinstance(item, str) or not item.strip() for item in group_items
        ):
            errors.append(f"dependency group '{group_name}' must be a list of strings")
            continue
        group_dependencies.extend(group_items)

    if not dependencies and not group_dependencies:
        errors.append("the project does not declare any runtime or development dependencies")

    return (
        {
            "requires_python": requires_python,
            "dependencies": dependencies,
            "group_dependencies": group_dependencies,
        },
        errors,
    )


def parse_lock(root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    path = root / "uv.lock"
    if not path.is_file():
        return None, ["uv.lock is missing"]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        return None, [f"uv.lock is invalid: {error}"]

    errors: list[str] = []
    packages = data.get("package")
    if not isinstance(packages, list) or not packages:
        errors.append("uv.lock does not contain resolved packages")
        packages = []
    revision = data.get("revision")
    if not isinstance(revision, int):
        errors.append("uv.lock revision is missing")
    requires_python = data.get("requires-python")
    if not isinstance(requires_python, str) or not requires_python.strip():
        errors.append("uv.lock requires-python is missing")
    return (
        {
            "revision": revision,
            "requires_python": requires_python,
            "packages": packages,
        },
        errors,
    )


def venv_is_ignored(root: Path) -> bool:
    path = root / ".gitignore"
    if not path.is_file():
        return False
    lines = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return bool(lines & {".venv", ".venv/", "/.venv", "/.venv/"})


def uv_command(
    uv: str,
    root: Path,
    arguments: list[str],
    *,
    offline: bool,
    cache_dir: Path | None,
) -> subprocess.CompletedProcess[str]:
    command = [uv, "--project", str(root), "--no-python-downloads"]
    if offline:
        command.append("--offline")
    if cache_dir is not None:
        command.extend(["--cache-dir", str(cache_dir)])
    command.extend(arguments)
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )


def command_message(result: subprocess.CompletedProcess[str], success: str) -> str:
    if result.returncode == 0:
        return success
    output = redact(result.stderr.strip() or result.stdout.strip())
    first_line = output.splitlines()[0] if output else "uv command failed"
    return first_line[:240]


def validate_imports(modules: list[str]) -> list[str]:
    unique: list[str] = []
    for module in modules:
        candidate = module.strip()
        if not MODULE_PATTERN.fullmatch(candidate):
            raise ValueError(f"invalid import name: {module}")
        if candidate not in unique:
            unique.append(candidate)
    return unique


def evaluate_project(
    path: Path,
    modules: list[str] | None = None,
    *,
    offline: bool = False,
    cache_dir: Path | None = None,
    uv_executable: str | None = None,
) -> dict[str, Any]:
    root = resolve_project(path)
    imports = validate_imports(modules or [])
    uv = uv_executable or shutil.which("uv")
    project, project_errors = parse_project(root)
    lock, lock_errors = parse_lock(root)

    if uv:
        version_result = subprocess.run(
            [uv, "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
        uv_version = (
            version_result.stdout.strip()
            if version_result.returncode == 0
            else ""
        )
    else:
        version_result = None
        uv_version = ""

    lock_result = None
    sync_result = None
    import_result = None
    if uv and not project_errors and not lock_errors:
        lock_result = uv_command(
            uv,
            root,
            ["lock", "--check"],
            offline=offline,
            cache_dir=cache_dir,
        )
        sync_result = uv_command(
            uv,
            root,
            ["sync", "--check", "--locked"],
            offline=offline,
            cache_dir=cache_dir,
        )
        if imports and sync_result.returncode == 0:
            code = (
                "import importlib, sys; "
                "[importlib.import_module(name) for name in sys.argv[1:]]"
            )
            import_result = uv_command(
                uv,
                root,
                [
                    "run",
                    "--locked",
                    "--no-sync",
                    "python",
                    "-c",
                    code,
                    *imports,
                ],
                offline=offline,
                cache_dir=cache_dir,
            )

    lock_current = lock_result is not None and lock_result.returncode == 0
    environment_synced = sync_result is not None and sync_result.returncode == 0
    imports_ready = not imports or (
        import_result is not None and import_result.returncode == 0
    )
    checks = [
        {
            "id": "uv",
            "passed": bool(uv and uv_version),
            "message": (
                f"Using {uv_version}."
                if uv and uv_version
                else "uv executable is unavailable."
            ),
        },
        {
            "id": "project",
            "passed": not project_errors,
            "message": (
                "pyproject.toml declares Python and dependencies."
                if not project_errors
                else "; ".join(project_errors)
            ),
        },
        {
            "id": "lockfile",
            "passed": not lock_errors,
            "message": (
                f"uv.lock contains {len(lock['packages'])} resolved packages."
                if not lock_errors and lock is not None
                else "; ".join(lock_errors)
            ),
        },
        {
            "id": "lock-current",
            "passed": lock_current,
            "message": (
                command_message(lock_result, "uv.lock matches project metadata.")
                if lock_result is not None
                else "Lock check was not run."
            ),
        },
        {
            "id": "environment",
            "passed": environment_synced,
            "message": (
                command_message(
                    sync_result,
                    ".venv is synchronized with the locked project.",
                )
                if sync_result is not None
                else "Environment check was not run."
            ),
        },
        {
            "id": "gitignore",
            "passed": venv_is_ignored(root),
            "message": (
                ".venv is excluded from version control."
                if venv_is_ignored(root)
                else ".gitignore must exclude .venv."
            ),
        },
        {
            "id": "imports",
            "passed": imports_ready,
            "message": (
                "Requested imports work in the locked environment."
                if imports_ready and imports
                else (
                    "No smoke imports requested."
                    if not imports
                    else command_message(import_result, "Imports succeeded.")
                    if import_result is not None
                    else "Import check was not run."
                )
            ),
        },
    ]
    return {
        "root": str(root),
        "ready": all(check["passed"] for check in checks),
        "uv_version": uv_version,
        "dependencies": (
            {
                "runtime": project["dependencies"],
                "development": project["group_dependencies"],
            }
            if project is not None
            else {"runtime": [], "development": []}
        ),
        "lock_packages": len(lock["packages"]) if lock is not None else 0,
        "imports": imports,
        "checks": checks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    result = "reproducible" if report["ready"] else "needs attention"
    lines = [
        "# uv reproducibility check",
        "",
        f"- Project: `{report['root']}`",
        f"- uv: `{report['uv_version'] or 'unavailable'}`",
        f"- Runtime dependencies: {len(report['dependencies']['runtime'])}",
        f"- Development dependencies: {len(report['dependencies']['development'])}",
        f"- Locked packages: {report['lock_packages']}",
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
    lines.extend(["", "## Smoke imports", ""])
    if report["imports"]:
        lines.extend(f"- `{name}`" for name in report["imports"])
    else:
        lines.append("_No imports requested._")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check that a uv project can be reproduced from its lockfile"
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--import", action="append", default=[], dest="modules")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = evaluate_project(
            args.path,
            modules=args.modules,
            offline=args.offline,
            cache_dir=args.cache_dir,
        )
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
        parser.exit(2, f"uv-project-check: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
