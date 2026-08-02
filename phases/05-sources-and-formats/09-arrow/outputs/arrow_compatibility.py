from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

CONTRACT_VERSION = "1.0.0"
REPORT_VERSION = "1.0.0"
DEFAULT_MAX_BYTES = 10_000_000
ROOT_KEYS = {"version", "source", "routes"}
SOURCE_KEYS = {"columns", "grain", "row_count", "null_counts"}
COLUMN_KEYS = {"name", "type", "nullable"}
ROUTE_KEYS = {"pandas_roundtrip", "duckdb_roundtrip"}
PANDAS_KEYS = {
    "preserve_index",
    "require_arrow_backed_dtypes",
    "allow_field_nullability_loss",
}
DUCKDB_KEYS = {"session_timezone", "allow_field_nullability_loss"}
DECIMAL_TYPE = re.compile(r"decimal128\((\d+),\s*(\d+)\)")
TIMESTAMP_TYPE = re.compile(r"timestamp\[(s|ms|us|ns),\s*tz=([^\]]+)\]")


class ArrowCompatibilityError(ValueError):
    """Raised when configuration or source data cannot satisfy the exchange audit."""


class ArrowRouteError(RuntimeError):
    """Raised when an exchange route cannot be executed."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ArrowCompatibilityError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise ArrowCompatibilityError(f"{label} misses keys: {missing}")
    if unknown:
        raise ArrowCompatibilityError(f"{label} has unknown keys: {unknown}")


def _valid_type_name(type_name: Any) -> bool:
    if type_name == "string":
        return True
    if isinstance(type_name, str):
        decimal = DECIMAL_TYPE.fullmatch(type_name)
        if decimal:
            precision, scale = (int(value) for value in decimal.groups())
            return 1 <= precision <= 38 and 0 <= scale <= precision
        timestamp = TIMESTAMP_TYPE.fullmatch(type_name)
        if timestamp:
            return bool(timestamp.group(2))
    return False


def _parse_contract_bytes(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ArrowCompatibilityError("exchange contract must be valid UTF-8") from error
    try:
        contract = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise ArrowCompatibilityError(f"invalid contract JSON: {error.msg}") from error
    if not isinstance(contract, dict):
        raise ArrowCompatibilityError("exchange contract root must be an object")
    _exact_keys(contract, ROOT_KEYS, "contract")
    if contract["version"] != CONTRACT_VERSION:
        raise ArrowCompatibilityError(
            f"unsupported contract version: {contract['version']!r}; expected {CONTRACT_VERSION!r}"
        )

    source = contract["source"]
    if not isinstance(source, dict):
        raise ArrowCompatibilityError("source must be an object")
    _exact_keys(source, SOURCE_KEYS, "source")
    columns = source["columns"]
    if not isinstance(columns, list) or not columns:
        raise ArrowCompatibilityError("source.columns must be a non-empty list")
    names: list[str] = []
    for position, column in enumerate(columns):
        label = f"source.columns[{position}]"
        if not isinstance(column, dict):
            raise ArrowCompatibilityError(f"{label} must be an object")
        _exact_keys(column, COLUMN_KEYS, label)
        name = column["name"]
        if not isinstance(name, str) or not name:
            raise ArrowCompatibilityError(f"{label}.name must be a non-empty string")
        if name in names:
            raise ArrowCompatibilityError(f"duplicate source column: {name}")
        names.append(name)
        if not _valid_type_name(column["type"]):
            raise ArrowCompatibilityError(f"unsupported source type for {name}: {column['type']!r}")
        if type(column["nullable"]) is not bool:
            raise ArrowCompatibilityError(f"{label}.nullable must be boolean")

    grain = source["grain"]
    if (
        not isinstance(grain, list)
        or not grain
        or any(not isinstance(name, str) for name in grain)
        or len(set(grain)) != len(grain)
    ):
        raise ArrowCompatibilityError("source.grain must contain unique column names")
    unknown_grain = sorted(set(grain) - set(names))
    if unknown_grain:
        raise ArrowCompatibilityError(f"source.grain refers to unknown columns: {unknown_grain}")
    by_name = {column["name"]: column for column in columns}
    nullable_grain = [name for name in grain if by_name[name]["nullable"]]
    if nullable_grain:
        raise ArrowCompatibilityError(f"source.grain columns must be non-null: {nullable_grain}")
    if type(source["row_count"]) is not int or source["row_count"] < 0:
        raise ArrowCompatibilityError("source.row_count must be a non-negative integer")
    null_counts = source["null_counts"]
    if not isinstance(null_counts, dict) or set(null_counts) != set(names):
        raise ArrowCompatibilityError("source.null_counts must declare every source column exactly")
    if any(type(value) is not int or value < 0 for value in null_counts.values()):
        raise ArrowCompatibilityError("source.null_counts values must be non-negative integers")
    if any(value > source["row_count"] for value in null_counts.values()):
        raise ArrowCompatibilityError("source.null_counts cannot exceed source.row_count")

    routes = contract["routes"]
    if not isinstance(routes, dict):
        raise ArrowCompatibilityError("routes must be an object")
    _exact_keys(routes, ROUTE_KEYS, "routes")
    pandas_route = routes["pandas_roundtrip"]
    duckdb_route = routes["duckdb_roundtrip"]
    if not isinstance(pandas_route, dict) or not isinstance(duckdb_route, dict):
        raise ArrowCompatibilityError("each route must be an object")
    _exact_keys(pandas_route, PANDAS_KEYS, "routes.pandas_roundtrip")
    _exact_keys(duckdb_route, DUCKDB_KEYS, "routes.duckdb_roundtrip")
    if any(type(pandas_route[key]) is not bool for key in PANDAS_KEYS):
        raise ArrowCompatibilityError("pandas route policy values must be boolean")
    if pandas_route["preserve_index"]:
        raise ArrowCompatibilityError("contract version 1 supports preserve_index=false only")
    if type(duckdb_route["allow_field_nullability_loss"]) is not bool:
        raise ArrowCompatibilityError("duckdb nullability policy must be boolean")
    if duckdb_route["session_timezone"] != "UTC":
        raise ArrowCompatibilityError("contract version 1 requires DuckDB session_timezone=UTC")
    return contract


def load_contract(path: str | Path) -> dict[str, Any]:
    contract_path = Path(path)
    if not contract_path.is_file():
        raise ArrowCompatibilityError(f"exchange contract does not exist: {contract_path}")
    try:
        raw = contract_path.read_bytes()
    except OSError as error:
        raise ArrowCompatibilityError(f"cannot read exchange contract: {error}") from error
    return _parse_contract_bytes(raw)


def schema_manifest(schema: pa.Schema) -> list[dict[str, Any]]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in schema
    ]


def null_counts(table: pa.Table) -> dict[str, int]:
    return {name: table.column(name).null_count for name in table.column_names}


def _grain_errors(table: pa.Table, grain: list[str]) -> list[str]:
    seen: dict[tuple[Any, ...], int] = {}
    errors: list[str] = []
    rows = table.select(grain).to_pylist()
    for position, row in enumerate(rows):
        key = tuple(row[name] for name in grain)
        if any(value is None for value in key):
            errors.append(f"row {position}: null grain {key!r}")
        elif key in seen:
            errors.append(f"row {position}: duplicate grain {key!r}; first at row {seen[key]}")
        else:
            seen[key] = position
    return errors


def _validate_source(table: pa.Table, contract: dict[str, Any]) -> None:
    expected = contract["source"]
    errors: list[str] = []
    if schema_manifest(table.schema) != expected["columns"]:
        errors.append(
            f"schema differs: expected {expected['columns']}, got {schema_manifest(table.schema)}"
        )
    if table.num_rows != expected["row_count"]:
        errors.append(f"row count differs: expected {expected['row_count']}, got {table.num_rows}")
    observed_nulls = null_counts(table)
    if observed_nulls != expected["null_counts"]:
        errors.append(
            f"null counts differ: expected {expected['null_counts']}, got {observed_nulls}"
        )
    errors.extend(_grain_errors(table, expected["grain"]))
    if errors:
        raise ArrowCompatibilityError("source violates exchange contract: " + "; ".join(errors))


def _canonical_rows(table: pa.Table, grain: list[str]) -> list[dict[str, Any]]:
    indices = pc.sort_indices(table, sort_keys=[(name, "ascending") for name in grain])
    return table.take(indices).to_pylist()


def _nullability_observation(
    source: pa.Schema,
    returned: pa.Schema,
    *,
    allow_loss: bool,
) -> dict[str, Any]:
    if source.names != returned.names:
        return {
            "exact": False,
            "only_relaxed": False,
            "allowed": False,
            "changed_fields": [],
        }
    changed = [
        {
            "name": source_field.name,
            "source_nullable": source_field.nullable,
            "returned_nullable": returned_field.nullable,
        }
        for source_field, returned_field in zip(source, returned, strict=True)
        if source_field.nullable != returned_field.nullable
    ]
    only_relaxed = all(
        not source_field.nullable or returned_field.nullable
        for source_field, returned_field in zip(source, returned, strict=True)
    )
    exact = not changed
    return {
        "exact": exact,
        "only_relaxed": only_relaxed,
        "allowed": exact or (allow_loss and only_relaxed),
        "changed_fields": changed,
    }


def compare_route(
    source: pa.Table,
    returned: pa.Table,
    *,
    grain: list[str],
    allow_field_nullability_loss: bool,
) -> dict[str, Any]:
    source_names_types = [(field.name, str(field.type)) for field in source.schema]
    returned_names_types = [(field.name, str(field.type)) for field in returned.schema]
    nullability = _nullability_observation(
        source.schema,
        returned.schema,
        allow_loss=allow_field_nullability_loss,
    )
    checks = {
        "row_count_preserved": source.num_rows == returned.num_rows,
        "names_and_types_preserved": source_names_types == returned_names_types,
        "values_preserved": _canonical_rows(source, grain) == _canonical_rows(returned, grain),
        "null_counts_preserved": null_counts(source) == null_counts(returned),
        "field_nullability_policy_satisfied": nullability["allowed"],
    }
    return {
        "rows": returned.num_rows,
        "schema": schema_manifest(returned.schema),
        "null_counts": null_counts(returned),
        "schema_metadata_equal": source.schema.metadata == returned.schema.metadata,
        "field_nullability": nullability,
        "checks": checks,
        "valid": all(checks.values()),
    }


def _buffer_identities(column: pa.ChunkedArray) -> set[tuple[int, int]]:
    identities: set[tuple[int, int]] = set()
    for chunk in column.chunks:
        for buffer in chunk.buffers():
            if buffer is not None and buffer.size:
                identities.add((buffer.address, buffer.size))
    return identities


def buffer_reuse_report(source: pa.Table, returned: pa.Table) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for name in source.column_names:
        source_buffers = _buffer_identities(source.column(name))
        returned_buffers = _buffer_identities(returned.column(name))
        shared = source_buffers & returned_buffers
        source_bytes = sum(size for _, size in source_buffers)
        shared_bytes = sum(size for _, size in shared)
        report[name] = {
            "source_buffer_count": len(source_buffers),
            "returned_buffer_count": len(returned_buffers),
            "shared_buffer_count": len(shared),
            "source_buffer_bytes": source_bytes,
            "shared_source_bytes": shared_bytes,
            "shared_source_fraction": (
                round(shared_bytes / source_bytes, 6) if source_bytes else None
            ),
            "all_source_buffers_reused": bool(source_buffers)
            and source_buffers.issubset(returned_buffers),
        }
    return report


def _read_parquet_bytes(path: Path, max_bytes: int) -> tuple[pa.Table, bytes]:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ArrowCompatibilityError("max_bytes must be a positive integer")
    if not path.is_file():
        raise ArrowCompatibilityError(f"Parquet file does not exist: {path}")
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ArrowCompatibilityError(f"cannot inspect Parquet file: {error}") from error
    if size > max_bytes:
        raise ArrowCompatibilityError(f"Parquet file exceeds max_bytes: {size} > {max_bytes}")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ArrowCompatibilityError(f"cannot read Parquet file: {error}") from error
    if len(raw) > max_bytes:
        raise ArrowCompatibilityError(f"Parquet file exceeds max_bytes: {len(raw)} > {max_bytes}")
    try:
        table = pq.read_table(pa.BufferReader(raw))
    except pa.ArrowException as error:
        raise ArrowCompatibilityError(f"cannot decode Parquet input: {error}") from error
    return table, raw


def _pandas_roundtrip(table: pa.Table, preserve_index: bool) -> tuple[pd.DataFrame, pa.Table]:
    try:
        frame = table.to_pandas(types_mapper=pd.ArrowDtype)
        returned = pa.Table.from_pandas(frame, preserve_index=preserve_index)
    except Exception as error:
        raise ArrowRouteError(f"pandas roundtrip failed: {error}") from error
    return frame, returned


def _duckdb_roundtrip(table: pa.Table, session_timezone: str) -> tuple[pa.Table, str]:
    connection = duckdb.connect()
    try:
        if session_timezone != "UTC":
            raise ArrowRouteError(f"unsupported DuckDB session timezone: {session_timezone}")
        connection.execute("SET TimeZone = 'UTC'")
        observed_timezone = connection.execute("SELECT current_setting('TimeZone')").fetchone()[0]
        connection.register("source_arrow", table)
        returned = connection.execute("SELECT * FROM source_arrow").to_arrow_table()
    except ArrowRouteError:
        raise
    except Exception as error:
        raise ArrowRouteError(f"DuckDB roundtrip failed: {error}") from error
    finally:
        connection.close()
    return returned, observed_timezone


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build_report(
    input_path: str | Path,
    contract_path: str | Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    source_path = Path(input_path)
    contract_file = Path(contract_path)
    if not contract_file.is_file():
        raise ArrowCompatibilityError(f"exchange contract does not exist: {contract_file}")
    try:
        contract_raw = contract_file.read_bytes()
    except OSError as error:
        raise ArrowCompatibilityError(f"cannot read exchange contract: {error}") from error
    contract = _parse_contract_bytes(contract_raw)
    source, source_raw = _read_parquet_bytes(source_path, max_bytes)
    _validate_source(source, contract)

    pandas_policy = contract["routes"]["pandas_roundtrip"]
    frame, pandas_returned = _pandas_roundtrip(source, pandas_policy["preserve_index"])
    pandas_report = compare_route(
        source,
        pandas_returned,
        grain=contract["source"]["grain"],
        allow_field_nullability_loss=pandas_policy["allow_field_nullability_loss"],
    )
    arrow_backed = {name: isinstance(dtype, pd.ArrowDtype) for name, dtype in frame.dtypes.items()}
    pandas_report.update(
        {
            "dtypes": {name: str(dtype) for name, dtype in frame.dtypes.items()},
            "arrow_backed_dtypes": arrow_backed,
            "buffer_reuse": buffer_reuse_report(source, pandas_returned),
        }
    )
    pandas_report["checks"]["arrow_backed_dtype_policy_satisfied"] = (
        all(arrow_backed.values()) if pandas_policy["require_arrow_backed_dtypes"] else True
    )
    pandas_report["valid"] = all(pandas_report["checks"].values())

    duckdb_policy = contract["routes"]["duckdb_roundtrip"]
    duckdb_returned, observed_timezone = _duckdb_roundtrip(
        source,
        duckdb_policy["session_timezone"],
    )
    duckdb_report = compare_route(
        source,
        duckdb_returned,
        grain=contract["source"]["grain"],
        allow_field_nullability_loss=duckdb_policy["allow_field_nullability_loss"],
    )
    duckdb_report["session_timezone"] = observed_timezone
    duckdb_report["checks"]["session_timezone_pinned"] = observed_timezone == "UTC"
    duckdb_report["valid"] = all(duckdb_report["checks"].values())

    memory = pandas_report["buffer_reuse"]
    return {
        "report_version": REPORT_VERSION,
        "source": {
            "name": source_path.name,
            "bytes": len(source_raw),
            "sha256": _sha256(source_raw),
            "rows": source.num_rows,
            "schema": schema_manifest(source.schema),
            "null_counts": null_counts(source),
        },
        "contract": {
            "name": contract_file.name,
            "bytes": len(contract_raw),
            "sha256": _sha256(contract_raw),
            "value": contract,
        },
        "libraries": {
            "pyarrow": pa.__version__,
            "pandas": pd.__version__,
            "duckdb": duckdb.__version__,
        },
        "pandas_roundtrip": pandas_report,
        "duckdb_roundtrip": duckdb_report,
        "summary": {
            "valid": pandas_report["valid"] and duckdb_report["valid"],
            "semantic_routes_valid": {
                "pandas_roundtrip": pandas_report["valid"],
                "duckdb_roundtrip": duckdb_report["valid"],
            },
            "columns_with_all_source_buffers_reused": [
                name
                for name, observation in memory.items()
                if observation["all_source_buffers_reused"]
            ],
            "memory_evidence_scope": (
                "source Arrow table to pandas-backed Arrow roundtrip in this process"
            ),
        },
    }


def _sibling_temp(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".json.part",
        dir=path.parent,
    )
    os.close(descriptor)
    return Path(name)


def publish_report(report: dict[str, Any], output_path: str | Path) -> None:
    if not report.get("summary", {}).get("valid"):
        raise ArrowRouteError("invalid compatibility report must not be published")
    output = Path(output_path)
    temporary = _sibling_temp(output)
    try:
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def _positive_cli_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit Arrow exchange across pandas and DuckDB without claiming universal zero-copy"
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-bytes", type=_positive_cli_int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    resolved = {
        args.input.resolve(strict=False),
        args.contract.resolve(strict=False),
        args.output.resolve(strict=False),
    }
    if len(resolved) != 3:
        parser.error("input, contract and output paths must be distinct")
    try:
        report = build_report(args.input, args.contract, max_bytes=args.max_bytes)
    except ArrowCompatibilityError as error:
        print(
            json.dumps({"kind": "contract", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(2) from error
    except ArrowRouteError as error:
        print(
            json.dumps({"kind": "route", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(1) from error
    content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not report["summary"]["valid"]:
        sys.stdout.write(content)
        raise SystemExit(1)
    publish_report(report, args.output)
    sys.stdout.write(content)


if __name__ == "__main__":
    main()
