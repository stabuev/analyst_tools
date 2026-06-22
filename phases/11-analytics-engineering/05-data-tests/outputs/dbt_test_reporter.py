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
GENERIC_TEST_TYPES = {"not_null", "unique", "relationships", "accepted_values"}
EXPECTED_SINGULAR_TESTS = {
    "assert_paid_revenue_reconciles": "contract_gate",
    "assert_no_many_to_many_revenue_join": "contract_gate",
    "warn_customers_without_subscription": "warning_diagnostic",
}
WARNING_TESTS = {
    name for name, classification in EXPECTED_SINGULAR_TESTS.items() if classification == "warning_diagnostic"
}
CONTRACT_TESTS = {
    name for name, classification in EXPECTED_SINGULAR_TESTS.items() if classification == "contract_gate"
}
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
CONFIG_WARN_RE = re.compile(r"config\([^)]*severity\s*=\s*['\"]warn['\"]", flags=re.IGNORECASE | re.DOTALL)


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


def yaml_files(project_root: Path) -> list[Path]:
    return sorted((project_root / "models").rglob("*.yml")) + sorted((project_root / "tests").rglob("*.yml"))


def iter_mappings(value: Any) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    if isinstance(value, dict):
        mappings.append(value)
        for nested in value.values():
            mappings.extend(iter_mappings(nested))
    elif isinstance(value, list):
        for nested in value:
            mappings.extend(iter_mappings(nested))
    return mappings


def extract_data_tests(value: Any) -> list[Any]:
    tests: list[Any] = []
    if isinstance(value, dict):
        if isinstance(value.get("data_tests"), list):
            tests.extend(value["data_tests"])
        for nested in value.values():
            tests.extend(extract_data_tests(nested))
    elif isinstance(value, list):
        for nested in value:
            tests.extend(extract_data_tests(nested))
    return tests


def test_name(test: Any) -> str | None:
    if isinstance(test, str):
        return test
    if isinstance(test, dict) and test:
        return str(next(iter(test)))
    return None


def collect_declared_tests(project_root: Path) -> dict[str, Any]:
    generic_counts: Counter[str] = Counter()
    legacy_tests_keys: list[str] = []
    data_test_instances = 0
    for path in yaml_files(project_root):
        value = read_yaml(path)
        relative = str(path.relative_to(project_root))
        for mapping in iter_mappings(value):
            if "tests" in mapping:
                legacy_tests_keys.append(relative)
        for item in extract_data_tests(value):
            name = test_name(item)
            if name in GENERIC_TEST_TYPES:
                generic_counts[name] += 1
                data_test_instances += 1
    singular_sql = sorted(path.stem for path in (project_root / "tests").glob("*.sql"))
    singular_descriptions = {
        item.get("name"): item.get("description")
        for path in sorted((project_root / "tests").glob("*.yml"))
        for item in read_yaml(path).get("data_tests", [])
        if isinstance(item, dict)
    }
    return {
        "generic_counts": dict(sorted(generic_counts.items())),
        "legacy_tests_keys": sorted(set(legacy_tests_keys)),
        "data_test_instances": data_test_instances,
        "singular_sql": singular_sql,
        "singular_descriptions": singular_descriptions,
    }


def validate_source_freshness_config(project_root: Path, data_contract: dict[str, Any]) -> dict[str, Any]:
    expected_tables = {name.removeprefix("raw_"): table for name, table in data_contract_tables(data_contract).items()}
    source_decl: dict[str, Any] | None = None
    for path in sorted((project_root / "models").rglob("*.yml")):
        value = read_yaml(path)
        for source in value.get("sources", []):
            if isinstance(source, dict) and source.get("name") == SOURCE_NAME:
                source_decl = source
                break
    if source_decl is None:
        return failed("sources_have_freshness_config", None, f"source {SOURCE_NAME}", [SOURCE_NAME])
    errors: list[dict[str, Any]] = []
    for table in source_decl.get("tables", []):
        if not isinstance(table, dict):
            continue
        name = table.get("name")
        config = table.get("config") if isinstance(table.get("config"), dict) else {}
        freshness = config.get("freshness") if isinstance(config.get("freshness"), dict) else {}
        contract_table = expected_tables.get(str(name), {})
        if config.get("loaded_at_field") != contract_table.get("freshness_column"):
            errors.append(
                {
                    "source": name,
                    "observed": config.get("loaded_at_field"),
                    "expected": contract_table.get("freshness_column"),
                }
            )
        if "warn_after" not in freshness or "error_after" not in freshness:
            errors.append({"source": name, "observed": sorted(freshness), "expected": ["warn_after", "error_after"]})
    if errors:
        return failed("sources_have_freshness_config", errors, "loaded_at_field plus warn/error thresholds", errors)
    return passed("sources_have_freshness_config", len(expected_tables), "all sources")


def validate_static_project(project_root: Path, data_contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"project_root": str(project_root)}
    if not project_root.is_dir():
        return [failed("project_root_exists", str(project_root), "existing directory")], summary
    checks.append(passed("project_root_exists", str(project_root), "existing directory"))

    required_files = [
        "dbt_project.yml",
        "profiles.yml.example",
        "models/sources.yml",
        "models/properties.yml",
        "tests/schema.yml",
        "tests/assert_paid_revenue_reconciles.sql",
        "tests/assert_no_many_to_many_revenue_join.sql",
        "tests/warn_customers_without_subscription.sql",
    ]
    missing_files = [path for path in required_files if not (project_root / path).is_file()]
    if missing_files:
        checks.append(failed("required_project_files_exist", missing_files, required_files, missing_files))
        return checks, summary
    checks.append(passed("required_project_files_exist", required_files, "required files"))

    declared = collect_declared_tests(project_root)
    summary.update(declared)
    missing_generic = sorted(GENERIC_TEST_TYPES - set(declared["generic_counts"]))
    if missing_generic:
        checks.append(
            failed(
                "generic_tests_cover_core_assertions",
                declared["generic_counts"],
                sorted(GENERIC_TEST_TYPES),
                missing_generic,
            )
        )
    else:
        checks.append(
            passed("generic_tests_cover_core_assertions", declared["generic_counts"], "not_null/unique/relationships/accepted_values")
        )

    if declared["legacy_tests_keys"]:
        checks.append(
            failed(
                "uses_data_tests_key",
                declared["legacy_tests_keys"],
                "data_tests key without legacy tests key",
                declared["legacy_tests_keys"],
            )
        )
    else:
        checks.append(passed("uses_data_tests_key", "ok", "data_tests key"))

    missing_singular = sorted(set(EXPECTED_SINGULAR_TESTS) - set(declared["singular_sql"]))
    missing_descriptions = sorted(
        name for name in EXPECTED_SINGULAR_TESTS if not declared["singular_descriptions"].get(name)
    )
    if missing_singular or missing_descriptions:
        checks.append(
            failed(
                "singular_tests_are_documented",
                {"missing_sql": missing_singular, "missing_descriptions": missing_descriptions},
                sorted(EXPECTED_SINGULAR_TESTS),
                missing_singular + missing_descriptions,
            )
        )
    else:
        checks.append(passed("singular_tests_are_documented", sorted(EXPECTED_SINGULAR_TESTS), "sql plus descriptions"))

    warning_errors: list[str] = []
    for name in WARNING_TESTS:
        if not CONFIG_WARN_RE.search((project_root / "tests" / f"{name}.sql").read_text(encoding="utf-8")):
            warning_errors.append(name)
    contract_warning_errors = [
        name
        for name in CONTRACT_TESTS
        if CONFIG_WARN_RE.search((project_root / "tests" / f"{name}.sql").read_text(encoding="utf-8"))
    ]
    if warning_errors or contract_warning_errors:
        checks.append(
            failed(
                "warning_diagnostics_are_marked_non_blocking",
                {"missing_warning_config": warning_errors, "contract_tests_marked_warn": contract_warning_errors},
                "warning diagnostics use severity warn; contract gates do not",
                warning_errors + contract_warning_errors,
            )
        )
    else:
        checks.append(
            passed("warning_diagnostics_are_marked_non_blocking", sorted(WARNING_TESTS), "severity warn diagnostics")
        )

    properties = read_yaml(project_root / "models" / "properties.yml")
    mart = next((item for item in properties.get("models", []) if item.get("name") == "mart_customer_revenue_health"), {})
    meta = mart.get("meta") if isinstance(mart.get("meta"), dict) else {}
    if not meta.get("required_tests") or not meta.get("warning_checks"):
        checks.append(
            failed(
                "mart_declares_required_and_warning_checks",
                meta,
                "required_tests and warning_checks in mart meta",
                ["mart_customer_revenue_health"],
            )
        )
    else:
        checks.append(
            passed(
                "mart_declares_required_and_warning_checks",
                {"required_tests": meta["required_tests"], "warning_checks": meta["warning_checks"]},
                "mart test policy",
            )
        )

    checks.append(validate_source_freshness_config(project_root, data_contract))
    return checks, summary


def safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"unsafe SQL identifier: {value}")
    return value


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


def source_state_counts(sources_path: Path) -> dict[str, int]:
    value = read_json(sources_path)
    counts: Counter[str] = Counter()
    for result in value.get("results", []):
        if isinstance(result, dict):
            counts[str(result.get("status", "unknown"))] += 1
    if counts:
        return dict(sorted(counts.items()))
    for source in value.get("sources", {}).values():
        if isinstance(source, dict):
            counts[str(source.get("state", "unknown"))] += 1
    return dict(sorted(counts.items()))


def test_kind(node: dict[str, Any]) -> str:
    path = str(node.get("original_file_path", ""))
    return "singular" if path.startswith("tests/") and path.endswith(".sql") else "generic"


def test_classification(node: dict[str, Any], result: dict[str, Any]) -> str:
    name = str(node.get("name") or result.get("unique_id", "").split(".")[-1])
    severity = str((node.get("config") or {}).get("severity", "error"))
    if name in WARNING_TESTS or severity == "warn":
        return "warning_diagnostic"
    return "contract_gate"


def inspect_test_results(manifest_path: Path, run_results_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = read_json(manifest_path)
    run_results = read_json(run_results_path)
    test_nodes = {
        unique_id: node
        for unique_id, node in manifest.get("nodes", {}).items()
        if isinstance(node, dict) and node.get("resource_type") == "test"
    }
    rows: list[dict[str, Any]] = []
    for result in run_results.get("results", []):
        if not isinstance(result, dict):
            continue
        unique_id = result.get("unique_id")
        node = test_nodes.get(unique_id, {})
        if not node:
            continue
        name = str(node.get("name") or str(unique_id).split(".")[-1])
        rows.append(
            {
                "name": name,
                "unique_id": unique_id,
                "status": result.get("status"),
                "failures": result.get("failures"),
                "severity": (node.get("config") or {}).get("severity", "error"),
                "kind": test_kind(node),
                "classification": test_classification(node, result),
            }
        )

    status_counts = dict(sorted(Counter(str(row["status"]) for row in rows).items()))
    kind_counts = dict(sorted(Counter(str(row["kind"]) for row in rows).items()))
    classification_counts = dict(sorted(Counter(str(row["classification"]) for row in rows).items()))
    contract_failures = [
        row for row in rows if row["classification"] == "contract_gate" and row["status"] != "pass"
    ]
    warning_rows = [row for row in rows if row["classification"] == "warning_diagnostic"]
    checks = []
    if contract_failures:
        checks.append(
            failed("contract_gates_pass", contract_failures, "all contract gates pass", contract_failures[:5])
        )
    else:
        checks.append(passed("contract_gates_pass", "ok", "all contract gates pass"))

    warning_errors = [
        row
        for row in warning_rows
        if row["status"] not in {"pass", "warn"}
    ]
    expected_warning_status = {
        row["name"]: row["status"] for row in warning_rows if row["name"] in WARNING_TESTS
    }
    if warning_errors or expected_warning_status.get("warn_customers_without_subscription") != "warn":
        checks.append(
            failed(
                "warning_diagnostics_are_non_blocking",
                {"warning_errors": warning_errors, "expected_warning_status": expected_warning_status},
                "warning diagnostics warn or pass and do not block",
                warning_errors or [expected_warning_status],
            )
        )
    else:
        checks.append(
            passed("warning_diagnostics_are_non_blocking", expected_warning_status, "expected warning diagnostics")
        )

    missing_singular = sorted(set(EXPECTED_SINGULAR_TESTS) - {row["name"] for row in rows})
    if missing_singular:
        checks.append(failed("singular_tests_execute", missing_singular, sorted(EXPECTED_SINGULAR_TESTS), missing_singular))
    else:
        checks.append(passed("singular_tests_execute", sorted(EXPECTED_SINGULAR_TESTS), "all singular tests executed"))

    return checks, {
        "test_status_counts": status_counts,
        "test_kind_counts": kind_counts,
        "test_classification_counts": classification_counts,
        "test_results": sorted(rows, key=lambda row: row["name"]),
        "contract_failure_count": len(contract_failures),
        "warning_diagnostic_count": len(warning_rows),
    }


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
        db_path = tmp / "data_tests.duckdb"
        row_counts = prepare_duckdb_database(db_path, data_contract, data_dir)

        env = os.environ.copy()
        env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
        env["DBT_DUCKDB_PATH"] = str(db_path)
        base = ["--project-dir", str(project_copy), "--profiles-dir", str(profiles_dir)]
        commands = [
            run_command(["dbt", "parse", *base], env),
            run_command(["dbt", "run", *base], env),
            run_command(["dbt", "source", "freshness", *base], env),
            run_command(["dbt", "test", "--select", "test_type:data", *base], env),
        ]
        summary["loaded_raw_rows"] = row_counts
        summary["dbt_commands"] = commands
        run_ok = commands[0]["returncode"] == 0 and commands[1]["returncode"] == 0
        freshness_ok = commands[2]["returncode"] == 0
        if run_ok:
            checks.append(passed("dbt_parse_and_run_succeed", "ok", "parse and run exit 0"))
        else:
            checks.append(failed("dbt_parse_and_run_succeed", commands[:2], "parse and run exit 0", commands[:2]))
            return checks, summary
        if freshness_ok:
            freshness_counts = source_state_counts(project_copy / "target" / "sources.json")
            summary["freshness_state_counts"] = freshness_counts
            if freshness_counts.get("error") or freshness_counts.get("warn"):
                checks.append(failed("source_freshness_passes", freshness_counts, "all sources pass", [freshness_counts]))
            else:
                checks.append(passed("source_freshness_passes", freshness_counts, "all sources pass"))
        else:
            checks.append(failed("source_freshness_passes", commands[2], "source freshness exits 0", [commands[2]]))
        test_checks, test_summary = inspect_test_results(
            project_copy / "target" / "manifest.json",
            project_copy / "target" / "run_results.json",
        )
        checks.extend(test_checks)
        summary.update(test_summary)
        expected_returncode = 0 if test_summary["contract_failure_count"] == 0 else 1
        if commands[3]["returncode"] == expected_returncode:
            checks.append(
                passed(
                    "dbt_test_exit_code_matches_contract_policy",
                    commands[3]["returncode"],
                    f"return code {expected_returncode}",
                )
            )
        else:
            checks.append(
                failed(
                    "dbt_test_exit_code_matches_contract_policy",
                    commands[3]["returncode"],
                    f"return code {expected_returncode}",
                    [commands[3]],
                )
            )
    return checks, summary


def validate_project(
    project_root: Path,
    data_contract_path: Path,
    data_dir: Path | None = None,
    run_dbt: bool = False,
) -> dict[str, Any]:
    data_contract = read_json(data_contract_path)
    resolved_data_dir = data_dir or data_contract_path.parent / "tiny"
    checks, summary = validate_static_project(project_root, data_contract)
    summary["data_contract"] = str(data_contract_path)
    summary["data_dir"] = str(resolved_data_dir)
    if run_dbt and all(check["valid"] for check in checks):
        live_checks, live_summary = run_dbt_audit(project_root, data_contract, resolved_data_dir)
        checks.extend(live_checks)
        summary.update(live_summary)
    elif run_dbt:
        checks.append(failed("dbt_parse_and_run_succeed", "skipped because static checks failed", "parse and run exit 0"))
    return {"valid": all(check["valid"] for check in checks), "summary": summary, "checks": checks}


def parse_args() -> argparse.Namespace:
    lesson_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Audit dbt generic/singular data tests and source freshness.")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parent / "data_test_project",
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
    parser.add_argument("--run-dbt", action="store_true", help="Run dbt run, source freshness and dbt data tests.")
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
