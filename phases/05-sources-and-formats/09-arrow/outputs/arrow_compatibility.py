from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


class ArrowCompatibilityError(ValueError):
    """Raised when a table cannot be compared across engines."""


def buffer_addresses(column: pa.ChunkedArray) -> list[int]:
    addresses: list[int] = []
    for chunk in column.chunks:
        addresses.extend(buffer.address for buffer in chunk.buffers() if buffer is not None)
    return addresses


def schema_manifest(schema: pa.Schema) -> list[dict[str, Any]]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in schema
    ]


def scalar_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def build_report(input_path: str | Path) -> dict[str, Any]:
    path = Path(input_path)
    if not path.is_file():
        raise ArrowCompatibilityError(f"Parquet file does not exist: {path}")
    arrow_table = pq.read_table(path)
    pandas_frame = arrow_table.to_pandas(types_mapper=pd.ArrowDtype)
    roundtrip = pa.Table.from_pandas(pandas_frame, preserve_index=False)

    copy_report = {}
    for name in arrow_table.column_names:
        source = buffer_addresses(arrow_table.column(name))
        returned = buffer_addresses(roundtrip.column(name))
        copy_report[name] = {
            "source_buffers": source,
            "roundtrip_buffers": returned,
            "shared_buffer_count": len(set(source) & set(returned)),
            "all_source_buffers_reused": bool(source) and set(source).issubset(returned),
        }

    connection = duckdb.connect()
    try:
        connection.register("orders_arrow", arrow_table)
        metrics = connection.execute(
            """
            SELECT
                count(*) AS rows,
                sum(amount) AS amount_sum,
                count(*) FILTER (WHERE comment IS NULL) AS null_comments
            FROM orders_arrow
            """
        ).fetchone()
        duckdb_reader = connection.execute(
            "SELECT order_id, amount FROM orders_arrow ORDER BY order_id"
        ).arrow()
        duckdb_table = duckdb_reader.read_all()
    finally:
        connection.close()

    arrow_nulls = {name: arrow_table.column(name).null_count for name in arrow_table.column_names}
    roundtrip_nulls = {name: roundtrip.column(name).null_count for name in roundtrip.column_names}
    names_types_preserved = [(field.name, field.type) for field in roundtrip.schema] == [
        (field.name, field.type) for field in arrow_table.schema
    ]
    nullability_preserved = [field.nullable for field in roundtrip.schema] == [
        field.nullable for field in arrow_table.schema
    ]
    checks = {
        "pandas_roundtrip_names_types": names_types_preserved,
        "pandas_roundtrip_values": roundtrip.to_pylist() == arrow_table.to_pylist(),
        "null_counts_preserved": arrow_nulls == roundtrip_nulls,
        "duckdb_rows_match": metrics[0] == arrow_table.num_rows,
    }
    return {
        "arrow": {
            "rows": arrow_table.num_rows,
            "schema": schema_manifest(arrow_table.schema),
            "null_counts": arrow_nulls,
        },
        "pandas": {
            "rows": len(pandas_frame),
            "dtypes": {name: str(dtype) for name, dtype in pandas_frame.dtypes.items()},
            "null_counts": {name: int(value) for name, value in pandas_frame.isna().sum().items()},
        },
        "roundtrip": {
            "schema": schema_manifest(roundtrip.schema),
            "field_nullability_preserved": nullability_preserved,
            "schema_metadata_equal": roundtrip.schema.metadata == arrow_table.schema.metadata,
            "null_counts": roundtrip_nulls,
            "buffers": copy_report,
        },
        "duckdb": {
            "rows": metrics[0],
            "amount_sum": scalar_json(metrics[1]),
            "null_comments": metrics[2],
            "arrow_result_schema": schema_manifest(duckdb_table.schema),
        },
        "checks": checks,
        "summary": {
            "valid": all(checks.values()),
            "columns_with_all_buffers_reused": [
                name for name, value in copy_report.items() if value["all_source_buffers_reused"]
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Arrow, pandas and DuckDB exchange")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(args.input)
    except ArrowCompatibilityError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    sys.stdout.write(content)
    if not report["summary"]["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
