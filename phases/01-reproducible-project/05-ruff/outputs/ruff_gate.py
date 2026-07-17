from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Sequence


REQUIRED_RULES = {"E", "F", "I", "UP", "B", "SIM"}


def default_command() -> list[str]:
    if shutil.which("ruff"):
        return ["ruff"]
    if shutil.which("uvx"):
        return ["uvx", "--offline", "--from", "ruff==0.15.17", "ruff"]
    return ["ruff"]


def subprocess_environment(command: Sequence[str]) -> dict[str, str]:
    environment = os.environ.copy()
    if command and Path(command[0]).name == "uvx":
        temporary = Path(tempfile.gettempdir())
        environment.setdefault(
            "UV_CACHE_DIR",
            str(temporary / "analyst-tools-ruff-uv-cache"),
        )
        environment.setdefault(
            "UV_TOOL_DIR",
            str(temporary / "analyst-tools-ruff-uv-tools"),
        )
        environment.setdefault(
            "UV_TOOL_BIN_DIR",
            str(temporary / "analyst-tools-ruff-uv-bin"),
        )
    return environment


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
    ruff = data.get("tool", {}).get("ruff", {})
    lint = ruff.get("lint", {}) if isinstance(ruff, dict) else {}
    selected = lint.get("select", []) if isinstance(lint, dict) else []
    return {
        "config": str(config),
        "ruff_in_dev": isinstance(dev, list)
        and any(isinstance(item, str) and item.casefold().startswith("ruff") for item in dev),
        "selected": selected if isinstance(selected, list) else [],
        "target_version": ruff.get("target-version") if isinstance(ruff, dict) else None,
        "line_length": ruff.get("line-length") if isinstance(ruff, dict) else None,
        "has_format": isinstance(ruff, dict) and isinstance(ruff.get("format"), dict),
    }


def execute(command: Sequence[str], root: Path, mode: str) -> dict[str, Any]:
    config = root / "pyproject.toml"
    arguments = (
        [*command, "check", "--config", str(config), "."]
        if mode == "lint"
        else [*command, "format", "--check", "--config", str(config), "."]
    )
    try:
        result = subprocess.run(
            arguments,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            env=subprocess_environment(command),
        )
    except FileNotFoundError:
        return {
            "passed": False,
            "command": arguments,
            "returncode": 127,
            "output": f"command not found: {command[0]}",
        }
    return {
        "passed": result.returncode == 0,
        "command": arguments,
        "returncode": result.returncode,
        "output": (result.stdout + result.stderr).strip(),
    }


def evaluate(root: Path, command: Sequence[str] | None = None) -> dict[str, Any]:
    project = root.expanduser().resolve()
    contract = read_contract(project)
    selected = set(contract["selected"])
    config_errors: list[str] = []
    if not contract["ruff_in_dev"]:
        config_errors.append("Ruff is absent from dependency-groups.dev")
    missing = sorted(REQUIRED_RULES - selected)
    if missing:
        config_errors.append("missing rule families: " + ", ".join(missing))
    if selected == {"ALL"}:
        config_errors.append("ALL makes upgrades enable new rules implicitly")
    if not contract["target_version"]:
        config_errors.append("tool.ruff.target-version is missing")
    if not contract["has_format"]:
        config_errors.append("tool.ruff.format is missing")

    selected_command = list(command or default_command())
    lint = execute(selected_command, project, "lint")
    formatting = execute(selected_command, project, "format")
    checks = [
        {
            "id": "configuration",
            "passed": not config_errors,
            "message": "valid" if not config_errors else "; ".join(config_errors),
        },
        {
            "id": "lint",
            "passed": lint["passed"],
            "message": lint["output"] or "all lint checks passed",
        },
        {
            "id": "format",
            "passed": formatting["passed"],
            "message": formatting["output"] or "all files are formatted",
        },
    ]
    return {
        "root": str(project),
        "ready": all(check["passed"] for check in checks),
        "command": selected_command,
        "contract": contract,
        "checks": checks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Ruff quality gate",
        "",
        f"- Project: `{report['root']}`",
        f"- Command: `{' '.join(report['command'])}`",
        f"- Rules: `{', '.join(report['contract']['selected'])}`",
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
    parser = argparse.ArgumentParser(description="Run Ruff lint and format quality gates")
    parser.add_argument("project", type=Path)
    parser.add_argument(
        "--ruff-command",
        help='Command string, for example "uvx --from ruff==0.15.17 ruff"',
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    try:
        report = evaluate(
            args.project,
            shlex.split(args.ruff_command) if args.ruff_command else None,
        )
    except ValueError as error:
        parser.exit(2, f"ruff-gate: {error}\n")
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
