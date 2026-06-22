from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml


SOURCE_NAME = "raw_app"
EXPECTED_MODELS: dict[str, dict[str, Any]] = {
    "stg_users": {"layer": "staging", "materialized": "view"},
    "stg_events": {"layer": "staging", "materialized": "view"},
    "stg_orders": {"layer": "staging", "materialized": "view"},
    "stg_order_items": {"layer": "staging", "materialized": "view"},
    "stg_subscriptions": {"layer": "staging", "materialized": "view"},
    "stg_support_tickets": {"layer": "staging", "materialized": "view"},
    "stg_refunds": {"layer": "staging", "materialized": "view"},
    "stg_currency_rates": {"layer": "staging", "materialized": "view"},
    "int_order_line_revenue": {"layer": "intermediate", "materialized": "ephemeral"},
    "int_refunds_by_order": {"layer": "intermediate", "materialized": "ephemeral"},
    "int_support_by_user": {"layer": "intermediate", "materialized": "view"},
    "int_subscription_latest": {"layer": "intermediate", "materialized": "view"},
    "mart_customer_revenue_health": {"layer": "marts", "materialized": "table"},
}
REQUIRED_META_KEYS = {
    "layer",
    "grain",
    "consumer",
    "materialization_reason",
    "cost_note",
}
MART_REQUIRED_REFS = {
    "stg_users",
    "stg_currency_rates",
    "int_order_line_revenue",
    "int_refunds_by_order",
    "int_support_by_user",
    "int_subscription_latest",
}
DISALLOWED_IN_THIS_LESSON = {"incremental", "materialized_view"}
RAW_IDENTIFIER_RE = re.compile(r"\braw_[a-z0-9_]+\b", flags=re.IGNORECASE)
SOURCE_CALL_RE = re.compile(r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)")
REF_CALL_RE = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]")
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


def source_table_name(raw_identifier: str) -> str:
    return raw_identifier.removeprefix("raw_")


def sql_files(project_root: Path) -> list[Path]:
    return sorted((project_root / "models").rglob("*.sql"))


def model_name_from_path(path: Path) -> str:
    return path.stem


def path_layer(project_root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(project_root / "models")
    except ValueError:
        return "unknown"
    return relative.parts[0] if relative.parts else "unknown"


def load_model_specs(project_root: Path) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for yaml_path in sorted((project_root / "models").rglob("*.yml")):
        value = read_yaml(yaml_path)
        for item in value.get("models", []):
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                specs[item["name"]] = item
    return specs


def load_source_declarations(project_root: Path) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for yaml_path in sorted((project_root / "models").rglob("*.yml")):
        value = read_yaml(yaml_path)
        for source in value.get("sources", []):
            if isinstance(source, dict):
                declarations.append(source)
    return declarations


def collect_sql_usage(project_root: Path, raw_identifiers: set[str]) -> dict[str, dict[str, Any]]:
    usage: dict[str, dict[str, Any]] = {}
    for path in sql_files(project_root):
        text = path.read_text(encoding="utf-8")
        usage[model_name_from_path(path)] = {
            "path": str(path.relative_to(project_root)),
            "layer": path_layer(project_root, path),
            "source_calls": SOURCE_CALL_RE.findall(text),
            "ref_calls": REF_CALL_RE.findall(text),
            "raw_identifiers": sorted(
                {identifier for identifier in RAW_IDENTIFIER_RE.findall(text) if identifier in raw_identifiers}
            ),
        }
    return usage


def validate_sources(project_root: Path, data_contract: dict[str, Any]) -> dict[str, Any]:
    tables = data_contract_tables(data_contract)
    expected_sources = {source_table_name(name): name for name in tables}
    raw_source = next(
        (source for source in load_source_declarations(project_root) if source.get("name") == SOURCE_NAME),
        None,
    )
    if raw_source is None:
        return failed("raw_sources_are_declared", None, f"source named {SOURCE_NAME}", [SOURCE_NAME])
    declared = {
        table.get("name"): table.get("identifier")
        for table in raw_source.get("tables", [])
        if isinstance(table, dict)
    }
    missing = sorted(set(expected_sources) - set(declared))
    identifier_errors = [
        {"source": source_name, "observed": declared.get(source_name), "expected": raw_identifier}
        for source_name, raw_identifier in sorted(expected_sources.items())
        if source_name in declared and declared[source_name] != raw_identifier
    ]
    if missing or identifier_errors:
        sample: list[Any] = [{"missing": item} for item in missing]
        sample.extend(identifier_errors)
        return failed(
            "raw_sources_are_declared",
            {"missing": missing, "identifier_errors": identifier_errors},
            "all data contract tables declared as sources",
            sample,
        )
    return passed("raw_sources_are_declared", len(expected_sources), "all data contract tables")


def validate_materialization_specs(
    specs: dict[str, dict[str, Any]],
    usage: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing_models = sorted(set(EXPECTED_MODELS) - set(usage))
    extra_models = sorted(set(usage) - set(EXPECTED_MODELS))
    if missing_models or extra_models:
        checks.append(
            failed(
                "expected_models_exist",
                {"missing": missing_models, "extra": extra_models},
                sorted(EXPECTED_MODELS),
                missing_models + extra_models,
            )
        )
    else:
        checks.append(passed("expected_models_exist", sorted(EXPECTED_MODELS), "all expected SQL models"))

    materialization_errors: list[dict[str, Any]] = []
    meta_errors: list[dict[str, Any]] = []
    observed_materializations: dict[str, str | None] = {}
    for model_name, expected in sorted(EXPECTED_MODELS.items()):
        spec = specs.get(model_name, {})
        config = spec.get("config") if isinstance(spec.get("config"), dict) else {}
        materialized = config.get("materialized")
        observed_materializations[model_name] = materialized
        if materialized != expected["materialized"]:
            materialization_errors.append(
                {
                    "model": model_name,
                    "observed": materialized,
                    "expected": expected["materialized"],
                }
            )
        meta = spec.get("meta") if isinstance(spec.get("meta"), dict) else {}
        missing_meta = sorted(REQUIRED_META_KEYS - set(meta))
        if meta.get("layer") != expected["layer"]:
            missing_meta.append("layer_mismatch")
        if missing_meta:
            meta_errors.append({"model": model_name, "missing_or_wrong_meta": missing_meta})

    if materialization_errors:
        checks.append(
            failed(
                "materializations_match_policy",
                materialization_errors,
                "declared materialization per model policy",
                materialization_errors,
            )
        )
    else:
        checks.append(
            passed(
                "materializations_match_policy",
                dict(sorted(observed_materializations.items())),
                "declared materialization per model policy",
            )
        )
    if meta_errors:
        checks.append(
            failed(
                "materialization_decisions_documented",
                meta_errors,
                f"meta keys {sorted(REQUIRED_META_KEYS)} per model",
                meta_errors,
            )
        )
    else:
        checks.append(
            passed("materialization_decisions_documented", len(EXPECTED_MODELS), "all decisions documented")
        )

    disallowed = sorted(
        model_name
        for model_name, materialized in observed_materializations.items()
        if materialized in DISALLOWED_IN_THIS_LESSON
    )
    if disallowed:
        checks.append(
            failed(
                "no_future_materializations_in_this_lesson",
                disallowed,
                "incremental/materialized_view are reserved for later lessons",
                disallowed,
            )
        )
    else:
        checks.append(
            passed("no_future_materializations_in_this_lesson", "ok", "no incremental/materialized_view")
        )
    return checks


def validate_sql_boundaries(usage: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    staging_errors = sorted(
        name
        for name, item in usage.items()
        if item["layer"] == "staging" and len(item["source_calls"]) != 1
    )
    non_staging_source_errors = sorted(
        name for name, item in usage.items() if item["layer"] != "staging" and item["source_calls"]
    )
    if staging_errors or non_staging_source_errors:
        checks.append(
            failed(
                "source_calls_stay_in_staging",
                {"staging_errors": staging_errors, "non_staging_source_errors": non_staging_source_errors},
                "staging reads sources; downstream reads models",
                staging_errors + non_staging_source_errors,
            )
        )
    else:
        checks.append(passed("source_calls_stay_in_staging", "ok", "staging source boundary"))

    downstream_without_ref = sorted(
        name for name, item in usage.items() if item["layer"] != "staging" and not item["ref_calls"]
    )
    if downstream_without_ref:
        checks.append(
            failed(
                "downstream_models_use_ref",
                downstream_without_ref,
                "intermediate and mart models use ref()",
                downstream_without_ref,
            )
        )
    else:
        checks.append(passed("downstream_models_use_ref", "ok", "ref() dependencies"))

    raw_mentions = [
        {"model": name, "path": item["path"], "raw_identifiers": item["raw_identifiers"]}
        for name, item in usage.items()
        if item["raw_identifiers"]
    ]
    if raw_mentions:
        checks.append(
            failed("sql_has_no_direct_raw_references", raw_mentions, "use source()/ref()", raw_mentions)
        )
    else:
        checks.append(passed("sql_has_no_direct_raw_references", "ok", "no direct raw identifiers"))

    mart_refs = set(usage.get("mart_customer_revenue_health", {}).get("ref_calls", []))
    missing_mart_refs = sorted(MART_REQUIRED_REFS - mart_refs)
    if missing_mart_refs:
        checks.append(
            failed(
                "mart_uses_required_upstream_models",
                missing_mart_refs,
                sorted(MART_REQUIRED_REFS),
                missing_mart_refs,
            )
        )
    else:
        checks.append(
            passed("mart_uses_required_upstream_models", sorted(mart_refs), "customer mart dependencies")
        )
    return checks


def validate_ephemeral_fanout(usage: dict[str, dict[str, Any]]) -> dict[str, Any]:
    children: dict[str, list[str]] = {name: [] for name, expected in EXPECTED_MODELS.items() if expected["materialized"] == "ephemeral"}
    for consumer, item in usage.items():
        for ref_name in item["ref_calls"]:
            if ref_name in children:
                children[ref_name].append(consumer)
    fanout_errors = [
        {"model": model, "children": sorted(consumers)}
        for model, consumers in sorted(children.items())
        if not consumers or len(set(consumers)) > 2
    ]
    if fanout_errors:
        return failed(
            "ephemeral_models_have_limited_fanout",
            fanout_errors,
            "ephemeral models used by one or two downstream models",
            fanout_errors,
        )
    return passed(
        "ephemeral_models_have_limited_fanout",
        {model: sorted(consumers) for model, consumers in sorted(children.items())},
        "one or two downstream consumers",
    )


def validate_static_project(project_root: Path, data_contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"project_root": str(project_root)}
    if not project_root.is_dir():
        return [failed("project_root_exists", str(project_root), "existing directory")], summary
    checks.append(passed("project_root_exists", str(project_root), "existing directory"))
    required_files = ["dbt_project.yml", "profiles.yml.example", "commands.md", "models/sources.yml", "models/properties.yml"]
    missing_files = [path for path in required_files if not (project_root / path).is_file()]
    if missing_files:
        checks.append(failed("required_project_files_exist", missing_files, required_files, missing_files))
        return checks, summary
    checks.append(passed("required_project_files_exist", required_files, "required files"))

    tables = data_contract_tables(data_contract)
    usage = collect_sql_usage(project_root, set(tables))
    specs = load_model_specs(project_root)
    materializations = {
        model: (specs.get(model, {}).get("config") or {}).get("materialized")
        for model in sorted(EXPECTED_MODELS)
    }
    summary["models"] = sorted(usage)
    summary["materializations"] = materializations
    summary["materialization_counts"] = dict(sorted(Counter(materializations.values()).items()))

    checks.append(validate_sources(project_root, data_contract))
    checks.extend(validate_materialization_specs(specs, usage))
    checks.extend(validate_sql_boundaries(usage))
    checks.append(validate_ephemeral_fanout(usage))
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
        "command": " ".join(command[:2]),
        "returncode": completed.returncode,
        "stdout_tail": tail(completed.stdout),
        "stderr_tail": tail(completed.stderr),
    }


def normalize_relation_type(table_type: str) -> str:
    lowered = table_type.lower()
    if "view" in lowered:
        return "view"
    if "table" in lowered:
        return "table"
    return lowered


def inspect_physical_relations(db_path: Path) -> dict[str, str]:
    import duckdb

    con = duckdb.connect(str(db_path))
    try:
        rows = con.execute(
            """
            select table_name, table_type
            from information_schema.tables
            where table_schema = 'analytics'
            order by table_name
            """
        ).fetchall()
    finally:
        con.close()
    return {str(name): normalize_relation_type(str(kind)) for name, kind in rows}


def decimal_string(value: Any) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):.2f}"


def inspect_mart_rows(db_path: Path) -> list[dict[str, Any]]:
    import duckdb

    con = duckdb.connect(str(db_path))
    try:
        rows = con.execute(
            """
            select
                user_id,
                latest_subscription_status,
                has_active_subscription,
                order_count,
                paid_order_count,
                gross_revenue_rub,
                paid_revenue_rub,
                refunded_amount_rub,
                support_ticket_count,
                high_priority_ticket_count,
                revenue_health_segment
            from analytics.mart_customer_revenue_health
            order by user_id
            """
        ).fetchall()
    finally:
        con.close()
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "user_id": row[0],
                "latest_subscription_status": row[1],
                "has_active_subscription": bool(row[2]),
                "order_count": int(row[3]),
                "paid_order_count": int(row[4]),
                "gross_revenue_rub": decimal_string(row[5]),
                "paid_revenue_rub": decimal_string(row[6]),
                "refunded_amount_rub": decimal_string(row[7]),
                "support_ticket_count": int(row[8]),
                "high_priority_ticket_count": int(row[9]),
                "revenue_health_segment": row[10],
            }
        )
    return result


def expected_mart_rows() -> list[dict[str, Any]]:
    return [
        {
            "user_id": "u001",
            "latest_subscription_status": "active",
            "has_active_subscription": True,
            "order_count": 1,
            "paid_order_count": 1,
            "gross_revenue_rub": "1200.00",
            "paid_revenue_rub": "1200.00",
            "refunded_amount_rub": "0.00",
            "support_ticket_count": 0,
            "high_priority_ticket_count": 0,
            "revenue_health_segment": "monetized",
        },
        {
            "user_id": "u002",
            "latest_subscription_status": "active",
            "has_active_subscription": True,
            "order_count": 1,
            "paid_order_count": 1,
            "gross_revenue_rub": "800.00",
            "paid_revenue_rub": "800.00",
            "refunded_amount_rub": "0.00",
            "support_ticket_count": 0,
            "high_priority_ticket_count": 0,
            "revenue_health_segment": "monetized",
        },
        {
            "user_id": "u003",
            "latest_subscription_status": "cancelled",
            "has_active_subscription": False,
            "order_count": 1,
            "paid_order_count": 0,
            "gross_revenue_rub": "1500.00",
            "paid_revenue_rub": "0.00",
            "refunded_amount_rub": "1500.00",
            "support_ticket_count": 1,
            "high_priority_ticket_count": 0,
            "revenue_health_segment": "needs_attention",
        },
        {
            "user_id": "u004",
            "latest_subscription_status": "none",
            "has_active_subscription": False,
            "order_count": 0,
            "paid_order_count": 0,
            "gross_revenue_rub": "0.00",
            "paid_revenue_rub": "0.00",
            "refunded_amount_rub": "0.00",
            "support_ticket_count": 1,
            "high_priority_ticket_count": 1,
            "revenue_health_segment": "needs_attention",
        },
        {
            "user_id": "u005",
            "latest_subscription_status": "active",
            "has_active_subscription": True,
            "order_count": 1,
            "paid_order_count": 1,
            "gross_revenue_rub": "2312.50",
            "paid_revenue_rub": "2312.50",
            "refunded_amount_rub": "0.00",
            "support_ticket_count": 0,
            "high_priority_ticket_count": 0,
            "revenue_health_segment": "high_value",
        },
    ]


def inspect_manifest(manifest_path: Path, relations: dict[str, str], mart_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest = read_json(manifest_path)
    nodes = {
        node.get("name"): node
        for node in manifest.get("nodes", {}).values()
        if isinstance(node, dict) and node.get("resource_type") == "model"
    }
    checks: list[dict[str, Any]] = []
    manifest_errors: list[dict[str, Any]] = []
    for model_name, expected in sorted(EXPECTED_MODELS.items()):
        node = nodes.get(model_name)
        observed = None
        if isinstance(node, dict):
            observed = (node.get("config") or {}).get("materialized")
        if observed != expected["materialized"]:
            manifest_errors.append({"model": model_name, "observed": observed, "expected": expected["materialized"]})
    if manifest_errors:
        checks.append(
            failed("manifest_materializations_match_policy", manifest_errors, "manifest config matches policy", manifest_errors)
        )
    else:
        checks.append(passed("manifest_materializations_match_policy", sorted(EXPECTED_MODELS), "manifest config"))

    relation_errors: list[dict[str, Any]] = []
    expected_relation_counts: Counter[str] = Counter()
    for model_name, expected in sorted(EXPECTED_MODELS.items()):
        materialized = expected["materialized"]
        if materialized == "ephemeral":
            if model_name in relations:
                relation_errors.append({"model": model_name, "observed": relations[model_name], "expected": "no relation"})
            continue
        expected_relation_counts[materialized] += 1
        if relations.get(model_name) != materialized:
            relation_errors.append({"model": model_name, "observed": relations.get(model_name), "expected": materialized})
    if relation_errors:
        checks.append(
            failed(
                "physical_relations_match_materializations",
                relation_errors,
                "views/tables exist and ephemeral models do not",
                relation_errors,
            )
        )
    else:
        checks.append(
            passed(
                "physical_relations_match_materializations",
                dict(sorted(Counter(relations.values()).items())),
                dict(sorted(expected_relation_counts.items())),
            )
        )

    mart_node = nodes.get("mart_customer_revenue_health", {})
    compiled = ""
    if isinstance(mart_node, dict):
        compiled = str(mart_node.get("compiled_code") or mart_node.get("compiled_sql") or "")
    missing_ctes = [
        cte
        for cte in ("__dbt__cte__int_order_line_revenue", "__dbt__cte__int_refunds_by_order")
        if cte not in compiled
    ]
    if missing_ctes:
        checks.append(
            failed("compiled_mart_inlines_ephemeral_models", missing_ctes, "ephemeral CTE names in compiled SQL", missing_ctes)
        )
    else:
        checks.append(
            passed("compiled_mart_inlines_ephemeral_models", "ok", "ephemeral CTE names in compiled SQL")
        )

    expected_rows = expected_mart_rows()
    if mart_rows != expected_rows:
        checks.append(
            failed(
                "mart_matches_independent_control",
                mart_rows,
                expected_rows,
                [{"observed": mart_rows, "expected": expected_rows}],
            )
        )
    else:
        checks.append(passed("mart_matches_independent_control", len(mart_rows), "expected mart rows"))
    return checks


def run_dbt_audit(
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
        db_path = tmp / "materialization.duckdb"
        row_counts = prepare_duckdb_database(db_path, data_contract, data_dir)

        env = os.environ.copy()
        env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
        env["DBT_DUCKDB_PATH"] = str(db_path)

        commands = [
            run_command(
                ["dbt", "parse", "--project-dir", str(project_copy), "--profiles-dir", str(profiles_dir)],
                env,
            ),
            run_command(
                [
                    "dbt",
                    "compile",
                    "--select",
                    "mart_customer_revenue_health",
                    "--project-dir",
                    str(project_copy),
                    "--profiles-dir",
                    str(profiles_dir),
                ],
                env,
            ),
            run_command(
                ["dbt", "run", "--project-dir", str(project_copy), "--profiles-dir", str(profiles_dir)],
                env,
            ),
        ]
        summary["loaded_raw_rows"] = row_counts
        summary["dbt_commands"] = commands
        if not all(item["returncode"] == 0 for item in commands):
            checks.append(failed("dbt_parse_compile_run_succeed", commands, "all dbt commands exit 0", commands))
            return checks, summary
        checks.append(passed("dbt_parse_compile_run_succeed", "ok", "all dbt commands exit 0"))
        relations = inspect_physical_relations(db_path)
        mart_rows = inspect_mart_rows(db_path)
        summary["physical_relations"] = relations
        summary["physical_relation_counts"] = dict(sorted(Counter(relations.values()).items()))
        summary["mart_row_count"] = len(mart_rows)
        checks.extend(inspect_manifest(project_copy / "target" / "manifest.json", relations, mart_rows))
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
        checks.append(
            failed(
                "dbt_parse_compile_run_succeed",
                "skipped because static checks failed",
                "all dbt commands exit 0",
            )
        )
    return {"valid": all(check["valid"] for check in checks), "summary": summary, "checks": checks}


def parse_args() -> argparse.Namespace:
    lesson_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Audit dbt model materializations and compiled mart logic.")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parent / "materialization_project",
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
    parser.add_argument("--run-dbt", action="store_true", help="Run dbt parse, compile and run in a temporary copy.")
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
