from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import sqlalchemy
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

CONTRACT_VERSION = "2.0.0"
DEFAULT_CONTRACT = Path(__file__).resolve().parents[2] / "data" / "db_contract.json"
DEFAULT_SQL = Path(__file__).with_name("order_slice.sql")
CONTRACT_KEYS = {"version", "query", "source", "result"}
RESULT_KEYS = {
    "columns",
    "grain",
    "fields",
    "domains",
    "relationship_fields",
    "allow_empty",
}


class DatabaseReadError(RuntimeError):
    """Raised when configuration or database access prevents a controlled audit."""


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DatabaseReadError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _require_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DatabaseReadError(f"{label} must be an object")
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing:
        raise DatabaseReadError(f"{label} misses keys: {sorted(missing)}")
    if unknown:
        raise DatabaseReadError(f"{label} has unknown keys: {sorted(unknown)}")
    return value


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        suffix = "a list" if allow_empty else "a non-empty list"
        raise DatabaseReadError(f"{label} must be {suffix}")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise DatabaseReadError(f"{label} must contain non-blank strings")
    if len(value) != len(set(value)):
        raise DatabaseReadError(f"{label} must not contain duplicates")
    return value


def _parse_contract(raw: bytes) -> dict[str, Any]:
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise DatabaseReadError(f"contract is not valid UTF-8 at byte {error.start}") from error
    try:
        value = json.loads(decoded, object_pairs_hook=_object_without_duplicates)
    except json.JSONDecodeError as error:
        raise DatabaseReadError(f"invalid contract JSON: {error.msg}") from error
    contract = _require_keys(value, CONTRACT_KEYS, "contract")
    if contract["version"] != CONTRACT_VERSION:
        raise DatabaseReadError(
            f"unsupported contract version: {contract['version']!r}; expected {CONTRACT_VERSION!r}"
        )

    query = _require_keys(contract["query"], {"bind_names"}, "query")
    _string_list(query["bind_names"], "query.bind_names")

    source = _require_keys(contract["source"], {"tables"}, "source")
    tables = source["tables"]
    if not isinstance(tables, dict) or not tables:
        raise DatabaseReadError("source.tables must be a non-empty object")
    for table_name, raw_table in tables.items():
        if not isinstance(table_name, str) or not table_name.strip():
            raise DatabaseReadError("source table names must be non-blank strings")
        table = _require_keys(
            raw_table,
            {"required_columns", "primary_key", "non_nullable"},
            f"source table {table_name!r}",
        )
        columns = _string_list(
            table["required_columns"], f"source table {table_name!r}.required_columns"
        )
        primary_key = _string_list(table["primary_key"], f"source table {table_name!r}.primary_key")
        non_nullable = _string_list(
            table["non_nullable"],
            f"source table {table_name!r}.non_nullable",
            allow_empty=True,
        )
        for field_name, field_values in {
            "primary_key": primary_key,
            "non_nullable": non_nullable,
        }.items():
            outside = sorted(set(field_values) - set(columns))
            if outside:
                raise DatabaseReadError(
                    f"source table {table_name!r}.{field_name} contains unknown columns: {outside}"
                )

    result = _require_keys(contract["result"], RESULT_KEYS, "result")
    columns = _string_list(result["columns"], "result.columns")
    grain = _string_list(result["grain"], "result.grain")
    outside_grain = sorted(set(grain) - set(columns))
    if outside_grain:
        raise DatabaseReadError(f"result.grain contains unknown columns: {outside_grain}")
    fields = result["fields"]
    if not isinstance(fields, dict) or list(fields) != columns:
        raise DatabaseReadError("result.fields must describe result.columns in the same order")
    for name, raw_field in fields.items():
        field = _require_keys(raw_field, {"type", "nullable"}, f"result field {name!r}")
        if field["type"] not in {"string", "number"}:
            raise DatabaseReadError(f"result field {name!r}.type must be 'string' or 'number'")
        if not isinstance(field["nullable"], bool):
            raise DatabaseReadError(f"result field {name!r}.nullable must be boolean")

    domains = result["domains"]
    if not isinstance(domains, dict):
        raise DatabaseReadError("result.domains must be an object")
    unknown_domains = sorted(set(domains) - set(columns))
    if unknown_domains:
        raise DatabaseReadError(f"result.domains contains unknown columns: {unknown_domains}")
    for name, allowed in domains.items():
        _string_list(allowed, f"result.domains.{name}")

    relationship_fields = _string_list(
        result["relationship_fields"], "result.relationship_fields", allow_empty=True
    )
    outside_relationships = sorted(set(relationship_fields) - set(columns))
    if outside_relationships:
        raise DatabaseReadError(
            f"result.relationship_fields contains unknown columns: {outside_relationships}"
        )
    if not isinstance(result["allow_empty"], bool):
        raise DatabaseReadError("result.allow_empty must be boolean")
    return contract


def load_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path)
    try:
        raw = contract_path.read_bytes()
    except OSError as error:
        raise DatabaseReadError(f"cannot read contract {contract_path.name!r}: {error}") from error
    return _parse_contract(raw)


def load_sql(path: str | Path) -> tuple[str, bytes]:
    sql_path = Path(path)
    try:
        raw = sql_path.read_bytes()
    except OSError as error:
        raise DatabaseReadError(f"cannot read SQL asset {sql_path.name!r}: {error}") from error
    try:
        statement = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise DatabaseReadError(f"SQL asset is not valid UTF-8 at byte {error.start}") from error
    if not statement.strip():
        raise DatabaseReadError("SQL asset must not be blank")
    return statement, raw


def build_sqlite_read_only_engine(database: str | Path) -> Engine:
    """Create an owned Engine for an existing SQLite file opened in read-only mode."""

    path = Path(database).resolve()
    if not path.is_file():
        raise DatabaseReadError(f"database file does not exist: {path.name}")
    encoded_path = quote(path.as_posix(), safe="/")
    return create_engine(f"sqlite+pysqlite:///file:{encoded_path}?mode=ro&uri=true")


def _file_metadata(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "file_name": path.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _inspect_schema(
    connection: Any, contract: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, bool], list[dict[str, Any]]]:
    inspector = inspect(connection)
    report: dict[str, Any] = {}
    table_presence = True
    columns_present = True
    primary_keys_match = True
    nullability_matches = True
    errors: list[dict[str, Any]] = []
    for table_name, expected in contract["source"]["tables"].items():
        exists = inspector.has_table(table_name)
        if not exists:
            table_presence = False
            columns_present = False
            primary_keys_match = False
            nullability_matches = False
            report[table_name] = {"exists": False, "columns": [], "primary_key": []}
            errors.append(
                {"kind": "schema", "table": table_name, "error": "required table is missing"}
            )
            continue
        reflected_columns = inspector.get_columns(table_name)
        reflected_by_name = {column["name"]: column for column in reflected_columns}
        actual_primary_key = (
            inspector.get_pk_constraint(table_name).get("constrained_columns", []) or []
        )
        report[table_name] = {
            "exists": True,
            "columns": [
                {
                    "name": column["name"],
                    "type": str(column["type"]),
                    "nullable": bool(column["nullable"]),
                }
                for column in reflected_columns
            ],
            "primary_key": list(actual_primary_key),
        }
        missing_columns = sorted(set(expected["required_columns"]) - set(reflected_by_name))
        if missing_columns:
            columns_present = False
            errors.append(
                {
                    "kind": "schema",
                    "table": table_name,
                    "columns": missing_columns,
                    "error": "required columns are missing",
                }
            )
        if list(actual_primary_key) != expected["primary_key"]:
            primary_keys_match = False
            errors.append(
                {
                    "kind": "schema",
                    "table": table_name,
                    "expected": expected["primary_key"],
                    "actual": list(actual_primary_key),
                    "error": "primary key differs from contract",
                }
            )
        wrong_nullability = [
            name
            for name in expected["non_nullable"]
            if name in reflected_by_name and bool(reflected_by_name[name]["nullable"])
        ]
        if wrong_nullability:
            nullability_matches = False
            errors.append(
                {
                    "kind": "schema",
                    "table": table_name,
                    "columns": wrong_nullability,
                    "error": "columns expected non-nullable are nullable",
                }
            )
    checks = {
        "source_tables_present": table_presence,
        "source_columns_present": columns_present,
        "source_primary_keys_match": primary_keys_match,
        "source_nullability_matches": nullability_matches,
    }
    return report, checks, errors


def _value_matches(value: Any, field: dict[str, Any]) -> bool:
    if value is None:
        return field["nullable"]
    if field["type"] == "string":
        return isinstance(value, str) and bool(value.strip())
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def read_orders(
    engine: Engine,
    contract_path: str | Path,
    *,
    sql_path: str | Path = DEFAULT_SQL,
    min_amount: float = 0.0,
    status: str | None = None,
    max_rows: int = 100,
    database_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read one checked slice through a caller-owned Engine without disposing it."""

    if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
        raise DatabaseReadError("max_rows must be a positive integer")
    if isinstance(min_amount, bool) or not isinstance(min_amount, (int, float)):
        raise DatabaseReadError("min_amount must be a finite number")
    min_amount = float(min_amount)
    if not math.isfinite(min_amount):
        raise DatabaseReadError("min_amount must be a finite number")
    if status is not None and (not isinstance(status, str) or not status.strip()):
        raise DatabaseReadError("status must be a non-blank string or null")

    contract_file = Path(contract_path)
    sql_file = Path(sql_path)
    try:
        contract_raw = contract_file.read_bytes()
    except OSError as error:
        raise DatabaseReadError(f"cannot read contract {contract_file.name!r}: {error}") from error
    contract = _parse_contract(contract_raw)
    sql, sql_raw = load_sql(sql_file)
    statement = text(sql)
    compiled = statement.compile(dialect=engine.dialect)
    actual_bind_names = sorted(compiled.params)
    expected_bind_names = sorted(contract["query"]["bind_names"])
    parameters = {
        "min_amount": min_amount,
        "status": status,
        "fetch_limit": max_rows + 1,
    }
    bind_names_match = actual_bind_names == expected_bind_names == sorted(parameters)
    errors: list[dict[str, Any]] = []
    if not bind_names_match:
        errors.append(
            {
                "kind": "query",
                "expected": expected_bind_names,
                "actual": actual_bind_names,
                "error": "SQL bind names differ from contract",
            }
        )

    try:
        with engine.connect() as connection:
            schema, schema_checks, schema_errors = _inspect_schema(connection, contract)
            errors.extend(schema_errors)
            schema_valid = all(schema_checks.values())
            if schema_valid and bind_names_match:
                cursor = connection.execute(statement, parameters)
                actual_columns = list(cursor.keys())
                fetched = [dict(row) for row in cursor.mappings().fetchmany(max_rows + 1)]
            else:
                actual_columns = []
                fetched = []
    except SQLAlchemyError as error:
        raise DatabaseReadError(f"database read failed: {error}") from error

    overflow = len(fetched) > max_rows
    rows = fetched[:max_rows]
    expected_result = contract["result"]
    columns_match = actual_columns == expected_result["columns"]
    if actual_columns and not columns_match:
        errors.append(
            {
                "kind": "result",
                "expected": expected_result["columns"],
                "actual": actual_columns,
                "error": "result columns or order differ from contract",
            }
        )

    grain = expected_result["grain"]
    grain_values = [tuple(row.get(column) for column in grain) for row in rows]
    grain_complete = all(
        all(value is not None and value != "" for value in key) for key in grain_values
    )
    grain_unique = len(grain_values) == len(set(grain_values))
    fields_valid = all(
        _value_matches(row.get(name), expected_result["fields"][name])
        for row in rows
        for name in expected_result["columns"]
    )
    domains_valid = all(
        row.get(name) in allowed
        for row in rows
        for name, allowed in expected_result["domains"].items()
    )
    relationships_complete = all(
        row.get(name) is not None and row.get(name) != ""
        for row in rows
        for name in expected_result["relationship_fields"]
    )
    empty_allowed = bool(rows) or expected_result["allow_empty"]
    result_checks = {
        "query_bind_names_match": bind_names_match,
        "result_columns_match": columns_match,
        "result_complete_within_limit": not overflow,
        "result_empty_allowed": empty_allowed,
        "result_fields_valid": fields_valid,
        "result_grain_complete": grain_complete,
        "result_grain_unique": grain_unique,
        "result_domains_valid": domains_valid,
        "relationships_complete": relationships_complete,
    }
    if overflow:
        errors.append(
            {
                "kind": "completeness",
                "max_rows": max_rows,
                "rows_fetched": len(fetched),
                "error": "result exceeds max_rows; completeness is not proven",
            }
        )
    if not grain_unique:
        errors.append({"kind": "grain", "columns": grain, "error": "result grain is not unique"})
    if not relationships_complete:
        errors.append(
            {
                "kind": "relationship",
                "fields": expected_result["relationship_fields"],
                "error": "required relationship fields are missing",
            }
        )
    checks = {**schema_checks, **result_checks}
    failed_checks = [name for name, passed in checks.items() if not passed]
    source: dict[str, Any] = {
        "dialect": engine.dialect.name,
        "driver": engine.driver,
        "sqlalchemy_version": sqlalchemy.__version__,
    }
    if database_source is not None:
        source["database"] = database_source
    return {
        "source": source,
        "contract": contract,
        "contract_source": {
            "file_name": contract_file.name,
            "sha256": hashlib.sha256(contract_raw).hexdigest(),
        },
        "query": {
            "file_name": sql_file.name,
            "sha256": hashlib.sha256(sql_raw).hexdigest(),
            "statement": sql,
            "compiled": str(compiled),
            "bind_names": actual_bind_names,
        },
        "parameters": {"min_amount": min_amount, "status": status, "max_rows": max_rows},
        "schema": schema,
        "result": {
            "grain": grain,
            "columns": actual_columns,
            "rows": rows,
        },
        "checks": checks,
        "errors": errors,
        "summary": {
            "valid": not failed_checks,
            "published": False,
            "row_count": len(rows),
            "rows_fetched_for_limit_check": len(fetched),
            "failed_checks": failed_checks,
        },
    }


def read_sqlite_orders(
    database: str | Path,
    contract_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Own one SQLite Engine for a CLI-style run and dispose it afterwards."""

    path = Path(database).resolve()
    engine = build_sqlite_read_only_engine(path)
    try:
        return read_orders(
            engine,
            contract_path,
            database_source=_file_metadata(path),
            **kwargs,
        )
    finally:
        engine.dispose()


def publish_snapshot(result: dict[str, Any], output: str | Path) -> Path:
    if not result.get("summary", {}).get("valid"):
        raise DatabaseReadError("an invalid database result cannot be published")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    published = json.loads(json.dumps(result, ensure_ascii=False))
    published["summary"]["published"] = True
    payload = json.dumps(published, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".part", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read one verified SQLite order slice")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--sql", type=Path, default=DEFAULT_SQL)
    parser.add_argument("--min-amount", type=float, default=0.0)
    parser.add_argument("--status")
    parser.add_argument("--max-rows", type=int, default=100)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        result = read_sqlite_orders(
            arguments.database,
            arguments.contract,
            sql_path=arguments.sql,
            min_amount=arguments.min_amount,
            status=arguments.status,
            max_rows=arguments.max_rows,
        )
        if result["summary"]["valid"] and arguments.output:
            publish_snapshot(result, arguments.output)
            result["summary"]["published"] = True
    except DatabaseReadError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False, indent=2))
        return 2
    except OSError as error:
        print(json.dumps({"error": f"cannot publish snapshot: {error}"}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["summary"]["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
