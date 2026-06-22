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
EXPECTED_STAGING_MODELS = {"stg_users", "stg_orders", "stg_order_items"}
EXPECTED_DOWNSTREAM_MODELS = {"int_order_line_revenue", "mart_customer_revenue_health"}
EXPECTED_DBT_COMMANDS = ("parse", "compile", "source freshness")
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


def source_table_name(raw_identifier: str) -> str:
    return raw_identifier.removeprefix("raw_")


def data_contract_tables(data_contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    tables = data_contract.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("data contract must contain a tables object")
    return {str(name): table for name, table in tables.items() if isinstance(table, dict)}


def load_source_declarations(project_root: Path) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for yaml_path in sorted((project_root / "models").rglob("*.yml")):
        value = read_yaml(yaml_path)
        sources = value.get("sources", [])
        if isinstance(sources, list):
            declarations.extend(source for source in sources if isinstance(source, dict))
    return declarations


def find_source(declarations: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((source for source in declarations if source.get("name") == name), None)


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


def validate_static_project(project_root: Path, data_contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"project_root": str(project_root)}
    if not project_root.is_dir():
        return [failed("project_root_exists", str(project_root), "existing directory")], summary
    checks.append(passed("project_root_exists", str(project_root), "existing directory"))

    tables = data_contract_tables(data_contract)
    expected_sources = {source_table_name(name): name for name in tables}
    declarations = load_source_declarations(project_root)
    raw_source = find_source(declarations, SOURCE_NAME)
    if raw_source is None:
        checks.append(failed("raw_source_declared", None, f"source named {SOURCE_NAME}", [SOURCE_NAME]))
        return checks, summary
    checks.append(passed("raw_source_declared", SOURCE_NAME, "source declaration exists"))

    source_tables = raw_source.get("tables", [])
    declared: dict[str, dict[str, Any]] = {}
    if isinstance(source_tables, list):
        for table in source_tables:
            if isinstance(table, dict) and isinstance(table.get("name"), str):
                declared[table["name"]] = table
    summary["declared_sources"] = sorted(declared)
    missing = sorted(set(expected_sources) - set(declared))
    extra = sorted(set(declared) - set(expected_sources))
    identifier_errors: list[dict[str, Any]] = []
    freshness_errors: list[dict[str, Any]] = []
    for source_name, raw_identifier in expected_sources.items():
        table = declared.get(source_name)
        if table is None:
            continue
        if table.get("identifier") != raw_identifier:
            identifier_errors.append(
                {
                    "source": source_name,
                    "observed": table.get("identifier"),
                    "expected": raw_identifier,
                }
            )
        config = table.get("config") if isinstance(table.get("config"), dict) else {}
        contract_freshness = tables[raw_identifier].get("freshness_column")
        if config.get("loaded_at_field") != contract_freshness:
            freshness_errors.append(
                {
                    "source": source_name,
                    "observed": config.get("loaded_at_field"),
                    "expected": contract_freshness,
                }
            )
        freshness = config.get("freshness") if isinstance(config.get("freshness"), dict) else {}
        if "warn_after" not in freshness or "error_after" not in freshness:
            freshness_errors.append(
                {
                    "source": source_name,
                    "observed": sorted(freshness),
                    "expected": ["warn_after", "error_after"],
                }
            )

    if missing or extra or identifier_errors:
        sample: list[Any] = []
        sample.extend({"missing": item} for item in missing)
        sample.extend({"extra": item} for item in extra)
        sample.extend(identifier_errors)
        checks.append(
            failed(
                "sources_match_data_contract",
                {"missing": missing, "extra": extra, "identifier_errors": identifier_errors},
                "all data contract tables declared as sources with matching identifiers",
                sample,
            )
        )
    else:
        checks.append(passed("sources_match_data_contract", len(expected_sources), "all data contract tables"))

    if freshness_errors:
        checks.append(
            failed(
                "sources_have_freshness_config",
                len(freshness_errors),
                "loaded_at_field plus warn_after/error_after per source table",
                freshness_errors,
            )
        )
    else:
        checks.append(passed("sources_have_freshness_config", len(expected_sources), "freshness configured"))

    usage = collect_sql_usage(project_root, set(tables))
    summary["models"] = sorted(usage)
    staging_without_source = sorted(
        name
        for name, item in usage.items()
        if item["layer"] == "staging" and not item["source_calls"]
    )
    non_staging_with_source = sorted(
        name
        for name, item in usage.items()
        if item["layer"] != "staging" and item["source_calls"]
    )
    missing_expected_staging = sorted(EXPECTED_STAGING_MODELS - set(usage))
    if staging_without_source or non_staging_with_source or missing_expected_staging:
        checks.append(
            failed(
                "source_calls_stay_in_staging",
                {
                    "staging_without_source": staging_without_source,
                    "non_staging_with_source": non_staging_with_source,
                    "missing_expected_staging": missing_expected_staging,
                },
                "staging models use source(); downstream models do not",
                staging_without_source + non_staging_with_source + missing_expected_staging,
            )
        )
    else:
        checks.append(passed("source_calls_stay_in_staging", sorted(EXPECTED_STAGING_MODELS), "source() in staging"))

    downstream_without_ref = sorted(
        name for name in EXPECTED_DOWNSTREAM_MODELS if not usage.get(name, {}).get("ref_calls")
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
        checks.append(passed("downstream_models_use_ref", sorted(EXPECTED_DOWNSTREAM_MODELS), "ref() present"))

    raw_mentions = [
        {"model": name, "path": item["path"], "raw_identifiers": item["raw_identifiers"]}
        for name, item in usage.items()
        if item["raw_identifiers"]
    ]
    if raw_mentions:
        checks.append(
            failed(
                "sql_has_no_direct_raw_references",
                len(raw_mentions),
                "SQL models use source()/ref(), not raw_* names",
                raw_mentions,
            )
        )
    else:
        checks.append(passed("sql_has_no_direct_raw_references", "ok", "no raw_* identifiers in SQL"))

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


def source_state_counts(freshness_path: Path) -> dict[str, int]:
    value = read_json(freshness_path)
    counts: Counter[str] = Counter()
    results = value.get("results")
    if isinstance(results, list):
        for result in results:
            if isinstance(result, dict):
                counts[str(result.get("status", "unknown"))] += 1
        return dict(sorted(counts.items()))
    sources = value.get("sources", {})
    if isinstance(sources, dict):
        for source in sources.values():
            if isinstance(source, dict):
                counts[str(source.get("state", "unknown"))] += 1
    return dict(sorted(counts.items()))


def inspect_manifest(manifest_path: Path, data_contract: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = read_json(manifest_path)
    nodes = manifest.get("nodes", {})
    sources = manifest.get("sources", {})
    checks: list[dict[str, Any]] = []
    tables = data_contract_tables(data_contract)
    expected_source_names = {source_table_name(name) for name in tables}
    source_nodes = {
        source.get("name")
        for source in sources.values()
        if isinstance(source, dict) and source.get("source_name") == SOURCE_NAME
    }
    missing_sources = sorted(expected_source_names - {name for name in source_nodes if isinstance(name, str)})
    if missing_sources:
        checks.append(
            failed("manifest_contains_declared_sources", missing_sources, "all source nodes", missing_sources)
        )
    else:
        checks.append(passed("manifest_contains_declared_sources", len(expected_source_names), "all source nodes"))

    model_nodes = {
        node.get("name"): node
        for node in nodes.values()
        if isinstance(node, dict) and node.get("resource_type") == "model"
    }
    staging_errors: list[dict[str, Any]] = []
    downstream_errors: list[dict[str, Any]] = []
    for name in EXPECTED_STAGING_MODELS:
        node = model_nodes.get(name)
        deps = set(node.get("depends_on", {}).get("nodes", [])) if isinstance(node, dict) else set()
        source_deps = sorted(dep for dep in deps if dep.startswith("source."))
        if len(source_deps) != 1:
            staging_errors.append({"model": name, "source_dependencies": source_deps})
    for name in EXPECTED_DOWNSTREAM_MODELS:
        node = model_nodes.get(name)
        deps = set(node.get("depends_on", {}).get("nodes", [])) if isinstance(node, dict) else set()
        source_deps = sorted(dep for dep in deps if dep.startswith("source."))
        ref_deps = sorted(dep for dep in deps if dep.startswith("model."))
        if source_deps or not ref_deps:
            downstream_errors.append(
                {"model": name, "source_dependencies": source_deps, "model_dependencies": ref_deps}
            )
    if staging_errors:
        checks.append(
            failed(
                "manifest_staging_depends_on_sources",
                len(staging_errors),
                "each staging model has one source dependency",
                staging_errors,
            )
        )
    else:
        checks.append(
            passed("manifest_staging_depends_on_sources", sorted(EXPECTED_STAGING_MODELS), "source dependencies")
        )
    if downstream_errors:
        checks.append(
            failed(
                "manifest_downstream_uses_ref_graph",
                len(downstream_errors),
                "downstream models depend on models, not sources",
                downstream_errors,
            )
        )
    else:
        checks.append(
            passed("manifest_downstream_uses_ref_graph", sorted(EXPECTED_DOWNSTREAM_MODELS), "ref dependencies")
        )
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
        db_path = tmp / "source_ref.duckdb"
        row_counts = prepare_duckdb_database(db_path, data_contract, data_dir)

        env = os.environ.copy()
        env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
        env["DBT_DUCKDB_PATH"] = str(db_path)

        base = ["dbt", "", "--project-dir", str(project_copy), "--profiles-dir", str(profiles_dir)]
        commands = []
        for command in ("parse", "compile"):
            command_line = base.copy()
            command_line[1] = command
            commands.append(run_command(command_line, env))
        freshness_output = project_copy / "target" / "sources.json"
        commands.append(
            run_command(
                [
                    "dbt",
                    "source",
                    "freshness",
                    "--project-dir",
                    str(project_copy),
                    "--profiles-dir",
                    str(profiles_dir),
                ],
                env,
            )
        )

        summary["loaded_raw_rows"] = row_counts
        summary["dbt_commands"] = commands
        if all(item["returncode"] == 0 for item in commands):
            checks.append(passed("dbt_parse_compile_freshness_succeed", "ok", "all dbt commands exit 0"))
            checks.extend(inspect_manifest(project_copy / "target" / "manifest.json", data_contract))
            summary["freshness_state_counts"] = source_state_counts(freshness_output)
            freshness_counts = summary["freshness_state_counts"]
            if freshness_counts.get("error") or freshness_counts.get("warn"):
                checks.append(
                    failed(
                        "source_freshness_passes",
                        freshness_counts,
                        "all selected sources pass freshness",
                        [freshness_counts],
                    )
                )
            else:
                checks.append(passed("source_freshness_passes", freshness_counts, "all selected sources pass"))
        else:
            checks.append(
                failed(
                    "dbt_parse_compile_freshness_succeed",
                    commands,
                    "all dbt commands exit 0",
                    commands,
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
        checks.append(
            failed(
                "dbt_parse_compile_freshness_succeed",
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
    lesson_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Audit dbt source()/ref() lineage.")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parent / "source_ref_project",
        help="Path to the dbt project.",
    )
    parser.add_argument(
        "--data-contract",
        type=Path,
        default=lesson_root.parent / "data" / "contract.json",
        help="Path to the phase data contract.",
    )
    parser.add_argument("--data-dir", type=Path, help="Directory containing raw CSV files.")
    parser.add_argument("--output", type=Path, help="Optional path to write audit JSON.")
    parser.add_argument(
        "--run-dbt",
        action="store_true",
        help="Run dbt parse, compile and source freshness in an isolated temporary copy.",
    )
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
