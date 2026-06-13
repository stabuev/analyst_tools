from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parent
ORDER_MART_SQL = ROOT / "order_mart.sql"
USER_SUMMARY_SQL = ROOT / "user_summary.sql"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def query_records(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    params: Sequence[Any] = (),
) -> tuple[list[str], list[dict[str, Any]]]:
    relation = connection.execute(sql, list(params))
    columns = [column[0] for column in relation.description]
    records = [
        {column: _plain(value) for column, value in zip(columns, row, strict=True)}
        for row in relation.fetchall()
    ]
    return columns, records


def build_marts(
    users_path: Path,
    orders_path: Path,
    items_path: Path,
    business_timezone: str = "Europe/Moscow",
) -> dict[str, Any]:
    order_sql = ORDER_MART_SQL.read_text(encoding="utf-8").strip().removesuffix(";")
    summary_sql = USER_SUMMARY_SQL.read_text(encoding="utf-8")
    connection = duckdb.connect()
    try:
        order_columns, order_mart = query_records(
            connection,
            order_sql,
            [str(users_path), business_timezone, str(orders_path), str(items_path)],
        )
        wrapped_summary = f"WITH order_mart AS ({order_sql})\n{summary_sql}"
        summary_columns, user_summary = query_records(
            connection,
            wrapped_summary,
            [str(users_path), business_timezone, str(orders_path), str(items_path)],
        )
    finally:
        connection.close()

    checks = {
        "order_rows": len(order_mart),
        "order_id_unique": len({row["order_id"] for row in order_mart}) == len(order_mart),
        "unknown_user_orders": sum(not row["user_found"] for row in order_mart),
        "amount_item_mismatches": sum(row["amount_matches_items"] is False for row in order_mart),
        "amount_item_unchecked": sum(row["amount_matches_items"] is None for row in order_mart),
        "paid_revenue": round(sum(row["paid_amount"] or 0 for row in order_mart), 2),
        "user_summary_rows": len(user_summary),
    }
    checks["valid"] = (
        checks["order_rows"] == 12
        and checks["order_id_unique"]
        and checks["amount_item_mismatches"] == 0
        and checks["paid_revenue"] == 5005.0
    )
    return {
        "business_timezone": business_timezone,
        "order_mart": {
            "grain": ["order_id"],
            "columns": order_columns,
            "records": order_mart,
        },
        "user_summary": {
            "grain": ["user_id"],
            "columns": summary_columns,
            "records": user_summary,
        },
        "checks": checks,
        "boundary": {
            "sql": "typing, normalization, joins, aggregation, window-free marts",
            "python": "parameters, orchestration, CSV export, checksums, manifest",
            "pandas": "optional downstream exploration; not required to build marts",
        },
    }


def write_csv(path: Path, columns: list[str], records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def export_marts(
    result: dict[str, Any],
    output_dir: Path,
    sources: dict[str, Path],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, Any]] = {}
    for name in ("order_mart", "user_summary"):
        path = output_dir / f"{name}.csv"
        mart = result[name]
        write_csv(path, mart["columns"], mart["records"])
        artifacts[name] = {
            "path": path.name,
            "rows": len(mart["records"]),
            "grain": mart["grain"],
            "sha256": sha256(path),
        }
    manifest = {
        "name": "sql_marts",
        "duckdb_version": duckdb.__version__,
        "business_timezone": result["business_timezone"],
        "checks": result["checks"],
        "boundary": result["boundary"],
        "artifacts": artifacts,
        "sql": {
            ORDER_MART_SQL.name: sha256(ORDER_MART_SQL),
            USER_SUMMARY_SQL.name: sha256(USER_SUMMARY_SQL),
        },
        "sources": {
            name: {"path": str(path), "sha256": sha256(path)} for name, path in sources.items()
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and export checked SQL marts")
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--business-timezone", default="Europe/Moscow")
    args = parser.parse_args()
    try:
        sources = {
            "users": args.users,
            "orders": args.orders,
            "order_items": args.items,
        }
        result = build_marts(
            args.users,
            args.orders,
            args.items,
            args.business_timezone,
        )
        manifest = export_marts(result, args.output_dir, sources)
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
