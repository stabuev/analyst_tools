from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

SETUP_UV_SHA = "08807647e7069bb48b6ef5acd8ec9567f424441b"
REQUIRED_TRIGGERS = {"push", "pull_request", "workflow_dispatch"}
REQUIRED_RUNS = [
    "uv sync --locked --dev",
    "uv run python tools/workflow_audit.py .github/workflows/quality.yml",
    "uv run ruff check .",
    "uv run ruff format --check .",
    "uv run pytest",
]


def load_workflow(path: Path) -> dict[str, Any]:
    workflow = path.expanduser().resolve()
    if not workflow.is_file():
        raise ValueError(f"workflow does not exist: {workflow}")
    try:
        data = yaml.load(workflow.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise ValueError(f"invalid workflow YAML: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("workflow must contain a mapping")
    return {"path": str(workflow), **data}


def as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def evaluate(data: dict[str, Any]) -> dict[str, Any]:
    errors: dict[str, list[str]] = {
        "triggers": [],
        "permissions": [],
        "concurrency": [],
        "job": [],
        "actions": [],
        "commands": [],
    }

    triggers = as_mapping(data.get("on"))
    missing_triggers = sorted(REQUIRED_TRIGGERS - set(triggers))
    if missing_triggers:
        errors["triggers"].append("missing triggers: " + ", ".join(missing_triggers))

    permissions = as_mapping(data.get("permissions"))
    if permissions != {"contents": "read"}:
        errors["permissions"].append("workflow permissions must be exactly contents: read")

    concurrency = as_mapping(data.get("concurrency"))
    if concurrency.get("group") != "${{ github.workflow }}-${{ github.ref }}":
        errors["concurrency"].append("concurrency group must isolate workflow and ref")
    if concurrency.get("cancel-in-progress") != "true":
        errors["concurrency"].append("cancel-in-progress must be true")

    jobs = as_mapping(data.get("jobs"))
    quality = as_mapping(jobs.get("quality"))
    if quality.get("runs-on") != "ubuntu-latest":
        errors["job"].append("quality job must run on ubuntu-latest")
    try:
        timeout = int(quality.get("timeout-minutes", "0"))
    except (TypeError, ValueError):
        timeout = 0
    if not 1 <= timeout <= 15:
        errors["job"].append("quality timeout must be between 1 and 15 minutes")
    steps = quality.get("steps")
    if not isinstance(steps, list):
        errors["job"].append("quality.steps must be a list")
        steps = []

    uses = [
        step.get("uses")
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("uses"), str)
    ]
    required_actions = {
        "actions/checkout@v6",
        "actions/setup-python@v6",
        f"astral-sh/setup-uv@{SETUP_UV_SHA}",
    }
    missing_actions = sorted(required_actions - set(uses))
    if missing_actions:
        errors["actions"].append("missing actions: " + ", ".join(missing_actions))
    setup_uv = next(
        (
            step
            for step in steps
            if isinstance(step, dict) and step.get("uses") == f"astral-sh/setup-uv@{SETUP_UV_SHA}"
        ),
        {},
    )
    setup_uv_with = as_mapping(setup_uv.get("with"))
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(setup_uv_with.get("version", ""))):
        errors["actions"].append("setup-uv must pin an explicit uv version")
    if setup_uv_with.get("enable-cache") != "true":
        errors["actions"].append("setup-uv cache must be enabled")

    runs = [
        step.get("run", "").strip()
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    missing_runs = [command for command in REQUIRED_RUNS if command not in runs]
    if missing_runs:
        errors["commands"].append("missing commands: " + ", ".join(missing_runs))
    positions = [runs.index(command) for command in REQUIRED_RUNS if command in runs]
    if len(positions) == len(REQUIRED_RUNS) and positions != sorted(positions):
        errors["commands"].append("quality commands are in the wrong order")
    if any(isinstance(step, dict) and step.get("continue-on-error") == "true" for step in steps):
        errors["commands"].append("quality steps must not use continue-on-error")

    checks = [
        {
            "id": section,
            "passed": not section_errors,
            "message": "valid" if not section_errors else "; ".join(section_errors),
        }
        for section, section_errors in errors.items()
    ]
    return {
        "path": data.get("path"),
        "ready": all(check["passed"] for check in checks),
        "workflow": data.get("name"),
        "checks": checks,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# GitHub Actions quality workflow audit",
        "",
        f"- Workflow: `{report['workflow'] or 'unnamed'}`",
        f"- Path: `{report['path'] or 'in-memory'}`",
        f"- Result: **{'PASS' if report['ready'] else 'FAIL'}**",
        "",
        "| Check | Result | Details |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        lines.append(
            f"| `{check['id']}` | {'PASS' if check['passed'] else 'FAIL'} | {check['message']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a GitHub Actions quality workflow")
    parser.add_argument("workflow", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()
    try:
        report = evaluate(load_workflow(args.workflow))
    except ValueError as error:
        parser.exit(2, f"workflow-audit: {error}\n")
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(report), end="")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
