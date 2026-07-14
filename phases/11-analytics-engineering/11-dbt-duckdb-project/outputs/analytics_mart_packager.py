from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml


LESSON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LESSON_ROOT.parents[2]
EXPECTED_PROJECT_NAME = "analytics_mart_dbt"
EXPECTED_PACKAGE_DIR = "analytics-mart-dbt"
EXPECTED_EXPOSURE_NAME = "customer_revenue_health_dashboard"
EXPECTED_LINT_PATHS = ("models", "tests", "snapshots")
EXPECTED_SQLFLUFF_IGNORES = {"target/", "logs/", "dbt_packages/", "*.duckdb"}
EXPECTED_DOC_BLOCKS = {
    "__analytics_mart_dbt__",
    "mart_customer_revenue_health_docs",
    "subscription_history_docs",
    "customer_revenue_health_dashboard_docs",
}
EXPECTED_KEY_NODES = {
    "model.analytics_mart_dbt.mart_customer_revenue_health",
    "model.analytics_mart_dbt.fct_order_revenue_daily",
    "model.analytics_mart_dbt.int_subscription_history",
    "snapshot.analytics_mart_dbt.subscription_status_snapshot",
    "exposure.analytics_mart_dbt.customer_revenue_health_dashboard",
}
EXPECTED_BLOCKING_TESTS = {
    "assert_paid_revenue_reconciles",
    "assert_daily_revenue_reconciles",
    "assert_no_many_to_many_revenue_join",
    "assert_subscription_history_has_one_current_row",
    "assert_subscription_history_windows_do_not_overlap",
    "assert_snapshot_does_not_version_noisy_updated_at",
}
EXPECTED_WARNING_TESTS = {"warn_customers_without_subscription"}
EXPECTED_DECISION_CLAIMS = {
    "customer_health_segment_supported": {
        "models": {"mart_customer_revenue_health"},
        "tests": {"assert_paid_revenue_reconciles", "warn_customers_without_subscription"},
    },
    "daily_paid_revenue_reconciles": {
        "models": {"fct_order_revenue_daily"},
        "tests": {"assert_daily_revenue_reconciles"},
    },
    "subscription_history_is_point_in_time": {
        "models": {"int_subscription_history"},
        "tests": {
            "assert_subscription_history_has_one_current_row",
            "assert_subscription_history_windows_do_not_overlap",
            "assert_snapshot_does_not_version_noisy_updated_at",
        },
    },
}
RELEASE_FILES = {
    "target-artifacts/manifest.json",
    "target-artifacts/catalog.json",
    "target-artifacts/run_results.json",
    "target-artifacts/lineage-summary.json",
    "quality/dbt-test-report.json",
    "quality/source-freshness.json",
    "quality/sqlfluff-report.json",
    "quality/contract-audit.json",
    "report.md",
    "manifest.json",
}
GENERATED_DIR_NAMES = {"target", "logs", "dbt_packages", "__pycache__"}
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
RAW_RELATION_RE = re.compile(r"\braw\s*\.", re.IGNORECASE)


def portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


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


def safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"unsafe SQL identifier: {value}")
    return value


def data_contract_tables(data_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = data_contract.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("data contract must contain a tables object")
    return {str(name): table for name, table in tables.items() if isinstance(table, dict)}


def source_table_map(project_root: Path) -> dict[str, dict[str, Any]]:
    sources = read_yaml(project_root / "models" / "sources.yml")
    raw_app = next(
        (source for source in sources.get("sources", []) if isinstance(source, dict) and source.get("name") == "raw_app"),
        None,
    )
    if not isinstance(raw_app, dict):
        return {}
    return {table["identifier"]: table for table in raw_app.get("tables", []) if isinstance(table, dict) and "identifier" in table}


def model_map(project_root: Path) -> dict[str, dict[str, Any]]:
    properties = read_yaml(project_root / "models" / "properties.yml")
    return {model["name"]: model for model in properties.get("models", []) if isinstance(model, dict) and "name" in model}


def has_description(resource: dict[str, Any]) -> bool:
    description = resource.get("description")
    return isinstance(description, str) and bool(description.strip()) and "todo" not in description.lower()


def sql_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    for directory in EXPECTED_LINT_PATHS:
        root = project_root / directory
        if root.exists():
            files.extend(sorted(root.rglob("*.sql")))
    return files


def tail(text: str, line_count: int = 10) -> str:
    lines = ANSI_RE.sub("", text).splitlines()
    return "\n".join(lines[-line_count:])


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


def redact_text(value: str, redactions: dict[str, str] | None) -> str:
    for source, replacement in sorted(
        (redactions or {}).items(), key=lambda item: len(item[0]), reverse=True
    ):
        value = value.replace(source, replacement)
    return value


def run_command(
    command: list[str],
    env: dict[str, str],
    cwd: Path | None = None,
    timeout: int = 240,
    redactions: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return {
        "command": redact_text(" ".join(command), redactions),
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": redact_text(tail(completed.stdout), redactions),
        "stderr_tail": redact_text(tail(completed.stderr), redactions),
    }


def validate_project_identity(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"project_root": portable_path(project_root)}
    required_files = [
        "dbt_project.yml",
        "profiles.yml",
        "profiles.yml.example",
        ".sqlfluff",
        ".sqlfluffignore",
        "commands.md",
        "docs/mart_contract.md",
        "models/docs.md",
        "models/exposures.yml",
        "models/sources.yml",
        "models/properties.yml",
        "snapshots/subscription_status_history.yml",
        "tests/schema.yml",
        "seeds/calendar.csv",
    ]
    missing = [path for path in required_files if not (project_root / path).is_file()]
    checks.append(
        passed("required_package_files_exist", required_files, "release package source files")
        if not missing
        else failed("required_package_files_exist", missing, required_files, missing)
    )
    if missing:
        return checks, summary

    dbt_project = read_yaml(project_root / "dbt_project.yml")
    observed_project = {"name": dbt_project.get("name"), "profile": dbt_project.get("profile")}
    expected_project = {"name": EXPECTED_PROJECT_NAME, "profile": EXPECTED_PROJECT_NAME}
    checks.append(
        passed("dbt_project_identity_is_final", observed_project, expected_project)
        if observed_project == expected_project
        else failed("dbt_project_identity_is_final", observed_project, expected_project)
    )

    profile = read_yaml(project_root / "profiles.yml")
    output = ((profile.get(EXPECTED_PROJECT_NAME) or {}).get("outputs") or {}).get("dev") or {}
    secret_like = [key for key in output if any(token in key.lower() for token in ("password", "token", "secret"))]
    profile_observed = {"type": output.get("type"), "path": output.get("path"), "threads": output.get("threads")}
    profile_valid = output.get("type") == "duckdb" and "analytics_mart.duckdb" in str(output.get("path", "")) and not secret_like
    checks.append(
        passed("profile_uses_local_duckdb_without_secrets", profile_observed, "local duckdb profile")
        if profile_valid
        else failed("profile_uses_local_duckdb_without_secrets", profile_observed, "local duckdb profile", secret_like)
    )

    config = read_sqlfluff_config(project_root / ".sqlfluff")
    core = config["sqlfluff"] if config.has_section("sqlfluff") else {}
    templater = config["sqlfluff:templater:dbt"] if config.has_section("sqlfluff:templater:dbt") else {}
    templater_observed = {
        "dialect": core.get("dialect"),
        "templater": core.get("templater"),
        "project_dir": templater.get("project_dir"),
        "profiles_dir": templater.get("profiles_dir"),
        "profile": templater.get("profile"),
        "target": templater.get("target"),
        "dbt_skip_compilation_error": templater.get("dbt_skip_compilation_error"),
    }
    templater_valid = templater_observed == {
        "dialect": "duckdb",
        "templater": "dbt",
        "project_dir": ".",
        "profiles_dir": ".",
        "profile": EXPECTED_PROJECT_NAME,
        "target": "dev",
        "dbt_skip_compilation_error": "False",
    }
    checks.append(
        passed("sqlfluff_uses_duckdb_dbt_templater", templater_observed, "duckdb + dbt templater")
        if templater_valid
        else failed("sqlfluff_uses_duckdb_dbt_templater", templater_observed, "duckdb + dbt templater")
    )

    ignore_lines = {
        line.strip()
        for line in (project_root / ".sqlfluffignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing_ignores = sorted(EXPECTED_SQLFLUFF_IGNORES - ignore_lines)
    checks.append(
        passed("generated_artifacts_are_ignored_by_sqlfluff", sorted(ignore_lines & EXPECTED_SQLFLUFF_IGNORES), sorted(EXPECTED_SQLFLUFF_IGNORES))
        if not missing_ignores
        else failed("generated_artifacts_are_ignored_by_sqlfluff", sorted(ignore_lines), sorted(EXPECTED_SQLFLUFF_IGNORES), missing_ignores)
    )

    generated_paths = [
        str(path.relative_to(project_root))
        for path in project_root.rglob("*")
        if path.is_dir() and path.name in {"target", "logs", "dbt_packages"}
    ]
    generated_paths.extend(str(path.relative_to(project_root)) for path in project_root.rglob("*.duckdb"))
    checks.append(
        passed("package_has_no_local_runtime_artifacts", 0, 0)
        if not generated_paths
        else failed("package_has_no_local_runtime_artifacts", generated_paths, "no target/logs/dbt_packages/*.duckdb", generated_paths[:5])
    )

    commands_text = (project_root / "commands.md").read_text(encoding="utf-8").lower()
    required_terms = ["dbt parse", "dbt snapshot", "dbt test", "dbt docs generate", "sqlfluff lint", "manifest.json"]
    missing_terms = [term for term in required_terms if term not in commands_text]
    checks.append(
        passed("commands_document_full_local_gate", required_terms, "full local gate commands")
        if not missing_terms
        else failed("commands_document_full_local_gate", missing_terms, required_terms, missing_terms)
    )
    return checks, summary


def validate_sources_and_raw_boundary(project_root: Path, data_contract: dict[str, Any]) -> dict[str, Any]:
    contract_tables = data_contract_tables(data_contract)
    sources = source_table_map(project_root)
    problems: list[dict[str, Any]] = []
    for table_name, contract in sorted(contract_tables.items()):
        table = sources.get(table_name)
        if table is None:
            problems.append({"table": table_name, "problem": "missing source declaration"})
            continue
        loaded_at = (table.get("config") or {}).get("loaded_at_field")
        if loaded_at != contract.get("freshness_column"):
            problems.append({"table": table_name, "problem": "freshness mismatch", "observed": loaded_at, "expected": contract.get("freshness_column")})
        if not has_description(table):
            problems.append({"table": table_name, "problem": "missing source description"})
        if not (table.get("meta") or {}).get("owner"):
            problems.append({"table": table_name, "problem": "missing source owner"})

    raw_terms = set(contract_tables)
    direct_refs: list[dict[str, Any]] = []
    for path in sql_files(project_root):
        text = path.read_text(encoding="utf-8")
        lower_text = text.lower()
        matches = sorted(term for term in raw_terms if re.search(rf"\b{re.escape(term.lower())}\b", lower_text))
        if RAW_RELATION_RE.search(text) or matches:
            direct_refs.append({"file": str(path.relative_to(project_root)), "raw_tables": matches})

    if problems or direct_refs:
        return failed(
            "sources_are_complete_and_models_do_not_reference_raw_relations",
            {"source_problems": problems, "direct_refs": direct_refs},
            "sources.yml boundary with no direct raw relation references",
            (problems + direct_refs)[:8],
        )
    return passed("sources_are_complete_and_models_do_not_reference_raw_relations", sorted(contract_tables), "complete raw source boundary")


def validate_model_contracts(project_root: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    models = model_map(project_root)
    model_problems: list[dict[str, Any]] = []
    for model_name, model in sorted(models.items()):
        meta = model.get("meta") or {}
        missing_meta = [key for key in ("layer", "grain", "consumer", "materialization_reason", "cost_note") if not meta.get(key)]
        if not has_description(model) or missing_meta:
            model_problems.append({"model": model_name, "missing_meta": missing_meta, "has_description": has_description(model)})
    checks.append(
        passed("models_document_layer_grain_consumers_and_materialization", len(models), "documented model contracts")
        if not model_problems
        else failed("models_document_layer_grain_consumers_and_materialization", model_problems, "documented model contracts", model_problems[:8])
    )

    fact_path = project_root / "models" / "marts" / "fct_order_revenue_daily.sql"
    fact_sql = fact_path.read_text(encoding="utf-8") if fact_path.is_file() else ""
    fact_model = models.get("fct_order_revenue_daily") or {}
    fact_meta = fact_model.get("meta") or {}
    incremental_contract = fact_meta.get("incremental_contract") or {}
    fact_valid = (
        "materialized='incremental'" in fact_sql
        and "unique_key='revenue_date'" in fact_sql
        and "is_incremental()" in fact_sql
        and "interval '2 days'" in fact_sql
        and incremental_contract.get("late_arrival_window_days") == 2
        and incremental_contract.get("full_refresh_policy")
    )
    checks.append(
        passed("incremental_fact_has_unique_key_late_window_and_full_refresh_policy", incremental_contract, "2-day revenue_date incremental contract")
        if fact_valid
        else failed(
            "incremental_fact_has_unique_key_late_window_and_full_refresh_policy",
            {"sql": fact_path.name, "contract": incremental_contract},
            "materialized incremental with revenue_date unique key and 2-day window",
        )
    )

    snapshot_yaml = read_yaml(project_root / "snapshots" / "subscription_status_history.yml")
    snapshot = next(
        (item for item in snapshot_yaml.get("snapshots", []) if isinstance(item, dict) and item.get("name") == "subscription_status_snapshot"),
        {},
    )
    config = snapshot.get("config") or {}
    meta = snapshot.get("meta") or {}
    snapshot_valid = (
        snapshot.get("relation") == "ref('stg_subscriptions')"
        and config.get("unique_key") == "subscription_id"
        and config.get("strategy") == "check"
        and config.get("updated_at") == "updated_at"
        and "updated_at" in ((meta.get("snapshot_contract") or {}).get("excluded_noisy_columns") or [])
    )
    checks.append(
        passed("snapshot_contract_uses_business_check_cols_and_excludes_noisy_updated_at", config, "check snapshot over business columns")
        if snapshot_valid
        else failed("snapshot_contract_uses_business_check_cols_and_excludes_noisy_updated_at", {"config": config, "meta": meta}, "check snapshot over business columns")
    )

    docs_text = (project_root / "models" / "docs.md").read_text(encoding="utf-8")
    observed_docs = set(re.findall(r"{%\s+docs\s+([A-Za-z_][A-Za-z0-9_]*)\s+%}", docs_text))
    missing_docs = sorted(EXPECTED_DOC_BLOCKS - observed_docs)
    checks.append(
        passed("docs_blocks_exist_for_project_mart_snapshot_and_exposure", sorted(EXPECTED_DOC_BLOCKS), sorted(EXPECTED_DOC_BLOCKS))
        if not missing_docs
        else failed("docs_blocks_exist_for_project_mart_snapshot_and_exposure", sorted(observed_docs), sorted(EXPECTED_DOC_BLOCKS), missing_docs)
    )
    return checks


def validate_exposure_claims(project_root: Path) -> dict[str, Any]:
    exposures_yaml = read_yaml(project_root / "models" / "exposures.yml")
    exposure = next(
        (item for item in exposures_yaml.get("exposures", []) if isinstance(item, dict) and item.get("name") == EXPECTED_EXPOSURE_NAME),
        None,
    )
    if not isinstance(exposure, dict):
        return failed("exposure_declares_traceable_decision_claims", None, EXPECTED_EXPOSURE_NAME)
    observed_claims = {
        claim.get("id"): claim
        for claim in (exposure.get("meta") or {}).get("decision_claims", [])
        if isinstance(claim, dict) and claim.get("id")
    }
    problems: list[dict[str, Any]] = []
    for claim_id, expected in EXPECTED_DECISION_CLAIMS.items():
        claim = observed_claims.get(claim_id)
        if claim is None:
            problems.append({"claim": claim_id, "problem": "missing"})
            continue
        if set(claim.get("upstream_models") or []) != expected["models"] or set(claim.get("required_tests") or []) != expected["tests"]:
            problems.append(
                {
                    "claim": claim_id,
                    "models": claim.get("upstream_models"),
                    "tests": claim.get("required_tests"),
                    "expected": {key: sorted(value) for key, value in expected.items()},
                }
            )
    if problems:
        return failed("exposure_declares_traceable_decision_claims", problems, sorted(EXPECTED_DECISION_CLAIMS), problems)
    return passed("exposure_declares_traceable_decision_claims", sorted(observed_claims), sorted(EXPECTED_DECISION_CLAIMS))


def validate_static_project(project_root: Path, data_contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks, summary = validate_project_identity(project_root)
    if not all(check["valid"] for check in checks):
        return checks, summary
    checks.append(validate_sources_and_raw_boundary(project_root, data_contract))
    checks.extend(validate_model_contracts(project_root))
    checks.append(validate_exposure_claims(project_root))
    summary["sql_files"] = len(sql_files(project_root))
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


def collect_source_freshness(db_path: Path, data_contract: dict[str, Any]) -> dict[str, Any]:
    import duckdb

    con = duckdb.connect(str(db_path), read_only=True)
    sources: list[dict[str, Any]] = []
    try:
        for table_name, table in sorted(data_contract_tables(data_contract).items()):
            freshness_column = safe_identifier(str(table.get("freshness_column")))
            safe_table = safe_identifier(table_name)
            row_count, max_loaded_at = con.execute(
                f'select count(*) as row_count, max("{freshness_column}") as max_loaded_at from raw."{safe_table}"'
            ).fetchone()
            sources.append(
                {
                    "source_id": f"source.{EXPECTED_PROJECT_NAME}.raw_app.{table_name.removeprefix('raw_')}",
                    "raw_table": table_name,
                    "freshness_column": freshness_column,
                    "row_count": row_count,
                    "max_loaded_at": str(max_loaded_at),
                    "status": "loaded" if row_count > 0 and max_loaded_at is not None else "empty",
                }
            )
    finally:
        con.close()
    return {"generated_at_utc": utc_now(), "status": "pass", "sources": sources}


def ignore_runtime_artifacts(_: str, names: list[str]) -> set[str]:
    return {name for name in names if name in GENERATED_DIR_NAMES or name.endswith(".duckdb")}


def copy_project_for_build(project_root: Path, destination: Path) -> Path:
    project_copy = destination / "project"
    shutil.copytree(project_root, project_copy, ignore=ignore_runtime_artifacts)
    return project_copy


def run_sqlfluff(project_copy: Path, env: dict[str, str]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "sqlfluff", "lint", *EXPECTED_LINT_PATHS, "--format", "json"],
        cwd=project_copy,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=240,
    )
    files = parse_sqlfluff_output(result.stdout)
    violations = flatten_violations(files)
    return {
        "generated_at_utc": utc_now(),
        "command": "python -m sqlfluff lint models tests snapshots --format json",
        "returncode": result.returncode,
        "files_linted": len(files),
        "violations": violations,
        "violation_count": len(violations),
        "stderr_tail": tail(result.stderr),
        "status": "pass" if result.returncode == 0 and not violations else "fail",
    }


def collect_tool_versions(env: dict[str, str]) -> dict[str, str]:
    versions = {"python": sys.version.split()[0]}
    dbt = run_command(["dbt", "--version"], env, timeout=60)
    sqlfluff = run_command([sys.executable, "-m", "sqlfluff", "version"], env, timeout=60)
    versions["dbt"] = dbt["stdout_tail"] or dbt["stderr_tail"]
    versions["sqlfluff"] = sqlfluff["stdout_tail"] or sqlfluff["stderr_tail"]
    return versions


def test_node_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        node.get("name"): node
        for node in manifest.get("nodes", {}).values()
        if isinstance(node, dict) and node.get("resource_type") == "test"
    }


def node_id_by_name(manifest: dict[str, Any], resource_type: str, name: str) -> str | None:
    for unique_id, node in manifest.get("nodes", {}).items():
        if isinstance(node, dict) and node.get("resource_type") == resource_type and node.get("name") == name:
            return unique_id
    if resource_type == "snapshot":
        for unique_id, node in manifest.get("nodes", {}).items():
            if isinstance(node, dict) and node.get("resource_type") == "snapshot" and node.get("name") == name:
                return unique_id
    return None


def build_dbt_test_report(run_results: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    nodes_by_id = manifest.get("nodes", {})
    tests: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    blocking_failures: list[dict[str, Any]] = []
    for result in run_results.get("results", []):
        unique_id = result.get("unique_id")
        node = nodes_by_id.get(unique_id, {})
        if node.get("resource_type") != "test":
            continue
        status = result.get("status")
        severity = ((node.get("config") or {}).get("severity") or "error").lower()
        counts[status] += 1
        record = {
            "unique_id": unique_id,
            "name": node.get("name"),
            "status": status,
            "severity": severity,
            "failures": result.get("failures"),
            "execution_time": result.get("execution_time"),
        }
        tests.append(record)
        if severity != "warn" and status not in {"pass", "success"}:
            blocking_failures.append(record)
    warning_results = [test for test in tests if test["severity"] == "warn"]
    return {
        "generated_at_utc": utc_now(),
        "status": "pass" if not blocking_failures else "fail",
        "counts_by_status": dict(sorted(counts.items())),
        "test_count": len(tests),
        "warning_test_count": len(warning_results),
        "blocking_failures": blocking_failures,
        "tests": sorted(tests, key=lambda item: str(item["unique_id"])),
    }


def build_lineage_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    nodes = manifest.get("nodes", {})
    models = []
    for unique_id, node in sorted(nodes.items()):
        if not isinstance(node, dict) or node.get("resource_type") not in {"model", "snapshot"}:
            continue
        models.append(
            {
                "unique_id": unique_id,
                "name": node.get("name"),
                "resource_type": node.get("resource_type"),
                "materialized": (node.get("config") or {}).get("materialized"),
                "layer": (node.get("meta") or {}).get("layer"),
                "grain": (node.get("meta") or {}).get("grain"),
                "depends_on_nodes": sorted((node.get("depends_on") or {}).get("nodes") or []),
            }
        )

    exposures = []
    for unique_id, exposure in sorted((manifest.get("exposures") or {}).items()):
        if not isinstance(exposure, dict):
            continue
        exposures.append(
            {
                "unique_id": unique_id,
                "name": exposure.get("name"),
                "type": exposure.get("type"),
                "maturity": exposure.get("maturity"),
                "depends_on_nodes": sorted((exposure.get("depends_on") or {}).get("nodes") or []),
                "decision_claims": (exposure.get("meta") or {}).get("decision_claims") or [],
            }
        )
    return {
        "generated_at_utc": utc_now(),
        "project_name": (manifest.get("metadata") or {}).get("project_name"),
        "models": models,
        "exposures": exposures,
    }


def generate_release_report(
    manifest: dict[str, Any],
    test_report: dict[str, Any],
    source_freshness: dict[str, Any],
    sqlfluff_report: dict[str, Any],
) -> str:
    test_nodes = test_node_map(manifest)
    claim_lines = []
    for claim_id, expected in EXPECTED_DECISION_CLAIMS.items():
        model_ids = [
            node_id_by_name(manifest, "model", model_name) or f"missing:{model_name}"
            for model_name in sorted(expected["models"])
        ]
        test_ids = [
            (test_nodes.get(test_name) or {}).get("unique_id") or f"missing:{test_name}"
            for test_name in sorted(expected["tests"])
        ]
        claim_lines.append(
            f"- `{claim_id}`: models {', '.join(f'`{item}`' for item in model_ids)}; "
            f"tests {', '.join(f'`{item}`' for item in test_ids)}."
        )

    source_lines = [
        f"- `{source['source_id']}`: {source['row_count']} rows, max `{source['freshness_column']}` = `{source['max_loaded_at']}`."
        for source in source_freshness.get("sources", [])
    ]
    status_lines = [
        f"- dbt tests: `{test_report['status']}` with {test_report['test_count']} tests and "
        f"{len(test_report['blocking_failures'])} blocking failures.",
        f"- SQLFluff: `{sqlfluff_report['status']}` with {sqlfluff_report['violation_count']} violations "
        f"across {sqlfluff_report['files_linted']} files.",
        f"- Source freshness extract: `{source_freshness['status']}` across {len(source_freshness.get('sources', []))} sources.",
    ]
    return "\n".join(
        [
            "# analytics-mart-dbt Release Report",
            "",
            f"Generated at: `{utc_now()}`",
            "",
            "## Decision Claims",
            "",
            *claim_lines,
            "",
            "## Quality Gates",
            "",
            *status_lines,
            "",
            "## Source Freshness",
            "",
            *source_lines,
            "",
            "## Handoff",
            "",
            "The package is reproducible with `python ../analytics_mart_packager.py --project . --build-package`.",
            "Checksum evidence is stored in `manifest.json`.",
            "",
        ]
    )


def clean_release_outputs(project_root: Path) -> None:
    for relative in RELEASE_FILES:
        path = project_root / relative
        if path.exists():
            path.unlink()


def copy_release_json(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, destination)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_release_files(project_root: Path) -> list[Path]:
    files = []
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(project_root).parts
        if any(part in GENERATED_DIR_NAMES for part in relative_parts):
            continue
        if path.name == "manifest.json" and path.parent == project_root:
            continue
        if path.suffix == ".duckdb" or path.name.endswith(".pyc"):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(project_root).as_posix())


def write_checksum_manifest(project_root: Path, tool_versions: dict[str, str]) -> dict[str, Any]:
    files = [
        {
            "path": path.relative_to(project_root).as_posix(),
            "sha256": file_sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in iter_release_files(project_root)
    ]
    manifest = {
        "package": EXPECTED_PACKAGE_DIR,
        "project_name": EXPECTED_PROJECT_NAME,
        "generated_at_utc": utc_now(),
        "tool_versions": tool_versions,
        "files": files,
    }
    write_json(project_root / "manifest.json", manifest)
    return manifest


def run_release_build(project_root: Path, data_contract: dict[str, Any], data_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    clean_release_outputs(project_root)
    with TemporaryDirectory() as directory:
        tmp = Path(directory)
        project_copy = copy_project_for_build(project_root, tmp)
        profiles_dir = tmp / "profiles"
        profiles_dir.mkdir()
        shutil.copy(project_copy / "profiles.yml", profiles_dir / "profiles.yml")
        db_path = tmp / "analytics_mart.duckdb"
        env = os.environ.copy()
        env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
        env["DBT_DUCKDB_PATH"] = str(db_path)
        base = ["--project-dir", str(project_copy), "--profiles-dir", str(profiles_dir)]
        redactions = {
            str(project_copy): "<temp>/project",
            str(profiles_dir): "<temp>/profiles",
            str(db_path): "<temp>/analytics_mart.duckdb",
            str(tmp): "<temp>",
        }

        summary["loaded_raw_rows"] = prepare_duckdb_database(db_path, data_contract, data_dir)
        commands: list[dict[str, Any]] = []
        for command in [
            ["dbt", "parse", *base],
            ["dbt", "run", "--exclude", "int_subscription_history", *base],
            ["dbt", "snapshot", "--select", "subscription_status_snapshot", *base],
            ["dbt", "run", "--select", "int_subscription_history", *base],
            ["dbt", "test", "--select", "test_type:data", *base],
        ]:
            command_result = run_command(command, env, redactions=redactions)
            commands.append(command_result)
            if command_result["returncode"] != 0:
                break
        test_run_results = read_json(project_copy / "target" / "run_results.json") if (project_copy / "target" / "run_results.json").is_file() else {}

        if all(command["returncode"] == 0 for command in commands):
            commands.append(
                run_command(
                    ["dbt", "docs", "generate", *base],
                    env,
                    redactions=redactions,
                )
            )
        summary["dbt_commands"] = commands
        failed_commands = [command for command in commands if command["returncode"] != 0]
        if failed_commands:
            checks.append(failed("dbt_local_gate_succeeds", failed_commands, "parse/run/snapshot/test/docs all exit 0", failed_commands))
            return checks, summary
        checks.append(passed("dbt_local_gate_succeeds", [command["command"] for command in commands], "parse/run/snapshot/test/docs all exit 0"))

        lint_report = run_sqlfluff(project_copy, env)
        checks.append(
            passed("sqlfluff_lint_succeeds", {"files": lint_report["files_linted"], "violations": 0}, "zero SQLFluff violations")
            if lint_report["status"] == "pass"
            else failed("sqlfluff_lint_succeeds", lint_report, "zero SQLFluff violations", lint_report["violations"][:5])
        )

        manifest = read_json(project_copy / "target" / "manifest.json")
        catalog = read_json(project_copy / "target" / "catalog.json")
        lineage = build_lineage_summary(manifest)
        test_report = build_dbt_test_report(test_run_results, manifest)
        source_freshness = collect_source_freshness(db_path, data_contract)
        report_md = generate_release_report(manifest, test_report, source_freshness, lint_report)

        copy_release_json(project_copy / "target" / "manifest.json", project_root / "target-artifacts" / "manifest.json")
        copy_release_json(project_copy / "target" / "catalog.json", project_root / "target-artifacts" / "catalog.json")
        write_json(project_root / "target-artifacts" / "run_results.json", test_run_results)
        write_json(project_root / "target-artifacts" / "lineage-summary.json", lineage)
        write_json(project_root / "quality" / "dbt-test-report.json", test_report)
        write_json(project_root / "quality" / "source-freshness.json", source_freshness)
        write_json(project_root / "quality" / "sqlfluff-report.json", lint_report)
        contract_audit = {
            "generated_at_utc": utc_now(),
            "status": "pass" if not failed_commands and lint_report["status"] == "pass" else "fail",
            "loaded_raw_rows": summary["loaded_raw_rows"],
            "dbt_commands": commands,
            "artifact_counts": {
                "manifest_nodes": len(manifest.get("nodes", {})),
                "manifest_sources": len(manifest.get("sources", {})),
                "manifest_exposures": len(manifest.get("exposures", {})),
                "catalog_nodes": len(catalog.get("nodes", {})),
                "catalog_sources": len(catalog.get("sources", {})),
            },
        }
        write_json(project_root / "quality" / "contract-audit.json", contract_audit)
        (project_root / "report.md").write_text(report_md, encoding="utf-8")
        write_checksum_manifest(project_root, collect_tool_versions(env))
    return checks, summary


def validate_release_artifacts(project_root: Path, data_contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    missing = sorted(relative for relative in RELEASE_FILES if not (project_root / relative).is_file())
    if missing:
        checks.append(failed("release_files_exist", missing, sorted(RELEASE_FILES), missing))
        return checks, summary
    checks.append(passed("release_files_exist", sorted(RELEASE_FILES), sorted(RELEASE_FILES)))

    manifest = read_json(project_root / "target-artifacts" / "manifest.json")
    catalog = read_json(project_root / "target-artifacts" / "catalog.json")
    run_results = read_json(project_root / "target-artifacts" / "run_results.json")
    lineage = read_json(project_root / "target-artifacts" / "lineage-summary.json")
    dbt_test_report = read_json(project_root / "quality" / "dbt-test-report.json")
    source_freshness = read_json(project_root / "quality" / "source-freshness.json")
    sqlfluff_report = read_json(project_root / "quality" / "sqlfluff-report.json")
    checksum_manifest = read_json(project_root / "manifest.json")
    report_text = (project_root / "report.md").read_text(encoding="utf-8")

    project_name = (manifest.get("metadata") or {}).get("project_name")
    checks.append(
        passed("dbt_manifest_catalog_are_for_final_project", project_name, EXPECTED_PROJECT_NAME)
        if project_name == EXPECTED_PROJECT_NAME and not catalog.get("errors")
        else failed("dbt_manifest_catalog_are_for_final_project", {"project": project_name, "catalog_errors": catalog.get("errors")}, EXPECTED_PROJECT_NAME)
    )

    present_nodes = set(manifest.get("nodes", {})) | set(manifest.get("exposures", {}))
    missing_nodes = sorted(EXPECTED_KEY_NODES - present_nodes)
    checks.append(
        passed("manifest_contains_key_models_snapshot_and_exposure", sorted(EXPECTED_KEY_NODES), sorted(EXPECTED_KEY_NODES))
        if not missing_nodes
        else failed("manifest_contains_key_models_snapshot_and_exposure", sorted(present_nodes & EXPECTED_KEY_NODES), sorted(EXPECTED_KEY_NODES), missing_nodes)
    )

    test_names = {node.get("name") for node in manifest.get("nodes", {}).values() if isinstance(node, dict) and node.get("resource_type") == "test"}
    missing_tests = sorted((EXPECTED_BLOCKING_TESTS | EXPECTED_WARNING_TESTS) - test_names)
    checks.append(
        passed("manifest_contains_blocking_and_warning_tests", sorted(test_names & (EXPECTED_BLOCKING_TESTS | EXPECTED_WARNING_TESTS)), sorted(EXPECTED_BLOCKING_TESTS | EXPECTED_WARNING_TESTS))
        if not missing_tests
        else failed("manifest_contains_blocking_and_warning_tests", sorted(test_names), sorted(EXPECTED_BLOCKING_TESTS | EXPECTED_WARNING_TESTS), missing_tests)
    )

    lineaged_exposure = next(
        (item for item in lineage.get("exposures", []) if item.get("name") == EXPECTED_EXPOSURE_NAME),
        {},
    )
    expected_exposure_deps = {
        "model.analytics_mart_dbt.mart_customer_revenue_health",
        "model.analytics_mart_dbt.fct_order_revenue_daily",
        "model.analytics_mart_dbt.int_subscription_history",
    }
    observed_exposure_deps = set(lineaged_exposure.get("depends_on_nodes") or [])
    checks.append(
        passed("lineage_summary_connects_exposure_to_marts", sorted(observed_exposure_deps), sorted(expected_exposure_deps))
        if observed_exposure_deps == expected_exposure_deps
        else failed("lineage_summary_connects_exposure_to_marts", sorted(observed_exposure_deps), sorted(expected_exposure_deps))
    )

    checks.append(
        passed("dbt_test_report_has_no_blocking_failures", dbt_test_report.get("test_count"), "no blocking failures")
        if dbt_test_report.get("status") == "pass" and not dbt_test_report.get("blocking_failures")
        else failed("dbt_test_report_has_no_blocking_failures", dbt_test_report, "no blocking failures")
    )
    checks.append(
        passed("sqlfluff_report_has_zero_violations", sqlfluff_report.get("files_linted"), "zero violations")
        if sqlfluff_report.get("status") == "pass" and sqlfluff_report.get("violation_count") == 0
        else failed("sqlfluff_report_has_zero_violations", sqlfluff_report, "zero violations", sqlfluff_report.get("violations", [])[:5])
    )

    expected_sources = {f"raw_app.{name.removeprefix('raw_')}" for name in data_contract_tables(data_contract)}
    observed_sources = {
        ".".join(str(source.get("source_id", "")).split(".")[-2:])
        for source in source_freshness.get("sources", [])
        if source.get("status") == "loaded"
    }
    checks.append(
        passed("source_freshness_covers_all_sources", sorted(observed_sources), sorted(expected_sources))
        if observed_sources == expected_sources
        else failed("source_freshness_covers_all_sources", sorted(observed_sources), sorted(expected_sources))
    )

    test_nodes = test_node_map(manifest)
    report_problems: list[dict[str, Any]] = []
    for claim_id, expected in EXPECTED_DECISION_CLAIMS.items():
        if claim_id not in report_text:
            report_problems.append({"claim": claim_id, "problem": "missing claim id in report"})
        for model_name in expected["models"]:
            model_id = node_id_by_name(manifest, "model", model_name)
            if model_id not in report_text:
                report_problems.append({"claim": claim_id, "problem": "missing model node id", "node": model_id})
        for test_name in expected["tests"]:
            test_id = (test_nodes.get(test_name) or {}).get("unique_id")
            if test_id not in report_text:
                report_problems.append({"claim": claim_id, "problem": "missing test node id", "node": test_id})
    checks.append(
        passed("report_claims_resolve_to_manifest_nodes", sorted(EXPECTED_DECISION_CLAIMS), "report.md claim node links")
        if not report_problems
        else failed("report_claims_resolve_to_manifest_nodes", report_problems, "report.md claim node links", report_problems)
    )

    checksum_errors: list[dict[str, Any]] = []
    for file_entry in checksum_manifest.get("files", []):
        relative = file_entry.get("path")
        if not isinstance(relative, str):
            checksum_errors.append({"path": relative, "problem": "invalid path"})
            continue
        path = project_root / relative
        if not path.is_file():
            checksum_errors.append({"path": relative, "problem": "missing"})
            continue
        observed_hash = file_sha256(path)
        if observed_hash != file_entry.get("sha256"):
            checksum_errors.append({"path": relative, "problem": "sha256 mismatch", "observed": observed_hash, "expected": file_entry.get("sha256")})
    checks.append(
        passed("checksum_manifest_matches_release_files", len(checksum_manifest.get("files", [])), "all checksums match")
        if not checksum_errors
        else failed("checksum_manifest_matches_release_files", checksum_errors, "all checksums match", checksum_errors[:8])
    )

    summary.update(
        {
            "artifact_counts": {
                "manifest_nodes": len(manifest.get("nodes", {})),
                "catalog_nodes": len(catalog.get("nodes", {})),
                "run_results": len(run_results.get("results", [])),
            },
            "lineage_models": len(lineage.get("models", [])),
            "release_files": len(RELEASE_FILES),
        }
    )
    return checks, summary


def validate_project(
    project_root: Path,
    data_contract_path: Path,
    data_dir: Path | None = None,
    build_package: bool = False,
) -> dict[str, Any]:
    data_contract = read_json(data_contract_path)
    resolved_data_dir = data_dir or data_contract_path.parent / "tiny"
    checks, summary = validate_static_project(project_root, data_contract)
    summary["data_contract"] = portable_path(data_contract_path)
    summary["data_dir"] = portable_path(resolved_data_dir)
    if build_package:
        if all(check["valid"] for check in checks):
            build_checks, build_summary = run_release_build(project_root, data_contract, resolved_data_dir)
            checks.extend(build_checks)
            summary.update(build_summary)
        else:
            checks.append(failed("dbt_local_gate_succeeds", "skipped because static checks failed", "static checks pass before build"))
    release_files_present = all((project_root / relative).is_file() for relative in RELEASE_FILES)
    if release_files_present:
        release_checks, release_summary = validate_release_artifacts(project_root, data_contract)
        checks.extend(release_checks)
        summary.update(release_summary)
    elif build_package:
        missing_release = sorted(relative for relative in RELEASE_FILES if not (project_root / relative).is_file())
        checks.append(failed("release_files_exist", missing_release, sorted(RELEASE_FILES), missing_release))
    return {"valid": all(check["valid"] for check in checks), "summary": summary, "checks": checks}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    lesson_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build and audit the final analytics-mart-dbt release package.")
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parent / EXPECTED_PACKAGE_DIR)
    parser.add_argument("--data-contract", type=Path, default=lesson_root.parent / "data" / "contract.json")
    parser.add_argument("--data-dir", type=Path, help="Directory containing raw CSV files.")
    parser.add_argument("--output", type=Path, help="Optional path to write the audit JSON.")
    parser.add_argument("--build-package", action="store_true", help="Run dbt/SQLFluff and refresh release artifacts.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = validate_project(
        project_root=args.project,
        data_contract_path=args.data_contract,
        data_dir=args.data_dir,
        build_package=args.build_package,
    )
    payload = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
