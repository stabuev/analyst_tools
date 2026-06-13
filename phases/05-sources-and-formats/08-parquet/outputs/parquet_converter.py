from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

DECIMAL_PATTERN = re.compile(r"decimal128\((\d+),\s*(\d+)\)")


class ParquetContractError(ValueError):
    """Raised when CSV data cannot satisfy the declared Parquet schema."""


def load_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path)
    if not contract_path.is_file():
        raise ParquetContractError(f"schema file does not exist: {contract_path}")
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ParquetContractError(f"invalid schema JSON: {error.msg}") from error
    if not isinstance(contract.get("columns"), dict) or not contract["columns"]:
        raise ParquetContractError("schema must declare columns")
    return contract


def arrow_type(type_name: str) -> pa.DataType:
    if type_name == "string":
        return pa.string()
    if type_name == "timestamp[us, tz=UTC]":
        return pa.timestamp("us", tz="UTC")
    match = DECIMAL_PATTERN.fullmatch(type_name)
    if match:
        return pa.decimal128(int(match.group(1)), int(match.group(2)))
    raise ParquetContractError(f"unsupported Arrow type: {type_name}")


def build_schema(contract: dict[str, Any]) -> pa.Schema:
    return pa.schema(
        [
            pa.field(name, arrow_type(column["type"]), nullable=column["nullable"])
            for name, column in contract["columns"].items()
        ]
    )


def parse_value(raw: str, field: pa.Field) -> Any:
    if raw == "" and field.nullable:
        return None
    if pa.types.is_string(field.type):
        return raw
    if pa.types.is_decimal(field.type):
        try:
            return Decimal(raw)
        except InvalidOperation as error:
            raise ParquetContractError(f"invalid decimal for {field.name}: {raw!r}") from error
    if pa.types.is_timestamp(field.type):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as error:
            raise ParquetContractError(f"invalid timestamp for {field.name}: {raw!r}") from error
    raise ParquetContractError(f"unsupported field type: {field.type}")


def read_csv_records(path: Path, schema: pa.Schema) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ParquetContractError(f"input CSV does not exist: {path}")
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != schema.names:
            raise ParquetContractError(
                f"CSV header differs: expected {schema.names}, got {reader.fieldnames}"
            )
        records = []
        for line, row in enumerate(reader, start=2):
            try:
                records.append(
                    {field.name: parse_value(row[field.name], field) for field in schema}
                )
            except ParquetContractError as error:
                raise ParquetContractError(f"line {line}: {error}") from error
    return records


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def convert_csv(
    input_path: str | Path,
    output_path: str | Path,
    schema_path: str | Path,
) -> dict[str, Any]:
    source = Path(input_path)
    output = Path(output_path)
    contract = load_contract(schema_path)
    schema = build_schema(contract)
    records = read_csv_records(source, schema)
    try:
        table = pa.Table.from_pylist(records, schema=schema)
    except (pa.ArrowInvalid, pa.ArrowTypeError) as error:
        raise ParquetContractError(f"records do not match Arrow schema: {error}") from error

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.part")
    try:
        pq.write_table(
            table,
            temporary,
            compression=contract["compression"],
            write_statistics=True,
        )
        roundtrip = pq.read_table(temporary)
        checks = {
            "schema_matches": roundtrip.schema == schema,
            "row_count_matches": roundtrip.num_rows == len(records),
            "null_counts_match": all(
                roundtrip.column(name).null_count == sum(record[name] is None for record in records)
                for name in schema.names
            ),
        }
        if not all(checks.values()):
            raise ParquetContractError(f"written Parquet failed checks: {checks}")
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    parquet_file = pq.ParquetFile(output)
    compressions = sorted(
        {
            parquet_file.metadata.row_group(group).column(column).compression
            for group in range(parquet_file.metadata.num_row_groups)
            for column in range(parquet_file.metadata.num_columns)
        }
    )
    return {
        "source": {
            "path": str(source),
            "bytes": source.stat().st_size,
            "sha256": sha256(source),
        },
        "output": {
            "path": str(output),
            "bytes": output.stat().st_size,
            "sha256": sha256(output),
            "compression": compressions,
            "row_groups": parquet_file.metadata.num_row_groups,
        },
        "schema": [
            {"name": field.name, "type": str(field.type), "nullable": field.nullable}
            for field in schema
        ],
        "rows": len(records),
        "checks": checks,
        "summary": {"valid": all(checks.values())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert CSV to schema-bound Parquet")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        manifest = convert_csv(args.input, args.output, args.schema)
    except ParquetContractError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    json.dump(manifest, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
