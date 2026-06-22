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


EXPECTED_PROJECT_NAME = "incremental_project"
MODEL_NAME = "fct_order_revenue_daily"
EXPECTED_UNIQUE_KEY = "revenue_date"
EXPECTED_LATE_WINDOW_DAYS = 2
EXPECTED_INCREMENTAL_STRATEGY = "delete+insert"
EXPECTED_SCHEMA_CHANGE_POLICY = "fail"
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


def model_config_text_is_valid(sql_text: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    required_fragments = {
        "materialized_incremental": "materialized='incremental'",
        "unique_key": "unique_key='revenue_date'",
        "incremental_strategy": "incremental_strategy='delete+insert'",
        "schema_change_policy": "on_schema_change='fail'",
        "is_incremental_guard": "is_incremental()",
        "target_relation": "{{ this }}",
        "late_window": "interval '2 days'",
        "safe_empty_target": "date '1900-01-01'",
    }
    missing = [
        {"fragment": name, "expected": value}
        for name, value in required_fragments.items()
        if value not in sql_text
    ]
    if missing:
        checks.append(failed("incremental_model_sql_declares_contract", missing, required_fragments, missing))
    else:
        checks.append(passed("incremental_model_sql_declares_contract", sorted(required_fragments), "required fragments"))

    if "group by orders.order_date" not in sql_text or "orders.order_date as revenue_date" not in sql_text:
        checks.append(
            failed(
                "incremental_model_keeps_daily_grain",
                "missing date grain fragments",
                "one row per revenue_date",
                ["fct_order_revenue_daily.sql"],
            )
        )
    else:
        checks.append(passed("incremental_model_keeps_daily_grain", "revenue_date", "one row per date"))
    return checks


def find_model(properties: dict[str, Any], name: str) -> dict[str, Any] | None:
    for item in properties.get("models", []):
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def test_names_for_column(model: dict[str, Any], column_name: str) -> set[str]:
    for column in model.get("columns", []):
        if isinstance(column, dict) and column.get("name") == column_name:
            names: set[str] = set()
            for item in column.get("data_tests", []):
                if isinstance(item, str):
                    names.add(item)
                elif isinstance(item, dict) and item:
                    names.add(next(iter(item)))
            return names
    return set()


def validate_model_properties(properties_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    properties = read_yaml(properties_path)
    model = find_model(properties, MODEL_NAME)
    if model is None:
        return [failed("incremental_model_properties_exist", None, MODEL_NAME)], {}

    checks: list[dict[str, Any]] = [passed("incremental_model_properties_exist", MODEL_NAME, MODEL_NAME)]
    summary: dict[str, Any] = {"model_description": model.get("description")}
    config = model.get("config") or {}
    expected_config = {
        "materialized": "incremental",
        "unique_key": EXPECTED_UNIQUE_KEY,
        "incremental_strategy": EXPECTED_INCREMENTAL_STRATEGY,
        "on_schema_change": EXPECTED_SCHEMA_CHANGE_POLICY,
    }
    config_errors = [
        {"key": key, "observed": config.get(key), "expected": value}
        for key, value in expected_config.items()
        if config.get(key) != value
    ]
    if config_errors:
        checks.append(failed("properties_repeat_incremental_config", config_errors, expected_config, config_errors))
    else:
        checks.append(passed("properties_repeat_incremental_config", expected_config, expected_config))

    meta = model.get("meta") or {}
    contract = meta.get("incremental_contract") or {}
    summary["incremental_contract"] = contract
    expected_contract = {
        "event_time_column": EXPECTED_UNIQUE_KEY,
        "unique_key": EXPECTED_UNIQUE_KEY,
        "late_arrival_window_days": EXPECTED_LATE_WINDOW_DAYS,
        "incremental_strategy": EXPECTED_INCREMENTAL_STRATEGY,
        "schema_change_policy": EXPECTED_SCHEMA_CHANGE_POLICY,
    }
    contract_errors = [
        {"key": key, "observed": contract.get(key), "expected": value}
        for key, value in expected_contract.items()
        if contract.get(key) != value
    ]
    text_fields = " ".join(str(contract.get(key, "")) for key in ["full_refresh_policy", "backfill_command", "duplicate_policy"])
    if "--full-refresh" not in text_fields or EXPECTED_UNIQUE_KEY not in text_fields:
        contract_errors.append({"key": "runbook_text", "observed": text_fields, "expected": "--full-refresh and unique_key"})
    if contract_errors:
        checks.append(failed("incremental_contract_meta_is_complete", contract_errors, expected_contract, contract_errors))
    else:
        checks.append(passed("incremental_contract_meta_is_complete", contract, expected_contract))

    revenue_date_tests = test_names_for_column(model, EXPECTED_UNIQUE_KEY)
    if {"unique", "not_null"}.issubset(revenue_date_tests):
        checks.append(passed("unique_key_has_data_tests", sorted(revenue_date_tests), "unique and not_null"))
    else:
        checks.append(
            failed("unique_key_has_data_tests", sorted(revenue_date_tests), "unique and not_null", [EXPECTED_UNIQUE_KEY])
        )
    return checks, summary


def validate_playbook(playbook_path: Path) -> dict[str, Any]:
    if not playbook_path.is_file():
        return failed("backfill_full_refresh_playbook_exists", str(playbook_path), "existing playbook")
    text = playbook_path.read_text(encoding="utf-8").lower()
    required_terms = [
        MODEL_NAME,
        "--full-refresh",
        "unique_key",
        "late-arriving",
        "schema change",
        "backfill",
        "duplicate",
    ]
    missing = [term for term in required_terms if term not in text]
    if missing:
        return failed("backfill_full_refresh_playbook_exists", missing, required_terms, missing)
    return passed("backfill_full_refresh_playbook_exists", required_terms, "runbook terms")


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
        "models/marts/fct_order_revenue_daily.sql",
        "models/properties.yml",
        "tests/assert_daily_revenue_reconciles.sql",
    ]
    missing_files = [path for path in required_files if not (project_root / path).is_file()]
    if missing_files:
        checks.append(failed("required_project_files_exist", missing_files, required_files, missing_files))
        return checks, summary
    checks.append(passed("required_project_files_exist", required_files, "required files"))

    dbt_project = read_yaml(project_root / "dbt_project.yml")
    project_observed = {"name": dbt_project.get("name"), "profile": dbt_project.get("profile")}
    if project_observed != {"name": EXPECTED_PROJECT_NAME, "profile": EXPECTED_PROJECT_NAME}:
        checks.append(
            failed(
                "dbt_project_is_renamed",
                project_observed,
                {"name": EXPECTED_PROJECT_NAME, "profile": EXPECTED_PROJECT_NAME},
            )
        )
    else:
        checks.append(passed("dbt_project_is_renamed", project_observed, EXPECTED_PROJECT_NAME))

    model_sql = (project_root / "models" / "marts" / "fct_order_revenue_daily.sql").read_text(encoding="utf-8")
    checks.extend(model_config_text_is_valid(model_sql))

    property_checks, property_summary = validate_model_properties(project_root / "models" / "properties.yml")
    checks.extend(property_checks)
    summary.update(property_summary)

    test_sql = (project_root / "tests" / "assert_daily_revenue_reconciles.sql").read_text(encoding="utf-8")
    required_test_fragments = [MODEL_NAME, "stg_orders", "full outer join", "expected_paid_revenue_rub"]
    missing_test_fragments = [fragment for fragment in required_test_fragments if fragment not in test_sql]
    if missing_test_fragments:
        checks.append(
            failed("daily_revenue_reconciliation_test_exists", missing_test_fragments, required_test_fragments)
        )
    else:
        checks.append(passed("daily_revenue_reconciliation_test_exists", required_test_fragments, "source reconciliation"))

    checks.append(validate_playbook(project_root.parent / "backfill_full_refresh_playbook.md"))
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
            row_counts[table_name] = con.execute(
                f'select count(*) from raw."{safe_table}"'
            ).fetchone()[0]
    finally:
        con.close()
    return row_counts


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


def copy_csv_dir(data_dir: Path, destination: Path) -> None:
    shutil.copytree(data_dir, destination)


def rewrite_csv_without_order(csv_path: Path, order_id: str) -> None:
    with csv_path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
        fieldnames = source.readline()
    if not rows:
        return
    columns = list(rows[0].keys())
    filtered = [row for row in rows if row.get("order_id") != order_id]
    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        writer.writerows(filtered)


def append_csv_row(csv_path: Path, row: dict[str, str]) -> None:
    with csv_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        fieldnames = reader.fieldnames
    if fieldnames is None:
        raise ValueError(f"{csv_path} has no header")
    existing_text = csv_path.read_text(encoding="utf-8")
    with csv_path.open("a", newline="", encoding="utf-8") as target:
        if existing_text and not existing_text.endswith("\n"):
            target.write("\n")
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writerow(row)


def build_initial_and_incremental_data(data_dir: Path, tmp: Path) -> tuple[Path, Path]:
    initial = tmp / "data_initial"
    incremental = tmp / "data_incremental"
    copy_csv_dir(data_dir, initial)
    copy_csv_dir(data_dir, incremental)
    rewrite_csv_without_order(initial / "raw_orders.csv", "o004")
    rewrite_csv_without_order(initial / "raw_order_items.csv", "o004")
    append_csv_row(
        incremental / "raw_orders.csv",
        {
            "order_id": "o005",
            "user_id": "u002",
            "ordered_at": "2026-05-03T21:00:00+03:00",
            "status": "paid",
            "currency": "RUB",
            "amount": "100.00",
            "updated_at": "2026-05-07T20:00:00+03:00",
        },
    )
    append_csv_row(
        incremental / "raw_order_items.csv",
        {
            "order_id": "o005",
            "line_number": "1",
            "product_id": "p_addon",
            "quantity": "1",
            "unit_price": "100.00",
            "currency": "RUB",
            "loaded_at": "2026-05-07T20:01:00+03:00",
        },
    )
    return initial, incremental


def inspect_fct_output(db_path: Path) -> dict[str, Any]:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            """
            select
                count(*) as row_count,
                cast(sum(paid_revenue_rub) as decimal(18, 2)) as paid_revenue_rub,
                cast(sum(case when revenue_date = date '2026-05-03' then paid_revenue_rub else 0 end) as decimal(18, 2)) as may_03_paid_revenue_rub,
                count(*) - count(distinct revenue_date) as duplicate_date_rows
            from analytics.fct_order_revenue_daily
            """
        ).fetchone()
    finally:
        con.close()
    return {
        "row_count": int(row[0]),
        "paid_revenue_rub": str(row[1]),
        "may_03_paid_revenue_rub": str(row[2]),
        "duplicate_date_rows": int(row[3]),
    }


def compiled_incremental_sql(project_copy: Path) -> str:
    compiled_root = project_copy / "target" / "compiled" / EXPECTED_PROJECT_NAME
    candidates = sorted(compiled_root.rglob(f"{MODEL_NAME}.sql"))
    if not candidates:
        return ""
    return candidates[0].read_text(encoding="utf-8")


def run_dbt_incremental_audit(
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
        initial_data, incremental_data = build_initial_and_incremental_data(data_dir, tmp)
        db_path = tmp / "incremental.duckdb"

        env = os.environ.copy()
        env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
        env["DBT_DUCKDB_PATH"] = str(db_path)
        base = ["--project-dir", str(project_copy), "--profiles-dir", str(profiles_dir)]

        summary["initial_loaded_raw_rows"] = prepare_duckdb_database(db_path, data_contract, initial_data)
        initial_commands = [
            run_command(["dbt", "parse", *base], env),
            run_command(["dbt", "run", "--full-refresh", *base], env),
            run_command(["dbt", "test", "--select", "test_type:data", *base], env),
        ]
        summary["initial_dbt_commands"] = initial_commands
        if any(command["returncode"] != 0 for command in initial_commands):
            checks.append(
                failed("initial_full_refresh_succeeds", initial_commands, "parse, full-refresh run and tests exit 0")
            )
            return checks, summary
        initial_output = inspect_fct_output(db_path)
        summary["initial_fct_output"] = initial_output
        expected_initial = {
            "row_count": 3,
            "paid_revenue_rub": "2000.00",
            "may_03_paid_revenue_rub": "800.00",
            "duplicate_date_rows": 0,
        }
        if initial_output != expected_initial:
            checks.append(failed("initial_full_refresh_succeeds", initial_output, expected_initial))
            return checks, summary
        checks.append(passed("initial_full_refresh_succeeds", initial_output, expected_initial))

        summary["incremental_loaded_raw_rows"] = prepare_duckdb_database(db_path, data_contract, incremental_data)
        incremental_commands = [
            run_command(["dbt", "run", *base], env),
            run_command(["dbt", "test", "--select", "test_type:data", *base], env),
        ]
        summary["incremental_dbt_commands"] = incremental_commands
        if any(command["returncode"] != 0 for command in incremental_commands):
            checks.append(
                failed("incremental_run_succeeds_after_late_arrival", incremental_commands, "incremental run and tests exit 0")
            )
            return checks, summary
        incremental_output = inspect_fct_output(db_path)
        summary["incremental_fct_output"] = incremental_output
        expected_incremental = {
            "row_count": 4,
            "paid_revenue_rub": "4412.50",
            "may_03_paid_revenue_rub": "900.00",
            "duplicate_date_rows": 0,
        }
        if incremental_output != expected_incremental:
            checks.append(
                failed(
                    "incremental_run_succeeds_after_late_arrival",
                    incremental_output,
                    expected_incremental,
                )
            )
        else:
            checks.append(
                passed("incremental_run_succeeds_after_late_arrival", incremental_output, expected_incremental)
            )

        compiled_sql = compiled_incremental_sql(project_copy)
        unresolved_tokens = [token for token in ["{{", "{%", "is_incremental()"] if token in compiled_sql]
        if unresolved_tokens:
            checks.append(failed("compiled_incremental_sql_is_plain_sql", unresolved_tokens, "no Jinja tokens"))
        elif "interval '2 days'" not in compiled_sql:
            checks.append(
                failed("compiled_incremental_sql_is_plain_sql", "missing late window", "compiled SQL contains late window")
            )
        else:
            checks.append(passed("compiled_incremental_sql_is_plain_sql", "plain SQL with late window", "no Jinja tokens"))

        full_refresh_commands = [
            run_command(["dbt", "run", "--full-refresh", "--select", MODEL_NAME, *base], env),
            run_command(["dbt", "test", "--select", "test_type:data", *base], env),
        ]
        summary["final_full_refresh_commands"] = full_refresh_commands
        if any(command["returncode"] != 0 for command in full_refresh_commands):
            checks.append(failed("documented_full_refresh_succeeds", full_refresh_commands, "full-refresh run and tests exit 0"))
            return checks, summary
        full_refresh_output = inspect_fct_output(db_path)
        summary["final_full_refresh_output"] = full_refresh_output
        if full_refresh_output != expected_incremental:
            checks.append(failed("documented_full_refresh_succeeds", full_refresh_output, expected_incremental))
        else:
            checks.append(passed("documented_full_refresh_succeeds", full_refresh_output, expected_incremental))
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
        live_checks, live_summary = run_dbt_incremental_audit(project_root, data_contract, resolved_data_dir)
        checks.extend(live_checks)
        summary.update(live_summary)
    elif run_dbt:
        checks.append(failed("initial_full_refresh_succeeds", "skipped because static checks failed", "dbt commands"))
    return {"valid": all(check["valid"] for check in checks), "summary": summary, "checks": checks}


def parse_args() -> argparse.Namespace:
    lesson_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Audit a dbt incremental model contract and live late-arrival behavior.")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parent / "incremental_project",
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
    parser.add_argument("--run-dbt", action="store_true", help="Run live dbt full-refresh and incremental checks.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = validate_project(
        args.project,
        args.data_contract,
        data_dir=args.data_dir,
        run_dbt=args.run_dbt,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not report["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
