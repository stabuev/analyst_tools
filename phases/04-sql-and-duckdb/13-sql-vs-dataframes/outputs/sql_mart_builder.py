from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parent
ORDER_MART_SQL = ROOT / "order_mart.sql"
USER_SUMMARY_SQL = ROOT / "user_summary.sql"
PACKAGE_ARTIFACTS = (
    "boundary_decision.json",
    "order_mart.csv",
    "sql/order_mart.sql",
    "sql/user_summary.sql",
    "user_summary.csv",
)


class ContractError(ValueError):
    """The source data cannot be published under the declared mart contract."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _scalar(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    params: Sequence[Any] = (),
) -> Any:
    row = connection.execute(sql, list(params)).fetchone()
    if row is None:
        raise RuntimeError("scalar query returned no rows")
    return row[0]


def _require_sources(sources: dict[str, Path]) -> dict[str, Path]:
    resolved: dict[str, Path] = {}
    for role, path in sources.items():
        candidate = Path(path)
        if not candidate.is_file():
            raise FileNotFoundError(f"{role} source is not a file: {candidate}")
        resolved[role] = candidate.resolve()
    return resolved


def _source_checks(
    connection: duckdb.DuckDBPyConnection,
    sources: dict[str, Path],
) -> dict[str, int]:
    users = str(sources["users"])
    orders = str(sources["orders"])
    items = str(sources["order_items"])
    read_csv = "read_csv(?, header = true, all_varchar = true, nullstr = '')"

    return {
        "users_rows": _scalar(connection, f"SELECT count(*) FROM {read_csv}", [users]),
        "orders_rows": _scalar(connection, f"SELECT count(*) FROM {read_csv}", [orders]),
        "order_items_rows": _scalar(
            connection,
            f"SELECT count(*) FROM {read_csv}",
            [items],
        ),
        "duplicate_user_ids": _scalar(
            connection,
            f"""
            SELECT count(*) - count(DISTINCT user_id)
            FROM {read_csv}
            WHERE nullif(trim(user_id), '') IS NOT NULL
            """,
            [users],
        ),
        "duplicate_order_ids": _scalar(
            connection,
            f"""
            SELECT count(*) - count(DISTINCT order_id)
            FROM {read_csv}
            WHERE nullif(trim(order_id), '') IS NOT NULL
            """,
            [orders],
        ),
        "duplicate_item_keys": _scalar(
            connection,
            f"""
            SELECT count(*) - count(DISTINCT (order_id, product_id))
            FROM {read_csv}
            WHERE nullif(trim(order_id), '') IS NOT NULL
              AND nullif(trim(product_id), '') IS NOT NULL
            """,
            [items],
        ),
        "missing_user_ids": _scalar(
            connection,
            f"""
            SELECT count(*) FROM {read_csv}
            WHERE nullif(trim(user_id), '') IS NULL
            """,
            [users],
        ),
        "missing_order_ids": _scalar(
            connection,
            f"""
            SELECT count(*) FROM {read_csv}
            WHERE nullif(trim(order_id), '') IS NULL
            """,
            [orders],
        ),
        "missing_order_user_ids": _scalar(
            connection,
            f"""
            SELECT count(*) FROM {read_csv}
            WHERE nullif(trim(user_id), '') IS NULL
            """,
            [orders],
        ),
        "missing_item_key_parts": _scalar(
            connection,
            f"""
            SELECT count(*) FROM {read_csv}
            WHERE nullif(trim(order_id), '') IS NULL
               OR nullif(trim(product_id), '') IS NULL
            """,
            [items],
        ),
        "orphan_item_order_ids": _scalar(
            connection,
            f"""
            SELECT count(*)
            FROM (
                SELECT DISTINCT items.order_id
                FROM {read_csv} AS items
                ANTI JOIN {read_csv} AS orders USING (order_id)
            )
            """,
            [items, orders],
        ),
    }


def _mart_checks(
    connection: duckdb.DuckDBPyConnection,
    source_checks: dict[str, int],
) -> dict[str, Any]:
    order_rows = _scalar(connection, "SELECT count(*) FROM order_mart")
    distinct_orders = _scalar(
        connection,
        "SELECT count(DISTINCT order_id) FROM order_mart",
    )
    summary_rows = _scalar(connection, "SELECT count(*) FROM user_summary")
    expected_summary_rows = _scalar(
        connection,
        """
        SELECT count(*)
        FROM (SELECT user_id, currency FROM order_mart GROUP BY user_id, currency)
        """,
    )
    order_paid_revenue = {
        currency: format(value, ".2f")
        for currency, value in connection.execute(
            """
            SELECT currency, coalesce(sum(paid_amount), 0)::DECIMAL(18, 2)
            FROM order_mart
            GROUP BY currency
            ORDER BY currency
            """
        ).fetchall()
    }
    summary_paid_revenue = {
        currency: format(value, ".2f")
        for currency, value in connection.execute(
            """
            SELECT currency, coalesce(sum(paid_revenue), 0)::DECIMAL(18, 2)
            FROM user_summary
            GROUP BY currency
            ORDER BY currency
            """
        ).fetchall()
    }

    return {
        "order_rows": order_rows,
        "order_rows_match_source": order_rows == source_checks["orders_rows"],
        "order_id_unique": distinct_orders == order_rows,
        "unknown_user_orders": _scalar(
            connection,
            "SELECT count(*) FROM order_mart WHERE NOT user_found",
        ),
        "missing_business_dates": _scalar(
            connection,
            "SELECT count(*) FROM order_mart WHERE business_date IS NULL",
        ),
        "missing_currency_codes": _scalar(
            connection,
            """
            SELECT count(*) FROM order_mart
            WHERE nullif(trim(currency), '') IS NULL
            """,
        ),
        "paid_orders_missing_amount": _scalar(
            connection,
            """
            SELECT count(*) FROM order_mart
            WHERE is_paid AND amount IS NULL
            """,
        ),
        "amount_item_mismatches": _scalar(
            connection,
            "SELECT count(*) FROM order_mart WHERE amount_matches_items = false",
        ),
        "amount_item_unchecked": _scalar(
            connection,
            "SELECT count(*) FROM order_mart WHERE amount_matches_items IS NULL",
        ),
        "user_summary_rows": summary_rows,
        "expected_user_summary_rows": expected_summary_rows,
        "user_summary_grain_valid": summary_rows == expected_summary_rows,
        "order_paid_revenue_by_currency": order_paid_revenue,
        "summary_paid_revenue_by_currency": summary_paid_revenue,
        "paid_revenue_reconciled_by_currency": (order_paid_revenue == summary_paid_revenue),
    }


def _quality_report(
    source_checks: dict[str, int],
    mart_checks: dict[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    for check in (
        "duplicate_user_ids",
        "duplicate_order_ids",
        "duplicate_item_keys",
        "missing_user_ids",
        "missing_order_ids",
        "missing_order_user_ids",
        "missing_item_key_parts",
        "orphan_item_order_ids",
    ):
        if source_checks[check]:
            blockers.append(f"{check}={source_checks[check]}")
    for check in (
        "order_rows_match_source",
        "order_id_unique",
        "user_summary_grain_valid",
        "paid_revenue_reconciled_by_currency",
    ):
        if not mart_checks[check]:
            blockers.append(f"{check}=false")
    if mart_checks["amount_item_mismatches"]:
        blockers.append(f"amount_item_mismatches={mart_checks['amount_item_mismatches']}")
    for check in ("missing_currency_codes", "paid_orders_missing_amount"):
        if mart_checks[check]:
            blockers.append(f"{check}={mart_checks[check]}")

    warnings = [
        f"{check}={mart_checks[check]}"
        for check in (
            "unknown_user_orders",
            "missing_business_dates",
            "amount_item_unchecked",
        )
        if mart_checks[check]
    ]
    return {
        "source": source_checks,
        "marts": mart_checks,
        "blockers": blockers,
        "warnings": warnings,
        "valid": not blockers,
    }


def _boundary_decision(
    sources: dict[str, Path],
    quality: dict[str, Any],
) -> dict[str, Any]:
    source_rows = {
        role: quality["source"][f"{role}_rows"] for role in ("users", "orders", "order_items")
    }
    source_bytes = {role: path.stat().st_size for role, path in sources.items()}
    summary_rows = quality["marts"]["user_summary_rows"]
    input_rows = sum(source_rows.values())
    return {
        "decision": {
            "duckdb_sql": (
                "typing, normalization, pre-aggregation, joins, marts and direct CSV export"
            ),
            "python": ("path validation, orchestration, quality gate, provenance and verification"),
            "pandas": (
                "not used during the build; optionally load only a checked result at the "
                "required grain for local exploration"
            ),
        },
        "evidence": {
            "source_rows": source_rows,
            "source_bytes": source_bytes,
            "relational_input_rows": input_rows,
            "order_mart_rows": quality["marts"]["order_rows"],
            "user_summary_rows": summary_rows,
            "handoff_grain": ["user_id", "currency"],
            "row_reduction_to_handoff": f"{input_rows}:{summary_rows}",
            "dataframes_materialized_during_build": 0,
        },
        "reasoning": [
            (
                "The build combines three relations and changes grain twice, so the "
                "relational work stays in one SQL engine."
            ),
            (
                "DuckDB writes ordered CSV files directly; Python never materializes the "
                "full marts as lists or DataFrames."
            ),
            (
                "Python owns file paths, the publish decision, checksums and the receiver's "
                "verification command rather than business aggregation."
            ),
        ],
        "limitations": [
            (
                "Row and byte counts describe this run; they do not prove a universal "
                "runtime or memory advantage."
            ),
            (
                "Repeat EXPLAIN ANALYZE and representative benchmarks when data size, file "
                "format or workload changes."
            ),
            ("SHA-256 detects changed bytes but does not authenticate the publisher."),
        ],
    }


def _artifact_record(root: Path, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    return {
        "path": relative_path,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def build_package(
    users_path: Path,
    orders_path: Path,
    items_path: Path,
    output_dir: Path,
    business_timezone: str = "Europe/Moscow",
) -> dict[str, Any]:
    """Build checked marts and publish a portable package without DataFrame materialization."""
    sources = _require_sources(
        {
            "users": users_path,
            "orders": orders_path,
            "order_items": items_path,
        }
    )
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")

    order_sql = ORDER_MART_SQL.read_text(encoding="utf-8").strip().removesuffix(";")
    summary_sql = USER_SUMMARY_SQL.read_text(encoding="utf-8").strip().removesuffix(";")
    connection = duckdb.connect()
    try:
        source_checks = _source_checks(connection, sources)
        connection.execute(
            f"CREATE TEMP TABLE order_mart AS {order_sql}",
            [
                str(sources["users"]),
                business_timezone,
                str(sources["orders"]),
                str(sources["order_items"]),
            ],
        )
        connection.execute(f"CREATE TEMP TABLE user_summary AS {summary_sql}")
        quality = _quality_report(
            source_checks,
            _mart_checks(connection, source_checks),
        )
        if not quality["valid"]:
            raise ContractError("publish blocked: " + ", ".join(quality["blockers"]))

        output_dir.mkdir(parents=True)
        sql_dir = output_dir / "sql"
        sql_dir.mkdir()
        connection.execute(
            """
            COPY (SELECT * FROM order_mart ORDER BY order_id)
            TO ? (FORMAT CSV, HEADER)
            """,
            [str(output_dir / "order_mart.csv")],
        )
        connection.execute(
            """
            COPY (SELECT * FROM user_summary ORDER BY user_id, currency)
            TO ? (FORMAT CSV, HEADER)
            """,
            [str(output_dir / "user_summary.csv")],
        )
    finally:
        connection.close()

    shutil.copyfile(ORDER_MART_SQL, output_dir / "sql" / ORDER_MART_SQL.name)
    shutil.copyfile(USER_SUMMARY_SQL, output_dir / "sql" / USER_SUMMARY_SQL.name)
    boundary = _boundary_decision(sources, quality)
    _write_json(output_dir / "boundary_decision.json", boundary)

    manifest = {
        "name": "sql-marts",
        "manifest_version": "1.0.0",
        "duckdb_version": duckdb.__version__,
        "business_timezone": business_timezone,
        "quality": quality,
        "boundary_decision": "boundary_decision.json",
        "sources": {
            role: {
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for role, path in sources.items()
        },
        "artifacts": [
            _artifact_record(output_dir, relative_path) for relative_path in PACKAGE_ARTIFACTS
        ],
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def _safe_package_path(package_dir: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative_path:
        raise ValueError(f"unsafe artifact path: {relative_path}")
    return package_dir.joinpath(*pure.parts)


def verify_package(package_dir: Path) -> dict[str, Any]:
    """Verify package structure and byte identity from the receiver's side."""
    package_dir = Path(package_dir)
    manifest_path = package_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {"valid": False, "errors": [f"cannot read manifest: {error}"]}

    errors: list[str] = []
    if manifest.get("manifest_version") != "1.0.0":
        errors.append("unsupported manifest_version")
    quality = manifest.get("quality")
    if not isinstance(quality, dict) or quality.get("valid") is not True:
        errors.append("manifest quality gate is not valid")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return {"valid": False, "errors": errors + ["artifacts must be a list"]}

    declared_paths: list[str] = []
    for record in artifacts:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            errors.append("invalid artifact record")
            continue
        relative_path = record["path"]
        declared_paths.append(relative_path)
        try:
            path = _safe_package_path(package_dir, relative_path)
        except ValueError as error:
            errors.append(str(error))
            continue
        if not path.is_file():
            errors.append(f"missing artifact: {relative_path}")
            continue
        if path.stat().st_size != record.get("bytes"):
            errors.append(f"byte size mismatch: {relative_path}")
        if sha256(path) != record.get("sha256"):
            errors.append(f"checksum mismatch: {relative_path}")

    if tuple(sorted(declared_paths)) != PACKAGE_ARTIFACTS:
        errors.append("artifact inventory does not match the package contract")
    actual_paths = tuple(
        sorted(
            path.relative_to(package_dir).as_posix()
            for path in package_dir.rglob("*")
            if path.is_file() and path != manifest_path
        )
    )
    if actual_paths != PACKAGE_ARTIFACTS:
        errors.append("package files do not match the declared inventory")
    return {
        "valid": not errors,
        "errors": errors,
        "verified_artifacts": len(declared_paths) if not errors else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or verify checked SQL marts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="build a new package")
    build.add_argument("--users", type=Path, required=True)
    build.add_argument("--orders", type=Path, required=True)
    build.add_argument("--items", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--business-timezone", default="Europe/Moscow")

    verify = subparsers.add_parser("verify", help="verify an existing package")
    verify.add_argument("--package-dir", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build_package(
                args.users,
                args.orders,
                args.items,
                args.output_dir,
                args.business_timezone,
            )
        else:
            result = verify_package(args.package_dir)
            if not result["valid"]:
                raise ContractError("; ".join(result["errors"]))
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
