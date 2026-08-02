from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

CONTRACT_VERSION = "2.0.0"
DEFAULT_MAX_ROWS = 100_000
DEFAULT_MAX_BYTES = 10_000_000
DECIMAL_PATTERN = re.compile(r"decimal128\((\d+),\s*(\d+)\)")
OFFSET_PATTERN = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")
ROOT_KEYS = {"version", "grain", "allow_empty", "columns", "writer"}
COLUMN_REQUIRED_KEYS = {"name", "type", "nullable", "empty_as_null"}
COLUMN_OPTIONAL_KEYS = {"domain"}
WRITER_KEYS = {"compression", "write_statistics", "row_group_size"}
SUPPORTED_COMPRESSIONS = {"zstd": "ZSTD", "snappy": "SNAPPY", "none": "UNCOMPRESSED"}


class ParquetContractError(ValueError):
    """Raised when configuration or source data violates the declared contract."""


class ParquetVerificationError(RuntimeError):
    """Raised when a written Parquet candidate fails roundtrip verification."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ParquetContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _exact_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    label: str,
) -> None:
    optional = optional or set()
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - required - optional)
    if missing:
        raise ParquetContractError(f"{label} misses keys: {missing}")
    if unknown:
        raise ParquetContractError(f"{label} has unknown keys: {unknown}")


def _parse_contract_bytes(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ParquetContractError("schema JSON must be valid UTF-8") from error
    try:
        contract = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise ParquetContractError(f"invalid schema JSON: {error.msg}") from error
    if not isinstance(contract, dict):
        raise ParquetContractError("schema JSON root must be an object")
    _exact_keys(contract, required=ROOT_KEYS, label="schema")

    if contract["version"] != CONTRACT_VERSION:
        raise ParquetContractError(
            f"unsupported schema version: {contract['version']!r}; expected {CONTRACT_VERSION!r}"
        )
    if type(contract["allow_empty"]) is not bool:
        raise ParquetContractError("allow_empty must be boolean")

    columns = contract["columns"]
    if not isinstance(columns, list) or not columns:
        raise ParquetContractError("columns must be a non-empty list")
    names: list[str] = []
    for position, column in enumerate(columns):
        label = f"columns[{position}]"
        if not isinstance(column, dict):
            raise ParquetContractError(f"{label} must be an object")
        _exact_keys(
            column,
            required=COLUMN_REQUIRED_KEYS,
            optional=COLUMN_OPTIONAL_KEYS,
            label=label,
        )
        name = column["name"]
        if not isinstance(name, str) or not name:
            raise ParquetContractError(f"{label}.name must be a non-empty string")
        if name in names:
            raise ParquetContractError(f"duplicate column name: {name}")
        names.append(name)
        if type(column["nullable"]) is not bool or type(column["empty_as_null"]) is not bool:
            raise ParquetContractError(f"{label} nullable and empty_as_null must be boolean")
        if column["empty_as_null"] and not column["nullable"]:
            raise ParquetContractError(f"{label} cannot map empty to null for a non-null field")
        arrow_type(column["type"])
        if "domain" in column:
            domain = column["domain"]
            if column["type"] != "string":
                raise ParquetContractError(f"{label}.domain is supported only for string")
            if (
                not isinstance(domain, list)
                or not domain
                or any(not isinstance(item, str) or not item for item in domain)
                or len(set(domain)) != len(domain)
            ):
                raise ParquetContractError(f"{label}.domain must contain unique non-empty strings")

    grain = contract["grain"]
    if (
        not isinstance(grain, list)
        or not grain
        or any(not isinstance(name, str) for name in grain)
        or len(set(grain)) != len(grain)
    ):
        raise ParquetContractError("grain must contain unique column names")
    unknown_grain = sorted(set(grain) - set(names))
    if unknown_grain:
        raise ParquetContractError(f"grain refers to unknown columns: {unknown_grain}")
    by_name = {column["name"]: column for column in columns}
    nullable_grain = [name for name in grain if by_name[name]["nullable"]]
    if nullable_grain:
        raise ParquetContractError(f"grain columns must be non-null: {nullable_grain}")

    writer = contract["writer"]
    if not isinstance(writer, dict):
        raise ParquetContractError("writer must be an object")
    _exact_keys(writer, required=WRITER_KEYS, label="writer")
    if writer["compression"] not in SUPPORTED_COMPRESSIONS:
        raise ParquetContractError(f"unsupported compression: {writer['compression']!r}")
    if type(writer["write_statistics"]) is not bool:
        raise ParquetContractError("writer.write_statistics must be boolean")
    if type(writer["row_group_size"]) is not int or writer["row_group_size"] <= 0:
        raise ParquetContractError("writer.row_group_size must be a positive integer")
    return contract


def load_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path)
    if not contract_path.is_file():
        raise ParquetContractError(f"schema file does not exist: {contract_path}")
    try:
        raw = contract_path.read_bytes()
    except OSError as error:
        raise ParquetContractError(f"cannot read schema file: {error}") from error
    return _parse_contract_bytes(raw)


def arrow_type(type_name: Any) -> pa.DataType:
    if type_name == "string":
        return pa.string()
    if type_name == "timestamp[us, tz=UTC]":
        return pa.timestamp("us", tz="UTC")
    if isinstance(type_name, str):
        match = DECIMAL_PATTERN.fullmatch(type_name)
        if match:
            precision, scale = (int(value) for value in match.groups())
            if 1 <= precision <= 38 and 0 <= scale <= precision:
                return pa.decimal128(precision, scale)
    raise ParquetContractError(f"unsupported Arrow type: {type_name!r}")


def build_schema(contract: dict[str, Any]) -> pa.Schema:
    return pa.schema(
        [
            pa.field(
                column["name"],
                arrow_type(column["type"]),
                nullable=column["nullable"],
            )
            for column in contract["columns"]
        ]
    )


def _parse_decimal(raw: str, field: pa.Field) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ParquetContractError(f"invalid decimal for {field.name}: {raw!r}") from error
    if not value.is_finite():
        raise ParquetContractError(f"decimal must be finite for {field.name}: {raw!r}")
    quantum = Decimal(1).scaleb(-field.type.scale)
    try:
        quantized = value.quantize(quantum)
    except InvalidOperation as error:
        raise ParquetContractError(
            f"decimal exceeds {field.type} for {field.name}: {raw!r}"
        ) from error
    if quantized != value:
        raise ParquetContractError(
            f"decimal has more than {field.type.scale} fractional digits for {field.name}: {raw!r}"
        )
    digits = format(quantized.copy_abs(), "f").replace(".", "").lstrip("0") or "0"
    if len(digits) > field.type.precision:
        raise ParquetContractError(f"decimal exceeds {field.type} for {field.name}: {raw!r}")
    return quantized


def _parse_timestamp(raw: str, field: pa.Field) -> datetime:
    if OFFSET_PATTERN.search(raw) is None:
        raise ParquetContractError(
            f"timestamp requires Z or numeric UTC offset for {field.name}: {raw!r}"
        )
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise ParquetContractError(f"invalid timestamp for {field.name}: {raw!r}") from error
    if value.tzinfo is None or value.utcoffset() is None:
        raise ParquetContractError(f"timestamp is timezone-naive for {field.name}: {raw!r}")
    return value.astimezone(UTC)


def parse_value(raw: str, field: pa.Field, column: dict[str, Any]) -> Any:
    if raw == "":
        if column["empty_as_null"]:
            return None
        if not field.nullable:
            raise ParquetContractError(f"empty value for non-null field {field.name}")
    if pa.types.is_string(field.type):
        value: Any = raw
    elif pa.types.is_decimal(field.type):
        value = _parse_decimal(raw, field)
    elif pa.types.is_timestamp(field.type):
        value = _parse_timestamp(raw, field)
    else:  # pragma: no cover - build_schema prevents this branch
        raise ParquetContractError(f"unsupported field type: {field.type}")
    domain = column.get("domain")
    if domain is not None and value not in domain:
        raise ParquetContractError(
            f"value outside domain for {field.name}: {value!r}; expected one of {domain}"
        )
    return value


def _positive_limit(value: int, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise ParquetContractError(f"{label} must be a positive integer")


def read_csv_records(
    path: str | Path,
    contract: dict[str, Any],
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[list[dict[str, Any]], bytes]:
    _positive_limit(max_rows, "max_rows")
    _positive_limit(max_bytes, "max_bytes")
    source = Path(path)
    if not source.is_file():
        raise ParquetContractError(f"input CSV does not exist: {source}")
    try:
        raw = source.read_bytes()
    except OSError as error:
        raise ParquetContractError(f"cannot read input CSV: {error}") from error
    if len(raw) > max_bytes:
        raise ParquetContractError(f"input CSV exceeds max_bytes: {len(raw)} > {max_bytes}")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ParquetContractError("input CSV must be valid UTF-8") from error

    schema = build_schema(contract)
    columns = {column["name"]: column for column in contract["columns"]}
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except StopIteration as error:
        raise ParquetContractError("input CSV is empty and has no header") from error
    except csv.Error as error:
        raise ParquetContractError(f"invalid CSV header: {error}") from error
    if header != schema.names:
        raise ParquetContractError(f"CSV header differs: expected {schema.names}, got {header}")

    records: list[dict[str, Any]] = []
    seen_grain: dict[tuple[Any, ...], int] = {}
    try:
        for row in reader:
            line = reader.line_num
            if len(row) != len(schema):
                raise ParquetContractError(
                    f"line {line}: expected {len(schema)} fields, got {len(row)}"
                )
            if len(records) >= max_rows:
                raise ParquetContractError(
                    f"input CSV exceeds max_rows: more than {max_rows} data rows"
                )
            try:
                record = {
                    field.name: parse_value(raw_value, field, columns[field.name])
                    for field, raw_value in zip(schema, row, strict=True)
                }
            except ParquetContractError as error:
                raise ParquetContractError(f"line {line}: {error}") from error
            grain = tuple(record[name] for name in contract["grain"])
            if grain in seen_grain:
                first_line = seen_grain[grain]
                raise ParquetContractError(
                    f"line {line}: duplicate grain {grain!r}; first seen on line {first_line}"
                )
            seen_grain[grain] = line
            records.append(record)
    except csv.Error as error:
        raise ParquetContractError(f"invalid CSV near line {reader.line_num}: {error}") from error
    if not records and not contract["allow_empty"]:
        raise ParquetContractError("input CSV has no data rows but allow_empty is false")
    return records, raw


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sibling_temp(path: Path, suffix: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=suffix,
        dir=path.parent,
    )
    os.close(descriptor)
    return Path(name)


def _inspect_candidate(
    path: Path,
    table: pa.Table,
    contract: dict[str, Any],
) -> tuple[dict[str, bool], dict[str, Any]]:
    roundtrip = pq.read_table(path)
    parquet_file = pq.ParquetFile(path)
    metadata = parquet_file.metadata
    compressions: set[str] = set()
    statistics_present = True
    row_groups: list[dict[str, Any]] = []
    for group_index in range(metadata.num_row_groups):
        group = metadata.row_group(group_index)
        columns: list[dict[str, Any]] = []
        for column_index in range(metadata.num_columns):
            column = group.column(column_index)
            compressions.add(column.compression)
            statistics_present = statistics_present and column.statistics is not None
            columns.append(
                {
                    "name": column.path_in_schema,
                    "compression": column.compression,
                    "num_values": column.num_values,
                    "statistics_present": column.statistics is not None,
                }
            )
        row_groups.append({"rows": group.num_rows, "columns": columns})

    expected_row_groups = math.ceil(table.num_rows / contract["writer"]["row_group_size"])
    expected_compression = SUPPORTED_COMPRESSIONS[contract["writer"]["compression"]]
    checks = {
        "schema_matches": roundtrip.schema == table.schema,
        "row_count_matches": roundtrip.num_rows == table.num_rows,
        "values_and_order_match": roundtrip.equals(table),
        "null_counts_match": all(
            roundtrip.column(name).null_count == table.column(name).null_count
            for name in table.schema.names
        ),
        "row_groups_match": metadata.num_row_groups == expected_row_groups,
        "compression_matches": compressions
        == ({expected_compression} if table.num_rows else set()),
        "statistics_match_policy": (statistics_present == contract["writer"]["write_statistics"]),
    }
    observed = {
        "rows": roundtrip.num_rows,
        "row_groups": metadata.num_row_groups,
        "compression": sorted(compressions),
        "schema": [
            {"name": field.name, "type": str(field.type), "nullable": field.nullable}
            for field in roundtrip.schema
        ],
        "row_group_metadata": row_groups,
    }
    return checks, observed


def _write_json_temp(path: Path, value: dict[str, Any]) -> Path:
    temporary = _sibling_temp(path, ".json.part")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def convert_csv(
    input_path: str | Path,
    output_path: str | Path,
    schema_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    source = Path(input_path)
    output = Path(output_path)
    contract_file = Path(schema_path)
    manifest_file = (
        Path(manifest_path)
        if manifest_path is not None
        else output.with_name(f"{output.name}.manifest.json")
    )
    resolved = [
        source.resolve(strict=False),
        output.resolve(strict=False),
        contract_file.resolve(strict=False),
        manifest_file.resolve(strict=False),
    ]
    if len(set(resolved)) != len(resolved):
        raise ParquetContractError("input, output, schema and manifest paths must be distinct")
    if not contract_file.is_file():
        raise ParquetContractError(f"schema file does not exist: {contract_file}")
    try:
        contract_raw = contract_file.read_bytes()
    except OSError as error:
        raise ParquetContractError(f"cannot read schema file: {error}") from error
    contract = _parse_contract_bytes(contract_raw)
    records, source_raw = read_csv_records(
        source,
        contract,
        max_rows=max_rows,
        max_bytes=max_bytes,
    )
    schema = build_schema(contract)
    try:
        table = pa.Table.from_pylist(records, schema=schema)
    except (pa.ArrowInvalid, pa.ArrowTypeError, pa.ArrowNotImplementedError) as error:
        raise ParquetContractError(f"records do not match Arrow schema: {error}") from error

    parquet_temp = _sibling_temp(output, ".parquet.part")
    manifest_temp: Path | None = None
    try:
        pq.write_table(
            table,
            parquet_temp,
            compression=contract["writer"]["compression"],
            write_statistics=contract["writer"]["write_statistics"],
            row_group_size=contract["writer"]["row_group_size"],
        )
        checks, observed = _inspect_candidate(parquet_temp, table, contract)
        if not all(checks.values()):
            raise ParquetVerificationError(f"written Parquet failed checks: {checks}")
        manifest = {
            "manifest_version": "1.0.0",
            "source": {
                "name": source.name,
                "bytes": len(source_raw),
                "sha256": _sha256_bytes(source_raw),
            },
            "contract": {
                "name": contract_file.name,
                "bytes": len(contract_raw),
                "sha256": _sha256_bytes(contract_raw),
                "value": contract,
            },
            "artifact": {
                "name": output.name,
                "bytes": parquet_temp.stat().st_size,
                "sha256": _sha256_file(parquet_temp),
            },
            "writer": {
                "library": "pyarrow",
                "version": pa.__version__,
                "compression": contract["writer"]["compression"],
                "write_statistics": contract["writer"]["write_statistics"],
                "row_group_size": contract["writer"]["row_group_size"],
                "max_rows": max_rows,
                "max_bytes": max_bytes,
            },
            "observed": observed,
            "checks": checks,
            "summary": {"valid": True},
        }
        manifest_temp = _write_json_temp(manifest_file, manifest)
        os.replace(parquet_temp, output)
        os.replace(manifest_temp, manifest_file)
        manifest_temp = None
        return manifest
    except (OSError, pa.ArrowException) as error:
        raise ParquetContractError(f"cannot write or verify Parquet delivery: {error}") from error
    finally:
        parquet_temp.unlink(missing_ok=True)
        if manifest_temp is not None:
            manifest_temp.unlink(missing_ok=True)


def _positive_cli_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert one bounded UTF-8 CSV snapshot to contract-checked Parquet"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--max-rows", type=_positive_cli_int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("--max-bytes", type=_positive_cli_int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    try:
        manifest = convert_csv(
            args.input,
            args.output,
            args.schema,
            manifest_path=args.manifest,
            max_rows=args.max_rows,
            max_bytes=args.max_bytes,
        )
    except ParquetVerificationError as error:
        print(
            json.dumps({"kind": "verification", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(1) from error
    except ParquetContractError as error:
        print(
            json.dumps({"kind": "contract", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(2) from error
    json.dump(manifest, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
