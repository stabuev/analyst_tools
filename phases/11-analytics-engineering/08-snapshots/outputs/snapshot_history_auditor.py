from __future__ import annotations

import argparse
import csv
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


EXPECTED_PROJECT_NAME = "snapshot_project"
SNAPSHOT_NAME = "subscription_status_snapshot"
HISTORY_MODEL_NAME = "int_subscription_history"
EXPECTED_UNIQUE_KEY = "subscription_id"
EXPECTED_STRATEGY = "check"
EXPECTED_UPDATED_AT = "updated_at"
EXPECTED_CHECK_COLS = ["plan", "status", "started_at", "ended_at"]
EXPECTED_CURRENT_VALID_TO = "9999-12-31"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


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


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = yaml.safe_load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"unsafe SQL identifier: {value}")
    return value


def data_contract_tables(data_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = data_contract.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("data contract must contain a tables object")
    return {str(name): table for name, table in tables.items() if isinstance(table, dict)}


def find_snapshot(snapshot_yaml: dict[str, Any], name: str) -> dict[str, Any] | None:
    for item in snapshot_yaml.get("snapshots", []):
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def find_model(properties: dict[str, Any], name: str) -> dict[str, Any] | None:
    for item in properties.get("models", []):
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def column_test_names(resource: dict[str, Any], column_name: str) -> set[str]:
    for column in resource.get("columns", []):
        if isinstance(column, dict) and column.get("name") == column_name:
            names: set[str] = set()
            for item in column.get("data_tests", []):
                if isinstance(item, str):
                    names.add(item)
                elif isinstance(item, dict) and item:
                    names.add(next(iter(item)))
            return names
    return set()


def validate_snapshot_yaml(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    snapshot_path = project_root / "snapshots" / "subscription_status_history.yml"
    snapshot_yaml = read_yaml(snapshot_path)
    snapshot = find_snapshot(snapshot_yaml, SNAPSHOT_NAME)
    if snapshot is None:
        return [failed("snapshot_yaml_declares_resource", None, SNAPSHOT_NAME)], summary
    checks.append(passed("snapshot_yaml_declares_resource", SNAPSHOT_NAME, SNAPSHOT_NAME))

    config = snapshot.get("config") or {}
    observed = {
        "relation": snapshot.get("relation"),
        "target_schema": config.get("target_schema"),
        "unique_key": config.get("unique_key"),
        "strategy": config.get("strategy"),
        "updated_at": config.get("updated_at"),
        "check_cols": config.get("check_cols"),
        "dbt_valid_to_current": config.get("dbt_valid_to_current"),
    }
    summary["snapshot_config"] = observed
    expected = {
        "relation": "ref('stg_subscriptions')",
        "target_schema": "snapshots",
        "unique_key": EXPECTED_UNIQUE_KEY,
        "strategy": EXPECTED_STRATEGY,
        "updated_at": EXPECTED_UPDATED_AT,
        "check_cols": EXPECTED_CHECK_COLS,
    }
    errors = [
        {"key": key, "observed": observed.get(key), "expected": value}
        for key, value in expected.items()
        if observed.get(key) != value
    ]
    if EXPECTED_CURRENT_VALID_TO not in str(config.get("dbt_valid_to_current", "")):
        errors.append(
            {
                "key": "dbt_valid_to_current",
                "observed": config.get("dbt_valid_to_current"),
                "expected": EXPECTED_CURRENT_VALID_TO,
            }
        )
    if errors:
        checks.append(failed("snapshot_config_is_explicit", errors, expected, errors))
    else:
        checks.append(passed("snapshot_config_is_explicit", observed, expected))

    check_cols = config.get("check_cols")
    if check_cols == "all" or EXPECTED_UPDATED_AT in (check_cols or []):
        checks.append(
            failed(
                "snapshot_excludes_noisy_columns",
                check_cols,
                "business check_cols without updated_at and without all",
                [check_cols],
            )
        )
    else:
        checks.append(passed("snapshot_excludes_noisy_columns", check_cols, EXPECTED_CHECK_COLS))

    contract = ((snapshot.get("meta") or {}).get("snapshot_contract") or {})
    summary["snapshot_contract"] = contract
    contract_errors = [
        {"key": key, "observed": contract.get(key), "expected": value}
        for key, value in {
            "source_model": "stg_subscriptions",
            "unique_key": EXPECTED_UNIQUE_KEY,
            "strategy": EXPECTED_STRATEGY,
            "updated_at": EXPECTED_UPDATED_AT,
            "check_cols": EXPECTED_CHECK_COLS,
            "excluded_noisy_columns": [EXPECTED_UPDATED_AT],
            "current_valid_to": EXPECTED_CURRENT_VALID_TO,
        }.items()
        if contract.get(key) != value
    ]
    if "dbt snapshot" not in str(contract.get("schedule", "")).lower():
        contract_errors.append({"key": "schedule", "observed": contract.get("schedule"), "expected": "dbt snapshot"})
    if contract_errors:
        checks.append(failed("snapshot_contract_meta_is_complete", contract_errors, "complete snapshot contract"))
    else:
        checks.append(passed("snapshot_contract_meta_is_complete", contract, "complete snapshot contract"))

    scd_tests = column_test_names(snapshot, "dbt_scd_id")
    valid_to_tests = column_test_names(snapshot, "dbt_valid_to")
    if {"unique", "not_null"}.issubset(scd_tests) and "not_null" in valid_to_tests:
        checks.append(passed("snapshot_meta_columns_have_tests", {"dbt_scd_id": sorted(scd_tests), "dbt_valid_to": sorted(valid_to_tests)}))
    else:
        checks.append(
            failed(
                "snapshot_meta_columns_have_tests",
                {"dbt_scd_id": sorted(scd_tests), "dbt_valid_to": sorted(valid_to_tests)},
                "dbt_scd_id unique/not_null and dbt_valid_to not_null",
            )
        )
    return checks, summary


def validate_history_model(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    model_path = project_root / "models" / "intermediate" / "int_subscription_history.sql"
    model_sql = model_path.read_text(encoding="utf-8")
    required_fragments = [
        "ref('subscription_status_snapshot')",
        "dbt_valid_from",
        "dbt_valid_to",
        "dbt_scd_id",
        "is_current",
        "9999-12-31",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in model_sql]
    if missing:
        checks.append(failed("history_model_uses_snapshot_meta_fields", missing, required_fragments, missing))
    else:
        checks.append(passed("history_model_uses_snapshot_meta_fields", required_fragments, "snapshot meta fields"))

    properties = read_yaml(project_root / "models" / "properties.yml")
    model = find_model(properties, HISTORY_MODEL_NAME)
    if model is None:
        checks.append(failed("history_model_properties_exist", None, HISTORY_MODEL_NAME))
        return checks, summary
    checks.append(passed("history_model_properties_exist", HISTORY_MODEL_NAME, HISTORY_MODEL_NAME))
    contract = ((model.get("meta") or {}).get("snapshot_contract") or {})
    summary["history_model_contract"] = contract
    if contract.get("snapshot_name") != SNAPSHOT_NAME or contract.get("check_cols") != EXPECTED_CHECK_COLS:
        checks.append(failed("history_model_repeats_snapshot_contract", contract, "matching snapshot contract"))
    else:
        checks.append(passed("history_model_repeats_snapshot_contract", contract, "matching snapshot contract"))

    required_tests = {
        "assert_subscription_history_has_one_current_row.sql",
        "assert_subscription_history_windows_do_not_overlap.sql",
        "assert_snapshot_does_not_version_noisy_updated_at.sql",
    }
    existing_tests = {path.name for path in (project_root / "tests").glob("*.sql")}
    missing_tests = sorted(required_tests - existing_tests)
    if missing_tests:
        checks.append(failed("snapshot_singular_tests_exist", missing_tests, sorted(required_tests), missing_tests))
    else:
        checks.append(passed("snapshot_singular_tests_exist", sorted(required_tests), "required singular tests"))
    return checks, summary


def validate_sources(project_root: Path) -> dict[str, Any]:
    sources = read_yaml(project_root / "models" / "sources.yml")
    subscriptions = None
    for source in sources.get("sources", []):
        if isinstance(source, dict) and source.get("name") == "raw_app":
            for table in source.get("tables", []):
                if isinstance(table, dict) and table.get("name") == "subscriptions":
                    subscriptions = table
                    break
    if subscriptions is None:
        return failed("subscription_source_unique_key_is_tested", None, "raw_app.subscriptions")
    key_tests = column_test_names(subscriptions, EXPECTED_UNIQUE_KEY)
    if {"unique", "not_null"}.issubset(key_tests):
        return passed("subscription_source_unique_key_is_tested", sorted(key_tests), "unique and not_null")
    return failed("subscription_source_unique_key_is_tested", sorted(key_tests), "unique and not_null")


def validate_snapshot_input_model(project_root: Path) -> dict[str, Any]:
    text = (project_root / "models" / "staging" / "stg_subscriptions.sql").read_text(encoding="utf-8")
    required_fragments = [
        "cast(nullif(cast(ended_at as varchar), '') as timestamptz) as ended_at",
        "cast(updated_at as timestamp) as updated_at",
    ]
    missing = [fragment for fragment in required_fragments if fragment not in text]
    if missing:
        return failed("subscription_staging_is_snapshot_safe", missing, required_fragments, missing)
    return passed("subscription_staging_is_snapshot_safe", required_fragments, "nullable timestamp and updated_at type")


def validate_runbook(runbook_path: Path) -> dict[str, Any]:
    if not runbook_path.is_file():
        return failed("snapshot_runbook_exists", str(runbook_path), "existing snapshot runbook")
    text = runbook_path.read_text(encoding="utf-8").lower()
    required_terms = [
        "dbt snapshot",
        SNAPSHOT_NAME,
        "unique_key",
        "check_cols",
        "updated_at",
        "dbt_valid_from",
        "dbt_valid_to",
        "noisy",
        "hard delete",
        "schedule",
    ]
    missing = [term for term in required_terms if term not in text]
    if missing:
        return failed("snapshot_runbook_exists", missing, required_terms, missing)
    return passed("snapshot_runbook_exists", required_terms, "runbook terms")


def validate_static_project(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"project_root": str(project_root)}
    if not project_root.is_dir():
        return [failed("project_root_exists", str(project_root), "existing directory")], summary
    checks.append(passed("project_root_exists", str(project_root), "existing directory"))

    required_files = [
        "dbt_project.yml",
        "profiles.yml.example",
        "commands.md",
        "snapshots/subscription_status_history.yml",
        "models/intermediate/int_subscription_history.sql",
        "models/properties.yml",
        "tests/assert_subscription_history_has_one_current_row.sql",
        "tests/assert_subscription_history_windows_do_not_overlap.sql",
        "tests/assert_snapshot_does_not_version_noisy_updated_at.sql",
    ]
    missing_files = [path for path in required_files if not (project_root / path).is_file()]
    if missing_files:
        checks.append(failed("required_project_files_exist", missing_files, required_files, missing_files))
        return checks, summary
    checks.append(passed("required_project_files_exist", required_files, "required files"))

    legacy_snapshot_sql = sorted(str(path.relative_to(project_root)) for path in (project_root / "snapshots").glob("*.sql"))
    if legacy_snapshot_sql:
        checks.append(failed("snapshots_use_yaml_not_legacy_sql", legacy_snapshot_sql, "YAML snapshot resources"))
    else:
        checks.append(passed("snapshots_use_yaml_not_legacy_sql", "ok", "YAML snapshot resources"))

    dbt_project = read_yaml(project_root / "dbt_project.yml")
    observed_project = {"name": dbt_project.get("name"), "profile": dbt_project.get("profile")}
    if observed_project != {"name": EXPECTED_PROJECT_NAME, "profile": EXPECTED_PROJECT_NAME}:
        checks.append(
            failed(
                "dbt_project_is_renamed",
                observed_project,
                {"name": EXPECTED_PROJECT_NAME, "profile": EXPECTED_PROJECT_NAME},
            )
        )
    else:
        checks.append(passed("dbt_project_is_renamed", observed_project, EXPECTED_PROJECT_NAME))

    snapshot_checks, snapshot_summary = validate_snapshot_yaml(project_root)
    history_checks, history_summary = validate_history_model(project_root)
    checks.extend(snapshot_checks)
    checks.extend(history_checks)
    checks.append(validate_sources(project_root))
    checks.append(validate_snapshot_input_model(project_root))
    checks.append(validate_runbook(project_root.parent / "snapshot_history_runbook.md"))
    summary.update(snapshot_summary)
    summary.update(history_summary)
    return checks, summary


def prepare_duckdb_database(db_path: Path, data_contract: dict[str, Any], data_dir: Path) -> dict[str, int]:
    import duckdb

    tables = data_contract_tables(data_contract)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("create schema if not exists raw")
        row_counts: dict[str, int] = {}
        for table_name in sorted(tables):
            safe_table = safe_identifier(table_name)
            csv_path = data_dir / f"{table_name}.csv"
            if not csv_path.is_file():
                raise FileNotFoundError(f"missing source CSV: {csv_path}")
            con.execute(
                f'create or replace table raw."{safe_table}" as select * from read_csv(?, delim=?, header=true, strict_mode=false)',
                [str(csv_path), ","],
            )
            row_counts[table_name] = con.execute(f'select count(*) from raw."{safe_table}"').fetchone()[0]
    finally:
        con.close()
    return row_counts


def read_csv_rows(csv_path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with csv_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        if reader.fieldnames is None:
            raise ValueError(f"{csv_path} has no header")
        return list(reader.fieldnames), rows


def write_csv_rows(csv_path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_initial_and_changed_data(data_dir: Path, tmp: Path) -> tuple[Path, Path]:
    initial = tmp / "data_initial"
    changed = tmp / "data_changed"
    shutil.copytree(data_dir, initial)
    shutil.copytree(data_dir, changed)
    subscription_csv = changed / "raw_subscriptions.csv"
    fieldnames, rows = read_csv_rows(subscription_csv)
    for row in rows:
        if row["subscription_id"] == "s001":
            row["updated_at"] = "2026-05-21T10:00:00+03:00"
        elif row["subscription_id"] == "s002":
            row["plan"] = "plus"
            row["updated_at"] = "2026-05-22T08:00:00+03:00"
        elif row["subscription_id"] == "s004":
            row["status"] = "cancelled"
            row["ended_at"] = "2026-05-21T09:30:00+03:00"
            row["updated_at"] = "2026-05-21T09:30:00+03:00"
    rows.append(
        {
            "subscription_id": "s005",
            "user_id": "u004",
            "plan": "basic",
            "status": "active",
            "started_at": "2026-05-22T11:00:00+03:00",
            "ended_at": "",
            "updated_at": "2026-05-22T11:00:00+03:00",
        }
    )
    write_csv_rows(subscription_csv, fieldnames, rows)
    return initial, changed


def tail(text: str, line_count: int = 8) -> str:
    lines = ANSI_RE.sub("", text).splitlines()
    return "\n".join(lines[-line_count:])


def run_command(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    return {
        "command": " ".join(command[:6]),
        "returncode": completed.returncode,
        "stdout_tail": tail(completed.stdout),
        "stderr_tail": tail(completed.stderr),
    }


def inspect_history_output(db_path: Path) -> dict[str, Any]:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            """
            select
                count(*) as row_count,
                count(distinct subscription_id) as subscription_count,
                sum(case when is_current then 1 else 0 end) as current_rows,
                sum(case when not is_current then 1 else 0 end) as closed_rows,
                sum(case when subscription_id = 's001' then 1 else 0 end) as s001_versions,
                sum(case when subscription_id = 's002' then 1 else 0 end) as s002_versions,
                sum(case when subscription_id = 's004' then 1 else 0 end) as s004_versions,
                sum(case when subscription_id = 's005' then 1 else 0 end) as s005_versions,
                sum(case when subscription_id = 's002' and is_current and plan = 'plus' then 1 else 0 end) as s002_current_plus,
                sum(case when subscription_id = 's004' and is_current and status = 'cancelled' then 1 else 0 end) as s004_current_cancelled
            from analytics.int_subscription_history
            """
        ).fetchone()
        overlap_count = con.execute(
            """
            with ordered_history as (
                select
                    subscription_id,
                    valid_from,
                    valid_to,
                    lead(valid_from) over (
                        partition by subscription_id
                        order by valid_from
                    ) as next_valid_from
                from analytics.int_subscription_history
            )
            select count(*)
            from ordered_history
            where next_valid_from is not null
                and valid_to != next_valid_from
            """
        ).fetchone()[0]
    finally:
        con.close()
    keys = [
        "row_count",
        "subscription_count",
        "current_rows",
        "closed_rows",
        "s001_versions",
        "s002_versions",
        "s004_versions",
        "s005_versions",
        "s002_current_plus",
        "s004_current_cancelled",
    ]
    output = {key: int(value or 0) for key, value in zip(keys, row)}
    output["overlap_count"] = int(overlap_count)
    return output


def run_snapshot_cycle(commands_base: list[str], env: dict[str, str]) -> list[dict[str, Any]]:
    return [
        run_command(["dbt", "run", "--exclude", HISTORY_MODEL_NAME, *commands_base], env),
        run_command(["dbt", "snapshot", "--select", SNAPSHOT_NAME, *commands_base], env),
        run_command(["dbt", "run", "--select", HISTORY_MODEL_NAME, *commands_base], env),
        run_command(["dbt", "test", "--select", "test_type:data", *commands_base], env),
    ]


def run_dbt_snapshot_audit(
    project_root: Path,
    data_contract: dict[str, Any],
    data_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    with TemporaryDirectory() as directory:
        tmp = Path(directory)
        project_copy = tmp / "project"
        profiles_dir = tmp / "profiles"
        shutil.copytree(project_root, project_copy)
        profiles_dir.mkdir()
        shutil.copy(project_copy / "profiles.yml.example", profiles_dir / "profiles.yml")
        initial_data, changed_data = build_initial_and_changed_data(data_dir, tmp)
        db_path = tmp / "snapshots.duckdb"
        env = os.environ.copy()
        env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
        env["DBT_DUCKDB_PATH"] = str(db_path)
        base = ["--project-dir", str(project_copy), "--profiles-dir", str(profiles_dir)]

        summary["initial_loaded_raw_rows"] = prepare_duckdb_database(db_path, data_contract, initial_data)
        parse_command = run_command(["dbt", "parse", *base], env)
        initial_commands = [parse_command, *run_snapshot_cycle(base, env)]
        summary["initial_dbt_commands"] = initial_commands
        if any(command["returncode"] != 0 for command in initial_commands):
            checks.append(failed("initial_snapshot_run_succeeds", initial_commands, "parse, run, snapshot, tests exit 0"))
            return checks, summary
        initial_output = inspect_history_output(db_path)
        summary["initial_history_output"] = initial_output
        expected_initial = {
            "row_count": 4,
            "subscription_count": 4,
            "current_rows": 4,
            "closed_rows": 0,
            "s001_versions": 1,
            "s002_versions": 1,
            "s004_versions": 1,
            "s005_versions": 0,
            "s002_current_plus": 0,
            "s004_current_cancelled": 0,
            "overlap_count": 0,
        }
        if initial_output != expected_initial:
            checks.append(failed("initial_snapshot_run_succeeds", initial_output, expected_initial))
            return checks, summary
        checks.append(passed("initial_snapshot_run_succeeds", initial_output, expected_initial))

        summary["changed_loaded_raw_rows"] = prepare_duckdb_database(db_path, data_contract, changed_data)
        changed_commands = run_snapshot_cycle(base, env)
        summary["changed_dbt_commands"] = changed_commands
        if any(command["returncode"] != 0 for command in changed_commands):
            checks.append(failed("second_snapshot_captures_business_changes", changed_commands, "run, snapshot, tests exit 0"))
            return checks, summary
        changed_output = inspect_history_output(db_path)
        summary["changed_history_output"] = changed_output
        expected_changed = {
            "row_count": 7,
            "subscription_count": 5,
            "current_rows": 5,
            "closed_rows": 2,
            "s001_versions": 1,
            "s002_versions": 2,
            "s004_versions": 2,
            "s005_versions": 1,
            "s002_current_plus": 1,
            "s004_current_cancelled": 1,
            "overlap_count": 0,
        }
        if changed_output != expected_changed:
            checks.append(failed("second_snapshot_captures_business_changes", changed_output, expected_changed))
        else:
            checks.append(passed("second_snapshot_captures_business_changes", changed_output, expected_changed))
    return checks, summary


def validate_project(
    project_root: Path,
    data_contract_path: Path,
    data_dir: Path | None = None,
    run_dbt: bool = False,
) -> dict[str, Any]:
    data_contract = read_json(data_contract_path)
    resolved_data_dir = data_dir or data_contract_path.parent / "tiny"
    checks, summary = validate_static_project(project_root)
    summary["data_contract"] = str(data_contract_path)
    summary["data_dir"] = str(resolved_data_dir)
    if run_dbt and all(check["valid"] for check in checks):
        live_checks, live_summary = run_dbt_snapshot_audit(project_root, data_contract, resolved_data_dir)
        checks.extend(live_checks)
        summary.update(live_summary)
    elif run_dbt:
        checks.append(failed("initial_snapshot_run_succeeds", "skipped because static checks failed", "dbt commands"))
    return {"valid": all(check["valid"] for check in checks), "summary": summary, "checks": checks}


def parse_args() -> argparse.Namespace:
    lesson_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Audit a dbt snapshot SCD type 2 history contract.")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parent / "snapshot_project",
        help="Path to the dbt project.",
    )
    parser.add_argument(
        "--data-contract",
        type=Path,
        default=lesson_root.parent / "data" / "contract.json",
        help="Path to the phase data contract.",
    )
    parser.add_argument("--data-dir", type=Path, help="Directory containing raw CSV files.")
    parser.add_argument("--output", type=Path, help="Optional path to write report JSON.")
    parser.add_argument("--run-dbt", action="store_true", help="Run live dbt snapshot history checks.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = validate_project(args.project, args.data_contract, data_dir=args.data_dir, run_dbt=args.run_dbt)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not report["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
