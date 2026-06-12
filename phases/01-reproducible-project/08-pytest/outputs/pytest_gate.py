from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Sequence


def read_contract(root: Path) -> dict[str, Any]:
    config = root / "pyproject.toml"
    if not config.is_file():
        raise ValueError(f"pyproject.toml does not exist: {config}")
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"invalid pyproject.toml: {error}") from error
    groups = data.get("dependency-groups", {})
    dev = groups.get("dev", []) if isinstance(groups, dict) else []
    options = data.get("tool", {}).get("pytest", {}).get("ini_options", {})
    return {
        "pytest_in_dev": isinstance(dev, list)
        and any(
            isinstance(item, str) and item.casefold().startswith("pytest") for item in dev
        ),
        "testpaths": options.get("testpaths", []) if isinstance(options, dict) else [],
        "addopts": options.get("addopts") if isinstance(options, dict) else None,
        "pythonpath": options.get("pythonpath", []) if isinstance(options, dict) else [],
    }


def evaluate(
    root: Path,
    command: Sequence[str] | None = None,
) -> dict[str, Any]:
    project = root.expanduser().resolve()
    contract = read_contract(project)
    config_errors: list[str] = []
    if not contract["pytest_in_dev"]:
        config_errors.append("pytest is absent from dependency-groups.dev")
    if "tests" not in contract["testpaths"]:
        config_errors.append("tool.pytest.ini_options.testpaths must include tests")
    if "--strict-markers" not in str(contract["addopts"]):
        config_errors.append("addopts must enable --strict-markers")

    selected_command = list(command or [sys.executable, "-m", "pytest"])
    try:
        result = subprocess.run(
            [*selected_command, str(project)],
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
        )
        test_output = (result.stdout + result.stderr).strip()
        test_passed = result.returncode == 0
        returncode = result.returncode
    except FileNotFoundError:
        test_output = f"command not found: {selected_command[0]}"
        test_passed = False
        returncode = 127

    checks = [
        {
            "id": "configuration",
            "passed": not config_errors,
            "message": "valid" if not config_errors else "; ".join(config_errors),
        },
        {
            "id": "tests",
            "passed": test_passed,
            "message": test_output or "pytest passed",
        },
    ]
    return {
        "root": str(project),
        "ready": all(check["passed"] for check in checks),
        "command": selected_command,
        "returncode": returncode,
        "checks": checks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# pytest behavioral gate",
        "",
        f"- Project: `{report['root']}`",
        f"- Command: `{' '.join(report['command'])}`",
        f"- Result: **{'PASS' if report['ready'] else 'FAIL'}**",
        "",
        "| Check | Result | Details |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        message = check["message"].replace("\n", "<br>")
        lines.append(
            f"| `{check['id']}` | {'PASS' if check['passed'] else 'FAIL'} | {message} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the project pytest quality gate")
    parser.add_argument("project", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    try:
        report = evaluate(args.project)
    except ValueError as error:
        parser.exit(2, f"pytest-gate: {error}\n")
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
