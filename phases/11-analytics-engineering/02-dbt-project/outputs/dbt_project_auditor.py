from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml


REQUIRED_PROJECT_KEYS = {
    "name",
    "version",
    "config-version",
    "profile",
    "model-paths",
    "test-paths",
    "macro-paths",
    "snapshot-paths",
    "seed-paths",
    "target-path",
    "clean-targets",
}
EXPECTED_DIRECTORIES = {
    "models",
    "models/staging",
    "models/intermediate",
    "models/marts",
    "tests",
    "macros",
    "snapshots",
    "seeds",
}
EXPECTED_DBT_COMMANDS = ("debug", "parse", "compile")
SECRET_FIELD_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "access_key",
    "private_key",
    "key_id",
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"id": check_id, "valid": True, "observed": observed, "expected": expected, "sample": []}


def failed(
    check_id: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = yaml.safe_load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def flatten_keys(value: Any, prefix: str = "") -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.append(path)
            keys.extend(flatten_keys(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            keys.extend(flatten_keys(nested, f"{prefix}[{index}]"))
    return keys


def command_summary(commands_text: str) -> dict[str, bool]:
    text = " ".join(line.strip() for line in commands_text.splitlines())
    return {command: f"dbt {command}" in text for command in EXPECTED_DBT_COMMANDS}


def validate_project_structure(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"project_root": str(project_root)}

    project_file = project_root / "dbt_project.yml"
    profile_file = project_root / "profiles.yml.example"
    commands_file = project_root / "commands.md"

    if not project_root.is_dir():
        checks.append(failed("project_root_exists", str(project_root), "existing directory"))
        return checks, summary
    checks.append(passed("project_root_exists", str(project_root), "existing directory"))

    missing_files = [
        str(path.relative_to(project_root))
        for path in (project_file, profile_file, commands_file)
        if not path.is_file()
    ]
    if missing_files:
        checks.append(
            failed("required_configuration_files_exist", missing_files, "all required files", missing_files)
        )
        return checks, summary
    checks.append(
        passed(
            "required_configuration_files_exist",
            ["dbt_project.yml", "profiles.yml.example", "commands.md"],
            "all required files",
        )
    )

    project = read_yaml(project_file)
    profile = read_yaml(profile_file)
    commands_text = read_text(commands_file)
    summary["project_name"] = project.get("name")
    summary["profile_name"] = project.get("profile")

    missing_keys = sorted(REQUIRED_PROJECT_KEYS - set(project))
    if missing_keys:
        checks.append(failed("dbt_project_required_keys", missing_keys, sorted(REQUIRED_PROJECT_KEYS), missing_keys))
    else:
        checks.append(passed("dbt_project_required_keys", sorted(REQUIRED_PROJECT_KEYS), "present"))

    profile_name = project.get("profile")
    if isinstance(profile_name, str) and profile_name in profile:
        checks.append(passed("project_profile_exists", profile_name, "profile mapping in profiles.yml.example"))
    else:
        checks.append(
            failed("project_profile_exists", profile_name, "profile mapping in profiles.yml.example", [profile_name])
        )
        return checks, summary

    expected_dirs = set(EXPECTED_DIRECTORIES)
    for key in ("model-paths", "test-paths", "macro-paths", "snapshot-paths", "seed-paths"):
        expected_dirs.update(as_string_list(project.get(key)))
    missing_dirs = sorted(
        relative for relative in expected_dirs if not (project_root / relative).is_dir()
    )
    if missing_dirs:
        checks.append(failed("resource_directories_exist", missing_dirs, sorted(expected_dirs), missing_dirs))
    else:
        checks.append(passed("resource_directories_exist", sorted(expected_dirs), "existing directories"))

    model_files = sorted(str(path.relative_to(project_root)) for path in (project_root / "models").rglob("*.sql"))
    missing_layer_models = [
        layer for layer in ("staging", "intermediate", "marts") if not list((project_root / "models" / layer).glob("*.sql"))
    ]
    if missing_layer_models:
        checks.append(
            failed("layer_directories_have_smoke_models", missing_layer_models, "one SQL model per layer", missing_layer_models)
        )
    else:
        checks.append(passed("layer_directories_have_smoke_models", model_files, "one SQL model per layer"))

    profile_block = profile[profile_name]
    outputs = profile_block.get("outputs") if isinstance(profile_block, dict) else None
    target_name = profile_block.get("target") if isinstance(profile_block, dict) else None
    target_output = outputs.get(target_name) if isinstance(outputs, dict) else None
    if not isinstance(target_output, dict):
        checks.append(failed("profile_target_output_exists", target_name, "target output mapping", [target_name]))
    else:
        checks.append(passed("profile_target_output_exists", target_name, "target output mapping"))
        duckdb_issues: list[str] = []
        if target_output.get("type") != "duckdb":
            duckdb_issues.append("type must be duckdb")
        if not isinstance(target_output.get("path"), str) or not target_output["path"].strip():
            duckdb_issues.append("path must be a local DuckDB path")
        if str(target_output.get("path", "")).startswith("md:"):
            duckdb_issues.append("MotherDuck path is outside this local lesson")
        if not isinstance(target_output.get("schema"), str) or not target_output["schema"].strip():
            duckdb_issues.append("schema must be declared")
        if not isinstance(target_output.get("threads"), int) or target_output["threads"] <= 0:
            duckdb_issues.append("threads must be a positive integer")
        if duckdb_issues:
            checks.append(failed("profile_uses_local_duckdb", duckdb_issues, "local duckdb output", duckdb_issues))
        else:
            checks.append(
                passed(
                    "profile_uses_local_duckdb",
                    {
                        "type": target_output.get("type"),
                        "path": target_output.get("path"),
                        "schema": target_output.get("schema"),
                        "threads": target_output.get("threads"),
                    },
                    "local duckdb output",
                )
            )

    secret_fields = [
        key
        for key in flatten_keys(profile)
        if any(fragment in key.lower().replace("-", "_") for fragment in SECRET_FIELD_FRAGMENTS)
    ]
    if secret_fields:
        checks.append(failed("profile_contains_no_secret_fields", secret_fields, "no secret-like fields", secret_fields))
    else:
        checks.append(passed("profile_contains_no_secret_fields", "ok", "no secret-like fields"))

    documented = command_summary(commands_text)
    missing_commands = [command for command, present in documented.items() if not present]
    missing_flags = [flag for flag in ("--project-dir", "--profiles-dir") if flag not in commands_text]
    if missing_commands or missing_flags:
        checks.append(
            failed(
                "commands_document_debug_parse_compile",
                {"missing_commands": missing_commands, "missing_flags": missing_flags},
                "debug, parse and compile commands with project/profile dirs",
                missing_commands + missing_flags,
            )
        )
    else:
        checks.append(
            passed(
                "commands_document_debug_parse_compile",
                documented,
                "debug, parse and compile commands with project/profile dirs",
            )
        )

    return checks, summary


def tail(text: str, line_count: int = 8) -> str:
    lines = ANSI_RE.sub("", text).splitlines()
    return "\n".join(lines[-line_count:])


def run_dbt_commands(project_root: Path) -> dict[str, Any]:
    with TemporaryDirectory() as directory:
        tmp = Path(directory)
        project_copy = tmp / "project"
        profiles_dir = tmp / "profiles"
        shutil.copytree(project_root, project_copy)
        profiles_dir.mkdir()
        shutil.copy(project_copy / "profiles.yml.example", profiles_dir / "profiles.yml")
        (project_copy / "target").mkdir(exist_ok=True)

        env = os.environ.copy()
        env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
        env["DBT_DUCKDB_PATH"] = str(project_copy / "target" / "analytics.duckdb")

        results: list[dict[str, Any]] = []
        for command in EXPECTED_DBT_COMMANDS:
            completed = subprocess.run(
                [
                    "dbt",
                    command,
                    "--project-dir",
                    str(project_copy),
                    "--profiles-dir",
                    str(profiles_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=90,
                env=env,
            )
            results.append(
                {
                    "command": f"dbt {command}",
                    "returncode": completed.returncode,
                    "stdout_tail": tail(completed.stdout),
                    "stderr_tail": tail(completed.stderr),
                }
            )

    return {
        "valid": all(item["returncode"] == 0 for item in results),
        "commands": results,
    }


def validate_project(project_root: Path, run_dbt: bool = False) -> dict[str, Any]:
    checks, summary = validate_project_structure(project_root)
    if run_dbt and all(check["valid"] for check in checks):
        dbt_result = run_dbt_commands(project_root)
        if dbt_result["valid"]:
            checks.append(passed("dbt_debug_parse_compile_succeed", "ok", "all dbt commands exit 0"))
        else:
            checks.append(
                failed(
                    "dbt_debug_parse_compile_succeed",
                    dbt_result["commands"],
                    "all dbt commands exit 0",
                    dbt_result["commands"],
                )
            )
        summary["dbt_commands"] = dbt_result["commands"]
    elif run_dbt:
        checks.append(
            failed(
                "dbt_debug_parse_compile_succeed",
                "skipped because static checks failed",
                "all dbt commands exit 0",
            )
        )

    return {
        "valid": all(check["valid"] for check in checks),
        "summary": summary,
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit a minimal dbt project skeleton.")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parent / "dbt_project_skeleton",
        help="Path to the dbt project skeleton.",
    )
    parser.add_argument("--output", type=Path, help="Optional path to write the audit JSON.")
    parser.add_argument(
        "--run-dbt",
        action="store_true",
        help="Run dbt debug, parse and compile in an isolated temporary copy.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = validate_project(args.project, run_dbt=args.run_dbt)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not report["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
