from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml


SOURCE_NAME = "raw_app"
EXPECTED_MACROS = {
    "normalize_status": ["column_name"],
    "normalize_currency": ["column_name"],
    "to_decimal": ["column_name", "precision", "scale"],
    "money_product": ["quantity_column", "unit_price_column", "precision", "scale"],
    "rub_amount": ["amount_column", "rate_column", "precision", "scale"],
}
MIN_MACRO_CALLS = {
    "normalize_status": 3,
    "normalize_currency": 4,
    "to_decimal": 10,
    "money_product": 1,
    "rub_amount": 3,
}
FORBIDDEN_BUSINESS_MACRO_RE = re.compile(
    r"(customer|health|segment|subscription|paid_revenue|refund_policy|lifecycle)",
    flags=re.IGNORECASE,
)
MACRO_DEF_RE = re.compile(r"{%-?\s*macro\s+([A-Za-z_][A-Za-z0-9_]*)\(([^)]*)\)\s*-?%}")
MACRO_CALL_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\(")
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


def data_contract_tables(data_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = data_contract.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("data contract must contain a tables object")
    return {str(name): table for name, table in tables.items() if isinstance(table, dict)}


def safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"unsafe SQL identifier: {value}")
    return value


def macro_args(raw_args: str) -> list[str]:
    args: list[str] = []
    for raw in raw_args.split(","):
        cleaned = raw.strip()
        if cleaned:
            args.append(cleaned.split("=", 1)[0].strip())
    return args


def collect_macro_inventory(project_root: Path) -> dict[str, Any]:
    definitions: dict[str, dict[str, Any]] = {}
    macro_files: dict[str, str] = {}
    for path in sorted((project_root / "macros").glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        macro_files[path.name] = text
        for match in MACRO_DEF_RE.finditer(text):
            definitions[match.group(1)] = {
                "file": str(path.relative_to(project_root)),
                "args": macro_args(match.group(2)),
            }

    calls: Counter[str] = Counter()
    call_locations: dict[str, list[str]] = {name: [] for name in EXPECTED_MACROS}
    for path in sorted((project_root / "models").rglob("*.sql")) + sorted((project_root / "tests").rglob("*.sql")):
        text = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(project_root))
        for match in MACRO_CALL_RE.finditer(text):
            name = match.group(1)
            if name in EXPECTED_MACROS:
                calls[name] += 1
                call_locations.setdefault(name, []).append(relative)

    docs: dict[str, Any] = {}
    for path in sorted((project_root / "macros").glob("*.yml")):
        value = read_yaml(path)
        for macro in value.get("macros", []):
            if isinstance(macro, dict) and macro.get("name"):
                docs[str(macro["name"])] = macro

    return {
        "definitions": definitions,
        "macro_files": macro_files,
        "calls": dict(sorted(calls.items())),
        "call_locations": {name: sorted(set(paths)) for name, paths in call_locations.items() if paths},
        "docs": docs,
    }


def validate_macro_definitions(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    definitions = inventory["definitions"]
    missing = sorted(set(EXPECTED_MACROS) - set(definitions))
    arg_errors = [
        {"macro": name, "observed": definitions.get(name, {}).get("args"), "expected": args}
        for name, args in EXPECTED_MACROS.items()
        if name in definitions and definitions[name]["args"] != args
    ]
    if missing or arg_errors:
        checks.append(
            failed(
                "expected_macros_defined",
                {"missing": missing, "arg_errors": arg_errors},
                EXPECTED_MACROS,
                missing + arg_errors,
            )
        )
    else:
        checks.append(passed("expected_macros_defined", sorted(EXPECTED_MACROS), "expected macro names and arguments"))

    whitespace_errors = [
        filename
        for filename, text in inventory["macro_files"].items()
        if "{%- macro" not in text or "{%- endmacro -%}" not in text
    ]
    if whitespace_errors:
        checks.append(
            failed(
                "macros_use_whitespace_control",
                whitespace_errors,
                "Jinja whitespace control around macro blocks",
                whitespace_errors,
            )
        )
    else:
        checks.append(passed("macros_use_whitespace_control", sorted(inventory["macro_files"]), "whitespace control"))
    return checks


def validate_macro_docs(inventory: dict[str, Any]) -> dict[str, Any]:
    docs = inventory["docs"]
    errors: list[dict[str, Any]] = []
    documented_summary: dict[str, Any] = {}
    for name, expected_args in EXPECTED_MACROS.items():
        macro_doc = docs.get(name)
        if not macro_doc:
            errors.append({"macro": name, "error": "missing macro documentation"})
            continue
        actual_args = [
            arg.get("name")
            for arg in macro_doc.get("arguments", [])
            if isinstance(arg, dict)
        ]
        documented_summary[name] = actual_args
        meta = ((macro_doc.get("config") or {}).get("meta") or {})
        if actual_args != expected_args:
            errors.append({"macro": name, "observed": actual_args, "expected": expected_args})
        if not macro_doc.get("description") or meta.get("abstraction_level") != "low_level_sql":
            errors.append({"macro": name, "error": "description and low_level_sql meta are required"})
        for arg in macro_doc.get("arguments", []):
            if not isinstance(arg, dict) or not arg.get("type") or not arg.get("description"):
                errors.append({"macro": name, "argument": arg.get("name") if isinstance(arg, dict) else None})
    if errors:
        return failed("macro_arguments_are_documented", errors, "macro docs with matching arguments", errors[:5])
    return passed("macro_arguments_are_documented", documented_summary, "macro docs with matching arguments")


def validate_macro_usage(project_root: Path, inventory: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    calls = inventory["calls"]
    missing_usage = [
        {"macro": name, "observed": calls.get(name, 0), "expected_min": minimum}
        for name, minimum in MIN_MACRO_CALLS.items()
        if calls.get(name, 0) < minimum
    ]
    if missing_usage:
        checks.append(failed("macro_usage_is_intentional", missing_usage, MIN_MACRO_CALLS, missing_usage))
    else:
        checks.append(passed("macro_usage_is_intentional", calls, MIN_MACRO_CALLS))

    forbidden_macros = sorted(name for name in inventory["definitions"] if FORBIDDEN_BUSINESS_MACRO_RE.search(name))
    mart_text = (project_root / "models" / "marts" / "mart_customer_revenue_health.sql").read_text(encoding="utf-8")
    mart_keeps_business_case = (
        "revenue_health_segment" in mart_text
        and "case" in mart_text
        and "when coalesce(sum(orders.refunded_amount_rub), 0) > 0" in mart_text
        and "when orders.status = 'paid'" in mart_text
    )
    if forbidden_macros or not mart_keeps_business_case:
        checks.append(
            failed(
                "business_logic_stays_out_of_macros",
                {"forbidden_macros": forbidden_macros, "mart_keeps_business_case": mart_keeps_business_case},
                "no business-policy macros and visible mart case expressions",
                forbidden_macros or ["mart_customer_revenue_health"],
            )
        )
    else:
        checks.append(passed("business_logic_stays_out_of_macros", "ok", "visible mart business logic"))
    return checks


def validate_static_project(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"project_root": str(project_root)}
    if not project_root.is_dir():
        return [failed("project_root_exists", str(project_root), "existing directory")], summary
    checks.append(passed("project_root_exists", str(project_root), "existing directory"))

    required_files = [
        "dbt_project.yml",
        "profiles.yml.example",
        "macros/normalization.sql",
        "macros/properties.yml",
        "models/marts/mart_customer_revenue_health.sql",
        "tests/assert_paid_revenue_reconciles.sql",
    ]
    missing_files = [path for path in required_files if not (project_root / path).is_file()]
    if missing_files:
        checks.append(failed("required_project_files_exist", missing_files, required_files, missing_files))
        return checks, summary
    checks.append(passed("required_project_files_exist", required_files, "required files"))

    checklist = project_root.parent / "compiled_sql_review_checklist.json"
    if not checklist.is_file():
        checks.append(failed("compiled_sql_review_checklist_exists", str(checklist), "existing JSON checklist"))
    else:
        checklist_value = read_json(checklist)
        rules = checklist_value.get("rules", [])
        required_rule_count = sum(1 for rule in rules if isinstance(rule, dict) and rule.get("required"))
        summary["review_checklist_rules"] = required_rule_count
        if required_rule_count < 5:
            checks.append(
                failed("compiled_sql_review_checklist_exists", required_rule_count, "at least five required rules", rules)
            )
        else:
            checks.append(passed("compiled_sql_review_checklist_exists", required_rule_count, "required rules"))

    inventory = collect_macro_inventory(project_root)
    summary["macro_definitions"] = inventory["definitions"]
    summary["macro_calls"] = inventory["calls"]
    summary["macro_call_locations"] = inventory["call_locations"]
    checks.extend(validate_macro_definitions(inventory))
    checks.append(validate_macro_docs(inventory))
    checks.extend(validate_macro_usage(project_root, inventory))
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
                f'create or replace table raw."{safe_table}" as select * from read_csv_auto(?)',
                [str(csv_path)],
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
        "command": " ".join(command[:3]),
        "returncode": completed.returncode,
        "stdout_tail": tail(completed.stdout),
        "stderr_tail": tail(completed.stderr),
    }


def compiled_sql_files(project_copy: Path) -> dict[str, str]:
    compiled_root = project_copy / "target" / "compiled" / "macro_project"
    files: dict[str, str] = {}
    for path in sorted(compiled_root.rglob("*.sql")):
        relative = str(path.relative_to(compiled_root))
        if relative.startswith("models/") and ".yml/" not in relative:
            files[relative] = path.read_text(encoding="utf-8")
    return files


def max_blank_streak(text: str) -> int:
    longest = 0
    current = 0
    for line in text.splitlines():
        if line.strip():
            longest = max(longest, current)
            current = 0
        else:
            current += 1
    return max(longest, current)


def inspect_compiled_sql(compiled: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    macro_names = set(EXPECTED_MACROS)
    for relative, text in compiled.items():
        if "{{" in text or "{%" in text:
            unresolved.append({"file": relative, "token": "jinja"})
        for name in macro_names:
            if f"{name}(" in text:
                unresolved.append({"file": relative, "token": name})
    if unresolved:
        checks.append(failed("compiled_sql_has_no_jinja", unresolved, "compiled SQL without Jinja", unresolved[:5]))
    else:
        checks.append(passed("compiled_sql_has_no_jinja", "ok", "compiled SQL without Jinja"))

    expected_fragments = {
        "models/staging/stg_orders.sql": [
            "lower(status) as status",
            "upper(currency) as currency",
            "cast(amount as decimal(18, 2)) as amount",
        ],
        "models/staging/stg_currency_rates.sql": [
            "cast(rate_to_rub as decimal(18, 4)) as rate_to_rub",
        ],
        "models/intermediate/int_order_line_revenue.sql": [
            "cast(items.quantity * items.unit_price as decimal(18, 2)) as line_revenue_native",
        ],
        "models/marts/mart_customer_revenue_health.sql": [
            "cast(orders.gross_amount_native * rates.rate_to_rub as decimal(18, 2)) as gross_revenue_rub",
            "when orders.status = 'paid'",
            "revenue_health_segment",
        ],
    }
    missing_fragments: list[dict[str, Any]] = []
    for relative, fragments in expected_fragments.items():
        text = compiled.get(relative, "")
        for fragment in fragments:
            if fragment not in text:
                missing_fragments.append({"file": relative, "missing": fragment})
    if missing_fragments:
        checks.append(
            failed("compiled_fragments_match_expected_sql", missing_fragments, "expected SQL fragments", missing_fragments)
        )
    else:
        checks.append(passed("compiled_fragments_match_expected_sql", expected_fragments, "expected SQL fragments"))

    readability_errors = [
        {"file": relative, "blank_streak": max_blank_streak(text), "line_count": len(text.splitlines())}
        for relative, text in compiled.items()
        if max_blank_streak(text) > 2 or len(text.splitlines()) > 140
    ]
    if readability_errors:
        checks.append(failed("compiled_sql_is_reviewable", readability_errors, "compact compiled SQL", readability_errors))
    else:
        checks.append(passed("compiled_sql_is_reviewable", len(compiled), "compact compiled SQL"))

    return checks, {
        "compiled_file_count": len(compiled),
        "compiled_models": sorted(compiled),
        "compiled_mart_line_count": len(compiled.get("models/marts/mart_customer_revenue_health.sql", "").splitlines()),
    }


def inspect_mart_output(db_path: Path) -> dict[str, Any]:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        row = con.execute(
            """
            select
                count(*) as row_count,
                cast(sum(paid_revenue_rub) as decimal(18, 2)) as paid_revenue_rub
            from analytics.mart_customer_revenue_health
            """
        ).fetchone()
    finally:
        con.close()
    return {"row_count": int(row[0]), "paid_revenue_rub": str(row[1])}


def run_dbt_audit(project_root: Path, data_contract: dict[str, Any], data_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    with TemporaryDirectory() as directory:
        tmp = Path(directory)
        project_copy = tmp / "project"
        profiles_dir = tmp / "profiles"
        shutil.copytree(project_root, project_copy)
        profiles_dir.mkdir()
        shutil.copy(project_copy / "profiles.yml.example", profiles_dir / "profiles.yml")
        db_path = tmp / "macros.duckdb"
        summary["loaded_raw_rows"] = prepare_duckdb_database(db_path, data_contract, data_dir)

        env = os.environ.copy()
        env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
        env["DBT_DUCKDB_PATH"] = str(db_path)
        base = ["--project-dir", str(project_copy), "--profiles-dir", str(profiles_dir)]
        commands = [
            run_command(["dbt", "parse", *base], env),
            run_command(["dbt", "compile", *base], env),
            run_command(["dbt", "run", *base], env),
            run_command(["dbt", "test", "--select", "test_type:data", *base], env),
        ]
        summary["dbt_commands"] = commands
        if any(command["returncode"] != 0 for command in commands):
            checks.append(failed("dbt_parse_compile_run_test_succeed", commands, "all dbt commands exit 0", commands))
            return checks, summary
        checks.append(passed("dbt_parse_compile_run_test_succeed", "ok", "all dbt commands exit 0"))

        compiled_checks, compiled_summary = inspect_compiled_sql(compiled_sql_files(project_copy))
        checks.extend(compiled_checks)
        summary.update(compiled_summary)

        mart_output = inspect_mart_output(db_path)
        summary["mart_output"] = mart_output
        if mart_output != {"row_count": 5, "paid_revenue_rub": "4312.50"}:
            checks.append(
                failed("mart_output_matches_macro_baseline", mart_output, {"row_count": 5, "paid_revenue_rub": "4312.50"})
            )
        else:
            checks.append(passed("mart_output_matches_macro_baseline", mart_output, "expected mart output"))
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
        live_checks, live_summary = run_dbt_audit(project_root, data_contract, resolved_data_dir)
        checks.extend(live_checks)
        summary.update(live_summary)
    elif run_dbt:
        checks.append(failed("dbt_parse_compile_run_test_succeed", "skipped because static checks failed", "dbt commands"))
    return {"valid": all(check["valid"] for check in checks), "summary": summary, "checks": checks}


def parse_args() -> argparse.Namespace:
    lesson_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Audit dbt macros, documentation and compiled SQL readability.")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parent / "macro_project",
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
    parser.add_argument("--run-dbt", action="store_true", help="Run dbt compile, run and data tests.")
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
