from __future__ import annotations

import argparse
import configparser
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


EXPECTED_PROJECT_NAME = "sqlfluff_project"
EXPECTED_LINT_PATHS = ("models", "tests", "snapshots")
EXPECTED_IGNORES = {"target/", "logs/", "dbt_packages/", "*.duckdb"}
KEYWORD_ALIASES = re.compile(r"\bas\s+(orders|users|support|lines)\b", re.IGNORECASE)


def passed(check_id: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"id": check_id, "valid": True, "observed": observed, "expected": expected, "sample": []}


def failed(check_id: str, observed: Any, expected: Any, sample: list[Any] | None = None) -> dict[str, Any]:
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


def read_sqlfluff_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str
    if not parser.read(path, encoding="utf-8"):
        raise ValueError(f"cannot read {path}")
    return parser


def sql_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for directory in EXPECTED_LINT_PATHS:
        root = project_root / directory
        if root.exists():
            files.extend(sorted(root.rglob("*.sql")))
    return files


def parse_sqlfluff_output(stdout: str) -> list[dict[str, Any]]:
    start = stdout.find("[")
    if start == -1:
        return []
    return json.loads(stdout[start:])


def flatten_violations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for item in items:
        for violation in item.get("violations", []):
            violations.append(
                {
                    "filepath": item.get("filepath"),
                    "code": violation.get("code"),
                    "line": violation.get("start_line_no"),
                    "description": violation.get("description"),
                }
            )
    return violations


def copy_project_for_lint(project_root: Path, destination: Path) -> Path:
    def ignore_generated(_: str, names: list[str]) -> set[str]:
        return {name for name in names if name in {"target", "logs", "dbt_packages"} or name.endswith(".duckdb")}

    working_project = destination / "project"
    shutil.copytree(project_root, working_project, ignore=ignore_generated)
    return working_project


def run_sqlfluff(project_root: Path) -> dict[str, Any]:
    with TemporaryDirectory() as directory:
        working_project = copy_project_for_lint(project_root, Path(directory))
        env = os.environ.copy()
        env["DBT_DUCKDB_PATH"] = str(working_project / "sqlfluff.duckdb")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sqlfluff",
                "lint",
                *EXPECTED_LINT_PATHS,
                "--format",
                "json",
            ],
            cwd=working_project,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        items = parse_sqlfluff_output(result.stdout)
    return {
        "returncode": result.returncode,
        "files": items,
        "violations": flatten_violations(items),
        "stderr": result.stderr.strip(),
    }


def run_raw_bad_example(example_path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sqlfluff",
            "lint",
            str(example_path),
            "--dialect",
            "duckdb",
            "--templater",
            "raw",
            "--format",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    items = parse_sqlfluff_output(result.stdout)
    return {
        "returncode": result.returncode,
        "files": items,
        "violations": flatten_violations(items),
        "stderr": result.stderr.strip(),
    }


def validate_static_project(project_root: Path, bad_example: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"project_root": str(project_root)}
    required_files = [
        "dbt_project.yml",
        "profiles.yml",
        "profiles.yml.example",
        ".sqlfluff",
        ".sqlfluffignore",
        "commands.md",
    ]
    missing = [path for path in required_files if not (project_root / path).is_file()]
    checks.append(
        failed("required_sqlfluff_files_exist", missing, required_files, missing)
        if missing
        else passed("required_sqlfluff_files_exist", required_files, "required SQLFluff project files")
    )
    if missing:
        return checks, summary

    dbt_project = read_yaml(project_root / "dbt_project.yml")
    observed_project = {"name": dbt_project.get("name"), "profile": dbt_project.get("profile")}
    expected_project = {"name": EXPECTED_PROJECT_NAME, "profile": EXPECTED_PROJECT_NAME}
    checks.append(
        passed("dbt_project_is_renamed", observed_project, expected_project)
        if observed_project == expected_project
        else failed("dbt_project_is_renamed", observed_project, expected_project)
    )

    profile = read_yaml(project_root / "profiles.yml")
    output = ((profile.get(EXPECTED_PROJECT_NAME) or {}).get("outputs") or {}).get("dev") or {}
    profile_observed = {"type": output.get("type"), "path": output.get("path"), "threads": output.get("threads")}
    profile_valid = output.get("type") == "duckdb" and "sqlfluff.duckdb" in str(output.get("path", ""))
    secret_like = [key for key in output if any(token in key.lower() for token in ("password", "token", "secret"))]
    if profile_valid and not secret_like:
        checks.append(passed("profile_uses_safe_local_duckdb", profile_observed, "duckdb profile without secrets"))
    else:
        checks.append(failed("profile_uses_safe_local_duckdb", profile_observed, "duckdb profile without secrets", secret_like))

    config = read_sqlfluff_config(project_root / ".sqlfluff")
    core = config["sqlfluff"] if config.has_section("sqlfluff") else {}
    dbt_templater = config["sqlfluff:templater:dbt"] if config.has_section("sqlfluff:templater:dbt") else {}
    config_observed = {
        "dialect": core.get("dialect"),
        "templater": core.get("templater"),
        "max_line_length": core.get("max_line_length"),
        "ignore": core.get("ignore"),
        "exclude_rules": core.get("exclude_rules"),
    }
    config_valid = (
        core.get("dialect") == "duckdb"
        and core.get("templater") == "dbt"
        and int(core.get("max_line_length", "0")) <= 120
        and not core.get("ignore")
        and not core.get("exclude_rules")
    )
    checks.append(
        passed("sqlfluff_core_config_declares_duckdb_dbt_style_gate", config_observed, "duckdb dbt style gate")
        if config_valid
        else failed("sqlfluff_core_config_declares_duckdb_dbt_style_gate", config_observed, "duckdb dbt style gate")
    )

    templater_observed = {
        "project_dir": dbt_templater.get("project_dir"),
        "profiles_dir": dbt_templater.get("profiles_dir"),
        "profile": dbt_templater.get("profile"),
        "target": dbt_templater.get("target"),
        "dbt_skip_compilation_error": dbt_templater.get("dbt_skip_compilation_error"),
    }
    templater_valid = templater_observed == {
        "project_dir": ".",
        "profiles_dir": ".",
        "profile": EXPECTED_PROJECT_NAME,
        "target": "dev",
        "dbt_skip_compilation_error": "False",
    }
    checks.append(
        passed("dbt_templater_is_explicit_and_local", templater_observed, "local dbt templater settings")
        if templater_valid
        else failed("dbt_templater_is_explicit_and_local", templater_observed, "local dbt templater settings")
    )

    ignore_lines = {
        line.strip()
        for line in (project_root / ".sqlfluffignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing_ignores = sorted(EXPECTED_IGNORES - ignore_lines)
    checks.append(
        passed("generated_artifacts_are_ignored", sorted(ignore_lines & EXPECTED_IGNORES), sorted(EXPECTED_IGNORES))
        if not missing_ignores
        else failed("generated_artifacts_are_ignored", sorted(ignore_lines), sorted(EXPECTED_IGNORES), missing_ignores)
    )

    sql_alias_problems = [
        str(path.relative_to(project_root))
        for path in sql_files(project_root)
        if KEYWORD_ALIASES.search(path.read_text(encoding="utf-8"))
    ]
    checks.append(
        passed("keyword_like_aliases_are_removed", len(sql_alias_problems), 0)
        if not sql_alias_problems
        else failed("keyword_like_aliases_are_removed", sql_alias_problems, "no aliases named orders/users/support/lines", sql_alias_problems)
    )

    commands_text = (project_root / "commands.md").read_text(encoding="utf-8").lower()
    required_terms = ["sqlfluff lint", "sqlfluff fix", "templater = dbt", "templater raw", "dbt test", ".sqlfluffignore"]
    missing_terms = [term for term in required_terms if term not in commands_text]
    checks.append(
        passed("commands_separate_style_gate_from_semantic_tests", required_terms, "style and semantic commands")
        if not missing_terms
        else failed("commands_separate_style_gate_from_semantic_tests", missing_terms, required_terms, missing_terms)
    )

    bad_text = bad_example.read_text(encoding="utf-8") if bad_example.is_file() else ""
    bad_valid = bad_example.is_file() and "SELECT " in bad_text and "GROUP BY 1" in bad_text
    checks.append(
        passed("raw_templater_bad_style_example_exists", bad_example.name, "plain SQL style violation example")
        if bad_valid
        else failed("raw_templater_bad_style_example_exists", str(bad_example), "plain SQL style violation example")
    )

    summary["sql_files"] = len(sql_files(project_root))
    return checks, summary


def validate_project(project_root: Path, bad_example: Path, run_lint: bool = False) -> dict[str, Any]:
    checks, summary = validate_static_project(project_root, bad_example)
    lint_result: dict[str, Any] | None = None
    bad_result: dict[str, Any] | None = None

    if run_lint and all(check["valid"] for check in checks):
        lint_result = run_sqlfluff(project_root)
        warnings = lint_result["stderr"]
        project_lint_valid = lint_result["returncode"] == 0 and not lint_result["violations"] and "not found in dbt project" not in warnings.lower()
        checks.append(
            passed(
                "sqlfluff_lint_passes_on_dbt_project",
                {"files": len(lint_result["files"]), "violations": 0},
                "zero SQLFluff violations",
            )
            if project_lint_valid
            else failed(
                "sqlfluff_lint_passes_on_dbt_project",
                {"returncode": lint_result["returncode"], "violations": len(lint_result["violations"]), "stderr": warnings},
                "zero SQLFluff violations",
                lint_result["violations"][:5],
            )
        )

        bad_result = run_raw_bad_example(bad_example)
        bad_codes = {item["code"] for item in bad_result["violations"]}
        bad_valid = bad_result["returncode"] == 1 and bool(bad_codes & {"CP01", "CP02", "LT01", "LT09", "RF02"})
        checks.append(
            passed(
                "raw_templater_catches_plain_sql_style_violation",
                sorted(bad_codes),
                "raw SQL lint violations",
            )
            if bad_valid
            else failed(
                "raw_templater_catches_plain_sql_style_violation",
                {"returncode": bad_result["returncode"], "codes": sorted(bad_codes)},
                "raw SQL lint violations",
                bad_result["violations"][:5],
            )
        )

    if lint_result is not None:
        summary["lint"] = {
            "files": len(lint_result["files"]),
            "violations": len(lint_result["violations"]),
            "returncode": lint_result["returncode"],
        }
    if bad_result is not None:
        summary["bad_example"] = {
            "violations": len(bad_result["violations"]),
            "codes": sorted({item["code"] for item in bad_result["violations"]}),
            "returncode": bad_result["returncode"],
        }
    return {"valid": all(check["valid"] for check in checks), "checks": checks, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate SQLFluff configuration and lint report for lesson 11/10.")
    default_root = Path(__file__).resolve().parent
    parser.add_argument("--project", type=Path, default=default_root / "sqlfluff_project")
    parser.add_argument("--bad-example", type=Path, default=default_root / "bad_style_example.sql")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run-sqlfluff", action="store_true")
    args = parser.parse_args(argv)

    report = validate_project(args.project, args.bad_example, run_lint=args.run_sqlfluff)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
