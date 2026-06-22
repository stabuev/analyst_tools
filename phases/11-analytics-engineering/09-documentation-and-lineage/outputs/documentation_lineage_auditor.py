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


EXPECTED_PROJECT_NAME = "documentation_project"
EXPOSURE_NAME = "customer_revenue_health_dashboard"
EXPECTED_DOC_BLOCKS = {
    "__documentation_project__",
    "mart_customer_revenue_health_docs",
    "subscription_history_docs",
    "customer_revenue_health_dashboard_docs",
}
EXPECTED_EXPOSURE_DEPENDS_ON = {
    "model.documentation_project.mart_customer_revenue_health",
    "model.documentation_project.fct_order_revenue_daily",
    "model.documentation_project.int_subscription_history",
}
EXPECTED_DECISION_CLAIMS = {
    "customer_health_segment_supported": {
        "upstream_models": {"mart_customer_revenue_health"},
        "required_tests": {"assert_paid_revenue_reconciles", "warn_customers_without_subscription"},
    },
    "daily_paid_revenue_reconciles": {
        "upstream_models": {"fct_order_revenue_daily"},
        "required_tests": {"assert_daily_revenue_reconciles"},
    },
    "subscription_history_is_point_in_time": {
        "upstream_models": {"int_subscription_history"},
        "required_tests": {
            "assert_subscription_history_has_one_current_row",
            "assert_subscription_history_windows_do_not_overlap",
            "assert_snapshot_does_not_version_noisy_updated_at",
        },
    },
}
EXPECTED_TEST_DOCS = {
    "assert_paid_revenue_reconciles",
    "assert_daily_revenue_reconciles",
    "assert_no_many_to_many_revenue_join",
    "warn_customers_without_subscription",
    "assert_subscription_history_has_one_current_row",
    "assert_subscription_history_windows_do_not_overlap",
    "assert_snapshot_does_not_version_noisy_updated_at",
}
EXPECTED_KEY_MODEL_COLUMNS = {
    "mart_customer_revenue_health": {
        "user_id",
        "country",
        "platform",
        "plan",
        "latest_subscription_status",
        "has_active_subscription",
        "order_count",
        "paid_order_count",
        "gross_revenue_rub",
        "paid_revenue_rub",
        "refunded_amount_rub",
        "support_ticket_count",
        "high_priority_ticket_count",
        "revenue_health_segment",
    },
    "fct_order_revenue_daily": {
        "revenue_date",
        "order_count",
        "paid_order_count",
        "gross_revenue_rub",
        "paid_revenue_rub",
        "refunded_amount_rub",
        "max_source_order_date",
    },
    "int_subscription_history": {
        "subscription_id",
        "user_id",
        "plan",
        "status",
        "started_at",
        "ended_at",
        "valid_from",
        "valid_to",
        "dbt_updated_at",
        "dbt_scd_id",
        "is_current",
    },
}
EXPECTED_CATALOG_RESOURCE_IDS = {
    "model.documentation_project.mart_customer_revenue_health",
    "model.documentation_project.fct_order_revenue_daily",
    "model.documentation_project.int_subscription_history",
    "snapshot.documentation_project.subscription_status_snapshot",
}
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


def has_description(resource: dict[str, Any]) -> bool:
    description = resource.get("description")
    return isinstance(description, str) and bool(description.strip()) and "todo" not in description.lower()


def model_by_name(properties: dict[str, Any], name: str) -> dict[str, Any] | None:
    for model in properties.get("models", []):
        if isinstance(model, dict) and model.get("name") == name:
            return model
    return None


def column_map(resource: dict[str, Any]) -> dict[str, dict[str, Any]]:
    columns: dict[str, dict[str, Any]] = {}
    for column in resource.get("columns", []):
        if isinstance(column, dict) and isinstance(column.get("name"), str):
            columns[column["name"]] = column
    return columns


def test_doc_names(test_docs: dict[str, Any]) -> set[str]:
    return {item["name"] for item in test_docs.get("data_tests", []) if isinstance(item, dict) and "name" in item}


def source_table_map(sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_app = next(
        (source for source in sources.get("sources", []) if isinstance(source, dict) and source.get("name") == "raw_app"),
        None,
    )
    if not isinstance(raw_app, dict):
        return {}
    return {table["identifier"]: table for table in raw_app.get("tables", []) if isinstance(table, dict) and "identifier" in table}


def data_contract_tables(data_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = data_contract.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("data contract must contain a tables object")
    return {str(name): table for name, table in tables.items() if isinstance(table, dict)}


def validate_project_identity(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"project_root": str(project_root)}
    required_files = [
        "dbt_project.yml",
        "profiles.yml.example",
        "commands.md",
        "models/docs.md",
        "models/exposures.yml",
        "models/sources.yml",
        "models/properties.yml",
        "snapshots/subscription_status_history.yml",
        "tests/schema.yml",
    ]
    missing = [path for path in required_files if not (project_root / path).is_file()]
    if missing:
        checks.append(failed("required_documentation_files_exist", missing, required_files, missing))
        return checks, summary
    checks.append(passed("required_documentation_files_exist", required_files, "required docs project files"))

    dbt_project = read_yaml(project_root / "dbt_project.yml")
    observed_project = {"name": dbt_project.get("name"), "profile": dbt_project.get("profile")}
    expected_project = {"name": EXPECTED_PROJECT_NAME, "profile": EXPECTED_PROJECT_NAME}
    if observed_project == expected_project:
        checks.append(passed("dbt_project_is_renamed", observed_project, expected_project))
    else:
        checks.append(failed("dbt_project_is_renamed", observed_project, expected_project))

    commands_text = (project_root / "commands.md").read_text(encoding="utf-8").lower()
    required_terms = ["dbt docs generate", "manifest", "catalog", "documentation_lineage_auditor.py"]
    missing_terms = [term for term in required_terms if term not in commands_text]
    if missing_terms:
        checks.append(failed("commands_document_docs_generate", missing_terms, required_terms, missing_terms))
    else:
        checks.append(passed("commands_document_docs_generate", required_terms, "docs generation commands"))
    return checks, summary


def validate_docs_blocks(project_root: Path) -> dict[str, Any]:
    docs_text = (project_root / "models" / "docs.md").read_text(encoding="utf-8")
    observed = set(re.findall(r"{%\s+docs\s+([A-Za-z_][A-Za-z0-9_]*)\s+%}", docs_text))
    missing = sorted(EXPECTED_DOC_BLOCKS - observed)
    if missing:
        return failed("docs_blocks_exist", sorted(observed), sorted(EXPECTED_DOC_BLOCKS), missing)
    return passed("docs_blocks_exist", sorted(observed & EXPECTED_DOC_BLOCKS), sorted(EXPECTED_DOC_BLOCKS))


def validate_sources_documentation(project_root: Path, data_contract: dict[str, Any]) -> dict[str, Any]:
    source_tables = source_table_map(read_yaml(project_root / "models" / "sources.yml"))
    contract_tables = data_contract_tables(data_contract)
    problems: list[dict[str, Any]] = []
    for table_name, contract in sorted(contract_tables.items()):
        table = source_tables.get(table_name)
        if table is None:
            problems.append({"table": table_name, "problem": "missing source table"})
            continue
        if not has_description(table):
            problems.append({"table": table_name, "problem": "missing table description"})
        if not (table.get("meta") or {}).get("owner"):
            problems.append({"table": table_name, "problem": "missing owner meta"})
        freshness_column = contract.get("freshness_column")
        if (table.get("config") or {}).get("loaded_at_field") != freshness_column:
            problems.append(
                {
                    "table": table_name,
                    "problem": "freshness mismatch",
                    "observed": (table.get("config") or {}).get("loaded_at_field"),
                    "expected": freshness_column,
                }
            )
        declared_columns = column_map(table)
        required_columns = set(contract.get("primary_key", []))
        if isinstance(freshness_column, str):
            required_columns.add(freshness_column)
        for column_name in sorted(required_columns):
            column = declared_columns.get(column_name)
            if column is None or not has_description(column):
                problems.append({"table": table_name, "column": column_name, "problem": "missing column description"})
    if problems:
        return failed("sources_have_descriptions_owners_and_freshness", problems, "source descriptions, owners, freshness and key columns")
    return passed("sources_have_descriptions_owners_and_freshness", sorted(contract_tables), "documented raw sources")


def validate_models_documentation(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    properties = read_yaml(project_root / "models" / "properties.yml")
    model_names = [model.get("name") for model in properties.get("models", []) if isinstance(model, dict)]
    undocumented_models = [name for name in model_names if not has_description(model_by_name(properties, name) or {})]
    if undocumented_models:
        checks.append(failed("models_have_descriptions", undocumented_models, "all declared models documented"))
    else:
        checks.append(passed("models_have_descriptions", len(model_names), "all declared models documented"))

    key_model_errors: list[dict[str, Any]] = []
    key_model_summary: dict[str, Any] = {}
    for model_name, expected_columns in EXPECTED_KEY_MODEL_COLUMNS.items():
        model = model_by_name(properties, model_name)
        if model is None:
            key_model_errors.append({"model": model_name, "problem": "missing model"})
            continue
        meta = model.get("meta") or {}
        if not meta.get("owner") or not meta.get("owner_email"):
            key_model_errors.append({"model": model_name, "problem": "missing owner and owner_email"})
        if not meta.get("grain") or not meta.get("consumer"):
            key_model_errors.append({"model": model_name, "problem": "missing grain or consumer"})
        columns = column_map(model)
        missing_columns = sorted(expected_columns - set(columns))
        undocumented_columns = sorted(name for name in expected_columns if name in columns and not has_description(columns[name]))
        duplicate_columns = [
            name
            for name in expected_columns
            if sum(1 for column in model.get("columns", []) if isinstance(column, dict) and column.get("name") == name) > 1
        ]
        if missing_columns or undocumented_columns or duplicate_columns:
            key_model_errors.append(
                {
                    "model": model_name,
                    "missing_columns": missing_columns,
                    "undocumented_columns": undocumented_columns,
                    "duplicate_columns": duplicate_columns,
                }
            )
        key_model_summary[model_name] = {
            "owner": meta.get("owner"),
            "grain": meta.get("grain"),
            "documented_columns": sorted(set(columns) & expected_columns),
        }
    summary["key_models"] = key_model_summary
    if key_model_errors:
        checks.append(failed("key_models_have_owner_grain_and_column_docs", key_model_errors, "owners, grain and documented key columns"))
    else:
        checks.append(passed("key_models_have_owner_grain_and_column_docs", key_model_summary, "documented key models"))
    return checks, summary


def validate_snapshot_documentation(project_root: Path) -> dict[str, Any]:
    snapshot_yaml = read_yaml(project_root / "snapshots" / "subscription_status_history.yml")
    snapshot = next(
        (item for item in snapshot_yaml.get("snapshots", []) if isinstance(item, dict) and item.get("name") == "subscription_status_snapshot"),
        None,
    )
    if snapshot is None:
        return failed("snapshot_has_documented_scd_fields", None, "subscription_status_snapshot")
    expected_columns = {
        "subscription_id",
        "user_id",
        "plan",
        "status",
        "started_at",
        "ended_at",
        "dbt_updated_at",
        "dbt_scd_id",
        "dbt_valid_from",
        "dbt_valid_to",
    }
    columns = column_map(snapshot)
    problems = []
    if not has_description(snapshot):
        problems.append({"problem": "missing snapshot description"})
    if not (snapshot.get("meta") or {}).get("owner"):
        problems.append({"problem": "missing snapshot owner"})
    missing_columns = sorted(expected_columns - set(columns))
    undocumented = sorted(name for name in expected_columns if name in columns and not has_description(columns[name]))
    if missing_columns or undocumented:
        problems.append({"missing_columns": missing_columns, "undocumented_columns": undocumented})
    if problems:
        return failed("snapshot_has_documented_scd_fields", problems, "snapshot description, owner and SCD column docs")
    return passed("snapshot_has_documented_scd_fields", sorted(expected_columns), "documented snapshot SCD fields")


def validate_test_documentation(project_root: Path) -> dict[str, Any]:
    test_docs = read_yaml(project_root / "tests" / "schema.yml")
    observed = test_doc_names(test_docs)
    missing = sorted(EXPECTED_TEST_DOCS - observed)
    undocumented = [
        item.get("name")
        for item in test_docs.get("data_tests", [])
        if isinstance(item, dict) and item.get("name") in EXPECTED_TEST_DOCS and not has_description(item)
    ]
    if missing or undocumented:
        return failed(
            "singular_data_tests_have_descriptions",
            {"missing": missing, "undocumented": undocumented},
            sorted(EXPECTED_TEST_DOCS),
        )
    return passed("singular_data_tests_have_descriptions", sorted(observed & EXPECTED_TEST_DOCS), sorted(EXPECTED_TEST_DOCS))


def validate_exposure_documentation(project_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    exposures_yaml = read_yaml(project_root / "models" / "exposures.yml")
    exposure = next(
        (item for item in exposures_yaml.get("exposures", []) if isinstance(item, dict) and item.get("name") == EXPOSURE_NAME),
        None,
    )
    if exposure is None:
        return [failed("exposure_declares_downstream_owner", None, EXPOSURE_NAME)], summary
    owner = exposure.get("owner") or {}
    observed = {
        "type": exposure.get("type"),
        "maturity": exposure.get("maturity"),
        "owner": owner,
        "depends_on": exposure.get("depends_on"),
    }
    summary["exposure"] = observed
    owner_ok = bool(owner.get("name")) and bool(owner.get("email"))
    if exposure.get("type") == "dashboard" and exposure.get("maturity") == "high" and owner_ok and has_description(exposure):
        checks.append(passed("exposure_declares_downstream_owner", observed, "dashboard/high with owner"))
    else:
        checks.append(failed("exposure_declares_downstream_owner", observed, "dashboard/high with owner and description"))

    expected_ref_calls = {"ref('mart_customer_revenue_health')", "ref('fct_order_revenue_daily')", "ref('int_subscription_history')"}
    observed_ref_calls = set(exposure.get("depends_on") or [])
    direct_sources = sorted(item for item in observed_ref_calls if item.startswith("source("))
    missing_refs = sorted(expected_ref_calls - observed_ref_calls)
    if direct_sources or missing_refs:
        checks.append(
            failed(
                "exposure_depends_on_documented_models_not_raw_sources",
                {"missing_refs": missing_refs, "direct_sources": direct_sources},
                sorted(expected_ref_calls),
            )
        )
    else:
        checks.append(passed("exposure_depends_on_documented_models_not_raw_sources", sorted(observed_ref_calls), sorted(expected_ref_calls)))

    claim_errors: list[dict[str, Any]] = []
    observed_claims = {
        claim.get("id"): claim
        for claim in (exposure.get("meta") or {}).get("decision_claims", [])
        if isinstance(claim, dict) and claim.get("id")
    }
    for claim_id, expected in EXPECTED_DECISION_CLAIMS.items():
        claim = observed_claims.get(claim_id)
        if claim is None:
            claim_errors.append({"claim": claim_id, "problem": "missing"})
            continue
        upstream = set(claim.get("upstream_models") or [])
        tests = set(claim.get("required_tests") or [])
        if upstream != expected["upstream_models"] or tests != expected["required_tests"] or not claim.get("claim"):
            claim_errors.append(
                {
                    "claim": claim_id,
                    "upstream_models": sorted(upstream),
                    "required_tests": sorted(tests),
                    "expected": {key: sorted(value) for key, value in expected.items()},
                }
            )
    if claim_errors:
        checks.append(failed("exposure_claims_link_to_models_and_tests", claim_errors, "decision claims with upstream models and tests"))
    else:
        checks.append(passed("exposure_claims_link_to_models_and_tests", sorted(observed_claims), sorted(EXPECTED_DECISION_CLAIMS)))
    return checks, summary


def validate_static_project(project_root: Path, data_contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks, summary = validate_project_identity(project_root)
    if not all(check["valid"] for check in checks):
        return checks, summary
    checks.append(validate_docs_blocks(project_root))
    checks.append(validate_sources_documentation(project_root, data_contract))
    model_checks, model_summary = validate_models_documentation(project_root)
    exposure_checks, exposure_summary = validate_exposure_documentation(project_root)
    checks.extend(model_checks)
    checks.append(validate_snapshot_documentation(project_root))
    checks.append(validate_test_documentation(project_root))
    checks.extend(exposure_checks)
    summary.update(model_summary)
    summary.update(exposure_summary)
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


def tail(text: str, line_count: int = 8) -> str:
    lines = ANSI_RE.sub("", text).splitlines()
    return "\n".join(lines[-line_count:])


def run_command(command: list[str], env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    return {
        "command": " ".join(command[:7]),
        "returncode": completed.returncode,
        "stdout_tail": tail(completed.stdout),
        "stderr_tail": tail(completed.stderr),
    }


def validate_generated_artifacts(project_copy: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    manifest_path = project_copy / "target" / "manifest.json"
    catalog_path = project_copy / "target" / "catalog.json"
    summary: dict[str, Any] = {}
    if not manifest_path.is_file() or not catalog_path.is_file():
        return [failed("docs_generate_writes_manifest_and_catalog", {"manifest": manifest_path.is_file(), "catalog": catalog_path.is_file()}, "manifest.json and catalog.json")], summary

    manifest = read_json(manifest_path)
    catalog = read_json(catalog_path)
    summary["artifact_counts"] = {
        "nodes": len(manifest.get("nodes", {})),
        "sources": len(manifest.get("sources", {})),
        "exposures": len(manifest.get("exposures", {})),
        "docs": len(manifest.get("docs", {})),
        "catalog_nodes": len(catalog.get("nodes", {})),
        "catalog_sources": len(catalog.get("sources", {})),
    }
    project_name = (manifest.get("metadata") or {}).get("project_name")
    if project_name == EXPECTED_PROJECT_NAME and not catalog.get("errors"):
        checks.append(passed("docs_generate_writes_manifest_and_catalog", summary["artifact_counts"], "valid manifest/catalog without catalog errors"))
    else:
        checks.append(
            failed(
                "docs_generate_writes_manifest_and_catalog",
                {"project_name": project_name, "catalog_errors": catalog.get("errors")},
                EXPECTED_PROJECT_NAME,
            )
        )

    doc_names = {doc.get("name") for doc in manifest.get("docs", {}).values() if isinstance(doc, dict)}
    missing_docs = sorted(EXPECTED_DOC_BLOCKS - doc_names)
    if missing_docs:
        checks.append(failed("manifest_contains_docs_blocks", sorted(doc_names), sorted(EXPECTED_DOC_BLOCKS), missing_docs))
    else:
        checks.append(passed("manifest_contains_docs_blocks", sorted(EXPECTED_DOC_BLOCKS), sorted(EXPECTED_DOC_BLOCKS)))

    exposure_id = f"exposure.{EXPECTED_PROJECT_NAME}.{EXPOSURE_NAME}"
    exposure = manifest.get("exposures", {}).get(exposure_id)
    if exposure is None:
        checks.append(failed("manifest_exposure_lineage_resolves", None, exposure_id))
    else:
        observed_depends = set((exposure.get("depends_on") or {}).get("nodes") or [])
        if observed_depends == EXPECTED_EXPOSURE_DEPENDS_ON:
            checks.append(passed("manifest_exposure_lineage_resolves", sorted(observed_depends), sorted(EXPECTED_EXPOSURE_DEPENDS_ON)))
        else:
            checks.append(failed("manifest_exposure_lineage_resolves", sorted(observed_depends), sorted(EXPECTED_EXPOSURE_DEPENDS_ON)))

    test_names = {node.get("name") for node in manifest.get("nodes", {}).values() if isinstance(node, dict) and node.get("resource_type") == "test"}
    missing_tests = sorted(EXPECTED_TEST_DOCS - test_names)
    undocumented_tests = sorted(
        node.get("name")
        for node in manifest.get("nodes", {}).values()
        if isinstance(node, dict)
        and node.get("resource_type") == "test"
        and node.get("name") in EXPECTED_TEST_DOCS
        and not has_description(node)
    )
    if missing_tests or undocumented_tests:
        checks.append(
            failed(
                "manifest_claim_tests_are_documented",
                {"missing_tests": missing_tests, "undocumented_tests": undocumented_tests},
                sorted(EXPECTED_TEST_DOCS),
            )
        )
    else:
        checks.append(passed("manifest_claim_tests_are_documented", sorted(EXPECTED_TEST_DOCS), "documented test nodes"))

    catalog_resources = set(catalog.get("nodes", {})) | set(catalog.get("sources", {}))
    missing_catalog_resources = sorted(EXPECTED_CATALOG_RESOURCE_IDS - catalog_resources)
    catalog_column_errors: list[dict[str, Any]] = []
    for resource_id in EXPECTED_CATALOG_RESOURCE_IDS & catalog_resources:
        resource = (catalog.get("nodes", {}).get(resource_id) or catalog.get("sources", {}).get(resource_id) or {})
        columns = resource.get("columns") or {}
        if len(columns) == 0:
            catalog_column_errors.append({"resource": resource_id, "problem": "no catalog columns"})
    if missing_catalog_resources or catalog_column_errors:
        checks.append(
            failed(
                "catalog_contains_key_resources_and_columns",
                {"missing": missing_catalog_resources, "column_errors": catalog_column_errors},
                sorted(EXPECTED_CATALOG_RESOURCE_IDS),
            )
        )
    else:
        checks.append(passed("catalog_contains_key_resources_and_columns", sorted(EXPECTED_CATALOG_RESOURCE_IDS), "catalog resources with columns"))
    return checks, summary


def run_dbt_docs_audit(
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
        db_path = tmp / "documentation.duckdb"
        env = os.environ.copy()
        env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
        env["DBT_DUCKDB_PATH"] = str(db_path)
        base = ["--project-dir", str(project_copy), "--profiles-dir", str(profiles_dir)]
        summary["loaded_raw_rows"] = prepare_duckdb_database(db_path, data_contract, data_dir)
        commands = [
            run_command(["dbt", "parse", *base], env),
            run_command(["dbt", "run", "--exclude", "int_subscription_history", *base], env),
            run_command(["dbt", "snapshot", "--select", "subscription_status_snapshot", *base], env),
            run_command(["dbt", "run", "--select", "int_subscription_history", *base], env),
            run_command(["dbt", "test", "--select", "test_type:data", *base], env),
            run_command(["dbt", "docs", "generate", *base], env),
        ]
        summary["dbt_commands"] = commands
        if any(command["returncode"] != 0 for command in commands):
            checks.append(failed("dbt_docs_generate_succeeds", commands, "parse, run, snapshot, test and docs generate exit 0"))
            return checks, summary
        checks.append(passed("dbt_docs_generate_succeeds", [command["command"] for command in commands], "dbt docs generate"))
        artifact_checks, artifact_summary = validate_generated_artifacts(project_copy)
        checks.extend(artifact_checks)
        summary.update(artifact_summary)
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
        live_checks, live_summary = run_dbt_docs_audit(project_root, data_contract, resolved_data_dir)
        checks.extend(live_checks)
        summary.update(live_summary)
    elif run_dbt:
        checks.append(failed("dbt_docs_generate_succeeds", "skipped because static checks failed", "dbt docs generate"))
    return {"valid": all(check["valid"] for check in checks), "summary": summary, "checks": checks}


def parse_args() -> argparse.Namespace:
    lesson_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Audit dbt documentation, exposure lineage and docs artifacts.")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parent / "documentation_project",
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
    parser.add_argument("--run-dbt", action="store_true", help="Run live dbt docs generate checks.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = validate_project(args.project, args.data_contract, args.data_dir, args.run_dbt)
    payload = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
