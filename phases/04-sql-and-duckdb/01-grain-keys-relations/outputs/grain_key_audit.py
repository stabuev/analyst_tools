from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import duckdb

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SOURCE_SQL = "read_csv(?, header = true, all_varchar = true)"


class DataContractError(ValueError):
    """Raised when the data or its declared relational contract cannot be audited."""


def quote_identifier(value: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise DataContractError(f"invalid SQL identifier in contract: {value!r}")
    return f'"{value}"'


def load_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path)
    if not contract_path.is_file():
        raise DataContractError(f"contract file does not exist: {contract_path}")
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DataContractError(f"invalid contract JSON: {error.msg}") from error

    tables = contract.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise DataContractError("contract must contain a non-empty 'tables' object")

    for table_name, table in tables.items():
        quote_identifier(table_name)
        if not isinstance(table, dict):
            raise DataContractError(f"table contract must be an object: {table_name}")
        if not isinstance(table.get("file"), str) or not table["file"]:
            raise DataContractError(f"table {table_name} must declare a file")
        columns = table.get("columns")
        if not isinstance(columns, dict) or not columns:
            raise DataContractError(f"table {table_name} must declare columns")
        for column in columns:
            quote_identifier(column)
        keys = table.get("primary_key")
        if not isinstance(keys, list) or not keys:
            raise DataContractError(f"table {table_name} must declare a primary_key")
        for key in keys:
            quote_identifier(key)
            if key not in columns:
                raise DataContractError(
                    f"primary key column {table_name}.{key} is absent from contract columns"
                )
        foreign_keys = table.get("foreign_keys", [])
        if not isinstance(foreign_keys, list):
            raise DataContractError(f"table {table_name} foreign_keys must be a list")
        for foreign_key in foreign_keys:
            _validate_foreign_key(table_name, columns, foreign_key, tables)
    return contract


def _validate_foreign_key(
    table_name: str,
    columns: dict[str, Any],
    foreign_key: Any,
    tables: dict[str, Any],
) -> None:
    if not isinstance(foreign_key, dict):
        raise DataContractError(f"foreign key in {table_name} must be an object")
    child_columns = foreign_key.get("columns")
    if not isinstance(child_columns, list) or not child_columns:
        raise DataContractError(f"foreign key in {table_name} must declare columns")
    for column in child_columns:
        quote_identifier(column)
        if column not in columns:
            raise DataContractError(
                f"foreign key column {table_name}.{column} is absent from contract columns"
            )
    parent_table, parent_columns = parse_reference(
        foreign_key.get("references"),
        len(child_columns),
    )
    if parent_table not in tables:
        raise DataContractError(f"foreign key references unknown table: {parent_table}")
    declared_parent_columns = tables[parent_table].get("columns", {})
    for column in parent_columns:
        if column not in declared_parent_columns:
            raise DataContractError(
                f"foreign key references unknown column: {parent_table}.{column}"
            )


def parse_reference(reference: Any, width: int) -> tuple[str, list[str]]:
    if not isinstance(reference, str) or "." not in reference:
        raise DataContractError(f"invalid foreign key reference: {reference!r}")
    table_name, raw_columns = reference.split(".", 1)
    quote_identifier(table_name)
    parent_columns = [column.strip() for column in raw_columns.split(",") if column.strip()]
    if len(parent_columns) != width:
        raise DataContractError(
            f"foreign key width mismatch: {width} child columns, "
            f"{len(parent_columns)} parent columns"
        )
    for column in parent_columns:
        quote_identifier(column)
    return table_name, parent_columns


def resolve_table_paths(
    data_dir: str | Path,
    contract: dict[str, Any],
) -> dict[str, Path]:
    root = Path(data_dir)
    if not root.is_dir():
        raise DataContractError(f"data directory does not exist: {root}")

    paths: dict[str, Path] = {}
    for table_name, table in contract["tables"].items():
        relative = Path(table["file"])
        if relative.is_absolute() or ".." in relative.parts:
            raise DataContractError(
                f"table {table_name} uses a file outside data directory: {relative}"
            )
        path = root / relative
        if not path.is_file():
            raise DataContractError(f"input file does not exist: {path}")
        paths[table_name] = path
    return paths


def fetch_dicts(
    connection: duckdb.DuckDBPyConnection,
    query: str,
    parameters: list[Any],
) -> list[dict[str, Any]]:
    cursor = connection.execute(query, parameters)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def inspect_columns(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    expected: list[str],
) -> dict[str, Any]:
    rows = connection.execute(
        f"DESCRIBE SELECT * FROM {SOURCE_SQL}",
        [str(path)],
    ).fetchall()
    actual = [row[0] for row in rows]
    missing = [column for column in expected if column not in actual]
    unexpected = [column for column in actual if column not in expected]
    return {
        "expected": expected,
        "actual": actual,
        "missing": missing,
        "unexpected": unexpected,
        "valid": not missing,
    }


def audit_primary_key(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    keys: list[str],
    actual_columns: list[str],
) -> dict[str, Any]:
    missing_keys = [key for key in keys if key not in actual_columns]
    if missing_keys:
        return {
            "columns": keys,
            "checked": False,
            "error": f"missing key columns: {missing_keys}",
            "null_key_rows": None,
            "duplicate_groups": None,
            "duplicate_key_rows": None,
            "sample_duplicates": [],
            "valid": False,
        }

    quoted_keys = [quote_identifier(key) for key in keys]
    key_list = ", ".join(quoted_keys)
    null_predicate = " OR ".join(f"{key} IS NULL" for key in quoted_keys)
    non_null_predicate = " AND ".join(f"{key} IS NOT NULL" for key in quoted_keys)
    null_key_rows = connection.execute(
        f"SELECT count(*) FROM {SOURCE_SQL} WHERE {null_predicate}",
        [str(path)],
    ).fetchone()[0]

    duplicate_cte = f"""
        WITH duplicate_keys AS (
            SELECT {key_list}, count(*) AS row_count
            FROM {SOURCE_SQL}
            WHERE {non_null_predicate}
            GROUP BY {key_list}
            HAVING count(*) > 1
        )
    """
    duplicate_key_rows, duplicate_groups = connection.execute(
        duplicate_cte
        + """
        SELECT coalesce(sum(row_count), 0), count(*)
        FROM duplicate_keys
        """,
        [str(path)],
    ).fetchone()
    sample_duplicates = fetch_dicts(
        connection,
        duplicate_cte
        + f"""
        SELECT {key_list}, row_count
        FROM duplicate_keys
        ORDER BY row_count DESC, {key_list}
        LIMIT 5
        """,
        [str(path)],
    )
    return {
        "columns": keys,
        "checked": True,
        "null_key_rows": null_key_rows,
        "duplicate_groups": duplicate_groups,
        "duplicate_key_rows": duplicate_key_rows,
        "sample_duplicates": sample_duplicates,
        "valid": null_key_rows == 0 and duplicate_groups == 0,
    }


def audit_table(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    table: dict[str, Any],
    path: Path,
) -> dict[str, Any]:
    expected_columns = list(table["columns"])
    columns = inspect_columns(connection, path, expected_columns)
    row_count = connection.execute(
        f"SELECT count(*) FROM {SOURCE_SQL}",
        [str(path)],
    ).fetchone()[0]
    primary_key = audit_primary_key(
        connection,
        path,
        table["primary_key"],
        columns["actual"],
    )
    return {
        "file": table["file"],
        "grain": table.get("grain"),
        "rows": row_count,
        "columns": columns,
        "primary_key": primary_key,
        "valid": columns["valid"] and primary_key["valid"],
    }


def audit_relationship(
    connection: duckdb.DuckDBPyConnection,
    child_table: str,
    child_columns: list[str],
    parent_table: str,
    parent_columns: list[str],
    paths: dict[str, Path],
    table_reports: dict[str, Any],
) -> dict[str, Any]:
    missing_child = [
        column
        for column in child_columns
        if column not in table_reports[child_table]["columns"]["actual"]
    ]
    missing_parent = [
        column
        for column in parent_columns
        if column not in table_reports[parent_table]["columns"]["actual"]
    ]
    base_report = {
        "child_table": child_table,
        "child_columns": child_columns,
        "parent_table": parent_table,
        "parent_columns": parent_columns,
    }
    if missing_child or missing_parent:
        return {
            **base_report,
            "checked": False,
            "error": (
                f"missing relationship columns: child={missing_child}, parent={missing_parent}"
            ),
            "orphan_keys": None,
            "orphan_rows": None,
            "sample_orphans": [],
            "valid": False,
        }

    child_keys = [quote_identifier(column) for column in child_columns]
    parent_keys = [quote_identifier(column) for column in parent_columns]
    child_key_list = ", ".join(f"child.{column}" for column in child_keys)
    non_null_predicate = " AND ".join(f"child.{column} IS NOT NULL" for column in child_keys)
    equality = " AND ".join(
        f"parent.{parent} = child.{child}"
        for child, parent in zip(child_keys, parent_keys, strict=True)
    )
    orphan_cte = f"""
        WITH
        child AS (SELECT * FROM {SOURCE_SQL}),
        parent AS (SELECT * FROM {SOURCE_SQL}),
        orphan_groups AS (
            SELECT {child_key_list}, count(*) AS row_count
            FROM child
            WHERE {non_null_predicate}
              AND NOT EXISTS (
                  SELECT 1
                  FROM parent
                  WHERE {equality}
              )
            GROUP BY {child_key_list}
        )
    """
    parameters = [str(paths[child_table]), str(paths[parent_table])]
    orphan_rows, orphan_keys = connection.execute(
        orphan_cte
        + """
        SELECT coalesce(sum(row_count), 0), count(*)
        FROM orphan_groups
        """,
        parameters,
    ).fetchone()
    sample_orphans = fetch_dicts(
        connection,
        orphan_cte
        + f"""
        SELECT {", ".join(child_keys)}, row_count
        FROM orphan_groups
        ORDER BY row_count DESC, {", ".join(child_keys)}
        LIMIT 5
        """,
        parameters,
    )
    return {
        **base_report,
        "checked": True,
        "orphan_keys": orphan_keys,
        "orphan_rows": orphan_rows,
        "sample_orphans": sample_orphans,
        "valid": orphan_keys == 0,
    }


def audit_dataset(
    data_dir: str | Path,
    contract_path: str | Path,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    paths = resolve_table_paths(data_dir, contract)
    connection = duckdb.connect(database=":memory:")
    try:
        table_reports = {
            table_name: audit_table(connection, table_name, table, paths[table_name])
            for table_name, table in contract["tables"].items()
        }
        relationships = []
        for child_table, table in contract["tables"].items():
            for foreign_key in table.get("foreign_keys", []):
                child_columns = foreign_key["columns"]
                parent_table, parent_columns = parse_reference(
                    foreign_key["references"],
                    len(child_columns),
                )
                relationships.append(
                    audit_relationship(
                        connection,
                        child_table,
                        child_columns,
                        parent_table,
                        parent_columns,
                        paths,
                        table_reports,
                    )
                )
    finally:
        connection.close()

    failed_checks = sum(not table["columns"]["valid"] for table in table_reports.values())
    failed_checks += sum(not table["primary_key"]["valid"] for table in table_reports.values())
    failed_checks += sum(not relationship["valid"] for relationship in relationships)
    return {
        "engine": {"name": "DuckDB", "version": duckdb.__version__},
        "data_dir": str(Path(data_dir)),
        "contract": str(Path(contract_path)),
        "tables": table_reports,
        "relationships": relationships,
        "summary": {
            "table_count": len(table_reports),
            "relationship_count": len(relationships),
            "failed_checks": failed_checks,
            "valid": failed_checks == 0,
        },
    }


def render_report(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit declared grain, primary keys, and foreign-key relationships"
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument(
        "--contract",
        type=Path,
        help="Defaults to contract.json next to the data profile directory",
    )
    parser.add_argument(
        "--allow-failures",
        action="store_true",
        help="Return exit code 0 after printing an invalid educational dataset",
    )
    args = parser.parse_args()
    contract_path = args.contract or args.data_dir.parent / "contract.json"
    try:
        report = audit_dataset(args.data_dir, contract_path)
    except (DataContractError, OSError, duckdb.Error) as error:
        parser.error(str(error))
    print(render_report(report), end="")
    if not report["summary"]["valid"] and not args.allow_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
