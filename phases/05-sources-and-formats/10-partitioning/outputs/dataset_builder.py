from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

CONTRACT_VERSION = "1.0.0"
MANIFEST_VERSION = "1.0.0"
DEFAULT_MAX_BYTES = 10_000_000
MAX_CONTRACT_BYTES = 1_000_000
ROOT_KEYS = {
    "version",
    "source",
    "derived_columns",
    "candidates",
    "selected",
    "workload",
    "diagnostics",
}
SOURCE_KEYS = {"columns", "grain", "row_count", "null_counts"}
COLUMN_KEYS = {"name", "type", "nullable"}
DERIVED_KEYS = {"name", "source", "transform"}
CANDIDATE_KEYS = {"name", "partition_by"}
WORKLOAD_KEYS = {"name", "filters"}
DIAGNOSTIC_KEYS = {"small_partition_rows", "allow_null_partition_values"}
SUPPORTED_TRANSFORMS = {"utc_month": "%Y-%m", "utc_date": "%Y-%m-%d"}
DECIMAL_TYPE = re.compile(r"decimal128\((\d+),\s*(\d+)\)")
TIMESTAMP_TYPE = re.compile(r"timestamp\[(s|ms|us|ns),\s*tz=([^\]]+)\]")


class LayoutContractError(ValueError):
    """Raised when the layout contract or source violates its declared rules."""


class DatasetBuildError(RuntimeError):
    """Raised when a validated candidate cannot be built or verified."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LayoutContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise LayoutContractError(f"{label} misses keys: {missing}")
    if unknown:
        raise LayoutContractError(f"{label} has unknown keys: {unknown}")


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


def _read_bounded(path: Path, *, max_bytes: int, label: str) -> bytes:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise LayoutContractError(f"{label} max_bytes must be a positive integer")
    if not path.is_file():
        raise LayoutContractError(f"{label} does not exist: {path}")
    try:
        size = path.stat().st_size
    except OSError as error:
        raise LayoutContractError(f"cannot inspect {label}: {error}") from error
    if size > max_bytes:
        raise LayoutContractError(f"{label} exceeds max_bytes: {size} > {max_bytes}")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise LayoutContractError(f"cannot read {label}: {error}") from error
    if len(raw) > max_bytes:
        raise LayoutContractError(f"{label} exceeds max_bytes: {len(raw)} > {max_bytes}")
    return raw


def _parse_contract(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise LayoutContractError("layout contract must be valid UTF-8") from error
    try:
        contract = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as error:
        raise LayoutContractError(f"invalid layout contract JSON: {error.msg}") from error
    if not isinstance(contract, dict):
        raise LayoutContractError("layout contract root must be an object")
    _exact_keys(contract, ROOT_KEYS, "contract")
    if contract["version"] != CONTRACT_VERSION:
        raise LayoutContractError(
            f"unsupported contract version: {contract['version']!r}; expected {CONTRACT_VERSION!r}"
        )

    source = contract["source"]
    if not isinstance(source, dict):
        raise LayoutContractError("source must be an object")
    _exact_keys(source, SOURCE_KEYS, "source")
    columns = source["columns"]
    if not isinstance(columns, list) or not columns:
        raise LayoutContractError("source.columns must be a non-empty list")
    column_names: list[str] = []
    column_types: dict[str, str] = {}
    column_nullable: dict[str, bool] = {}
    for position, column in enumerate(columns):
        label = f"source.columns[{position}]"
        if not isinstance(column, dict):
            raise LayoutContractError(f"{label} must be an object")
        _exact_keys(column, COLUMN_KEYS, label)
        name = column["name"]
        if not isinstance(name, str) or not name:
            raise LayoutContractError(f"{label}.name must be a non-empty string")
        if name in column_names:
            raise LayoutContractError(f"duplicate source column: {name}")
        if not _valid_type_name(column["type"]):
            raise LayoutContractError(f"unsupported source type for {name}: {column['type']!r}")
        if type(column["nullable"]) is not bool:
            raise LayoutContractError(f"{label}.nullable must be boolean")
        column_names.append(name)
        column_types[name] = column["type"]
        column_nullable[name] = column["nullable"]

    grain = source["grain"]
    if (
        not isinstance(grain, list)
        or not grain
        or any(not isinstance(name, str) or not name for name in grain)
        or len(set(grain)) != len(grain)
    ):
        raise LayoutContractError("source.grain must contain unique column names")
    unknown_grain = sorted(set(grain) - set(column_names))
    if unknown_grain:
        raise LayoutContractError(f"source.grain has unknown columns: {unknown_grain}")
    nullable_grain = [name for name in grain if column_nullable[name]]
    if nullable_grain:
        raise LayoutContractError(f"source.grain columns must be non-null: {nullable_grain}")
    if type(source["row_count"]) is not int or source["row_count"] < 0:
        raise LayoutContractError("source.row_count must be a non-negative integer")
    null_counts = source["null_counts"]
    if not isinstance(null_counts, dict) or set(null_counts) != set(column_names):
        raise LayoutContractError("source.null_counts must declare every source column")
    if any(type(value) is not int or value < 0 for value in null_counts.values()):
        raise LayoutContractError("source.null_counts values must be non-negative integers")
    if any(value > source["row_count"] for value in null_counts.values()):
        raise LayoutContractError("source.null_counts cannot exceed source.row_count")

    derived = contract["derived_columns"]
    if not isinstance(derived, list) or not derived:
        raise LayoutContractError("derived_columns must be a non-empty list")
    derived_names: list[str] = []
    for position, rule in enumerate(derived):
        label = f"derived_columns[{position}]"
        if not isinstance(rule, dict):
            raise LayoutContractError(f"{label} must be an object")
        _exact_keys(rule, DERIVED_KEYS, label)
        name = rule["name"]
        source_name = rule["source"]
        transform = rule["transform"]
        if not isinstance(name, str) or not name:
            raise LayoutContractError(f"{label}.name must be a non-empty string")
        if name in column_names or name in derived_names:
            raise LayoutContractError(f"duplicate or colliding derived column: {name}")
        if source_name not in column_names:
            raise LayoutContractError(f"{label}.source is unknown: {source_name!r}")
        if transform not in SUPPORTED_TRANSFORMS:
            raise LayoutContractError(f"{label}.transform is unsupported: {transform!r}")
        if not column_types[source_name].startswith("timestamp["):
            raise LayoutContractError(f"{label}.source must be a timestamp column")
        if "tz=UTC" not in column_types[source_name]:
            raise LayoutContractError(f"{label}.source timestamp must use UTC")
        derived_names.append(name)

    all_names = set(column_names) | set(derived_names)
    string_names = {
        name for name, type_name in column_types.items() if type_name == "string"
    } | set(derived_names)
    candidates = contract["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise LayoutContractError("candidates must be a non-empty list")
    candidate_names: list[str] = []
    candidates_by_name: dict[str, list[str]] = {}
    for position, candidate in enumerate(candidates):
        label = f"candidates[{position}]"
        if not isinstance(candidate, dict):
            raise LayoutContractError(f"{label} must be an object")
        _exact_keys(candidate, CANDIDATE_KEYS, label)
        name = candidate["name"]
        partition_by = candidate["partition_by"]
        if not isinstance(name, str) or not name:
            raise LayoutContractError(f"{label}.name must be a non-empty string")
        if name in candidate_names:
            raise LayoutContractError(f"duplicate candidate name: {name}")
        if (
            not isinstance(partition_by, list)
            or not partition_by
            or any(not isinstance(key, str) or not key for key in partition_by)
            or len(set(partition_by)) != len(partition_by)
        ):
            raise LayoutContractError(f"{label}.partition_by must contain unique names")
        unknown = sorted(set(partition_by) - all_names)
        if unknown:
            raise LayoutContractError(f"{label}.partition_by has unknown columns: {unknown}")
        non_string = sorted(set(partition_by) - string_names)
        if non_string:
            raise LayoutContractError(
                f"{label}.partition_by supports string dimensions only: {non_string}"
            )
        candidate_names.append(name)
        candidates_by_name[name] = partition_by

    selected = contract["selected"]
    if selected not in candidates_by_name:
        raise LayoutContractError(f"selected candidate is unknown: {selected!r}")

    workload = contract["workload"]
    if not isinstance(workload, list) or not workload:
        raise LayoutContractError("workload must be a non-empty list")
    workload_names: list[str] = []
    for position, query in enumerate(workload):
        label = f"workload[{position}]"
        if not isinstance(query, dict):
            raise LayoutContractError(f"{label} must be an object")
        _exact_keys(query, WORKLOAD_KEYS, label)
        name = query["name"]
        filters = query["filters"]
        if not isinstance(name, str) or not name:
            raise LayoutContractError(f"{label}.name must be a non-empty string")
        if name in workload_names:
            raise LayoutContractError(f"duplicate workload name: {name}")
        if not isinstance(filters, dict) or not filters:
            raise LayoutContractError(f"{label}.filters must be a non-empty object")
        unknown = sorted(set(filters) - all_names)
        if unknown:
            raise LayoutContractError(f"{label}.filters has unknown columns: {unknown}")
        if any(
            key not in string_names or not isinstance(value, str) for key, value in filters.items()
        ):
            raise LayoutContractError(f"{label}.filters supports string dimensions only")
        if not set(filters) & set(candidates_by_name[selected]):
            raise LayoutContractError(
                f"selected candidate cannot prune any filter in workload {name!r}"
            )
        workload_names.append(name)

    diagnostics = contract["diagnostics"]
    if not isinstance(diagnostics, dict):
        raise LayoutContractError("diagnostics must be an object")
    _exact_keys(diagnostics, DIAGNOSTIC_KEYS, "diagnostics")
    threshold = diagnostics["small_partition_rows"]
    if type(threshold) is not int or threshold <= 0:
        raise LayoutContractError("small_partition_rows must be a positive integer")
    if diagnostics["allow_null_partition_values"] is not False:
        raise LayoutContractError("contract version 1 requires allow_null_partition_values=false")
    return contract


def load_contract(path: str | Path) -> dict[str, Any]:
    raw = _read_bounded(
        Path(path),
        max_bytes=MAX_CONTRACT_BYTES,
        label="layout contract",
    )
    return _parse_contract(raw)


def _schema_manifest(schema: pa.Schema) -> list[dict[str, Any]]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in schema
    ]


def _null_counts(table: pa.Table) -> dict[str, int]:
    return {name: table.column(name).null_count for name in table.column_names}


def _grain_errors(table: pa.Table, grain: list[str]) -> list[str]:
    seen: dict[tuple[Any, ...], int] = {}
    errors: list[str] = []
    for position, row in enumerate(table.select(grain).to_pylist()):
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
    observed_schema = _schema_manifest(table.schema)
    if observed_schema != expected["columns"]:
        errors.append(f"schema differs: expected {expected['columns']}, got {observed_schema}")
    if table.num_rows != expected["row_count"]:
        errors.append(f"row count differs: expected {expected['row_count']}, got {table.num_rows}")
    observed_nulls = _null_counts(table)
    if observed_nulls != expected["null_counts"]:
        errors.append(
            f"null counts differ: expected {expected['null_counts']}, got {observed_nulls}"
        )
    errors.extend(_grain_errors(table, expected["grain"]))
    if errors:
        raise LayoutContractError("source violates layout contract: " + "; ".join(errors))


def _add_derived_columns(table: pa.Table, rules: list[dict[str, str]]) -> pa.Table:
    result = table
    for rule in rules:
        values = pc.strftime(
            result.column(rule["source"]),
            format=SUPPORTED_TRANSFORMS[rule["transform"]],
        )
        if values.null_count:
            raise LayoutContractError(f"derived partition column contains nulls: {rule['name']}")
        result = result.append_column(rule["name"], values)
    return result


def _canonical_rows(table: pa.Table, grain: list[str]) -> list[dict[str, Any]]:
    indices = pc.sort_indices(table, sort_keys=[(name, "ascending") for name in grain])
    return table.take(indices).to_pylist()


def _partition_rows(table: pa.Table, keys: list[str]) -> list[dict[str, Any]]:
    counts: dict[tuple[str, ...], int] = {}
    for row in table.select(keys).to_pylist():
        values = tuple(row[key] for key in keys)
        if any(value is None for value in values):
            raise LayoutContractError(f"partition columns contain null tuple: {values!r}")
        counts[values] = counts.get(values, 0) + 1
    return [
        {"values": dict(zip(keys, values, strict=True)), "rows": rows}
        for values, rows in sorted(counts.items())
    ]


def _candidate_report(
    table: pa.Table,
    candidate: dict[str, Any],
    workload: list[dict[str, Any]],
    *,
    small_partition_rows: int,
) -> dict[str, Any]:
    keys = candidate["partition_by"]
    partitions = _partition_rows(table, keys)
    row_counts = [partition["rows"] for partition in partitions]
    workload_support = {}
    for query in workload:
        partition_filters = [name for name in query["filters"] if name in keys]
        residual_filters = [name for name in query["filters"] if name not in keys]
        workload_support[query["name"]] = {
            "partition_filters": partition_filters,
            "residual_filters": residual_filters,
            "can_prune_files": bool(partition_filters),
        }
    return {
        "name": candidate["name"],
        "partition_by": keys,
        "partition_count": len(partitions),
        "partition_to_row_ratio": round(len(partitions) / table.num_rows, 6)
        if table.num_rows
        else None,
        "rows_per_partition": {
            "minimum": min(row_counts) if row_counts else None,
            "median": statistics.median(row_counts) if row_counts else None,
            "maximum": max(row_counts) if row_counts else None,
        },
        "small_partition_count": sum(rows < small_partition_rows for rows in row_counts),
        "one_partition_per_row": bool(table.num_rows) and len(partitions) == table.num_rows,
        "partitions": partitions,
        "workload_support": workload_support,
    }


def analyze_candidates(table: pa.Table, contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _candidate_report(
            table,
            candidate,
            contract["workload"],
            small_partition_rows=contract["diagnostics"]["small_partition_rows"],
        )
        for candidate in contract["candidates"]
    ]


def _filter_expression(filters: dict[str, str]):
    expression = None
    for name, value in filters.items():
        condition = ds.field(name) == value
        expression = condition if expression is None else expression & condition
    return expression


def _filter_table(table: pa.Table, filters: dict[str, str]) -> pa.Table:
    mask = None
    for name, value in filters.items():
        condition = pc.equal(table.column(name), pa.scalar(value))
        mask = condition if mask is None else pc.and_kleene(mask, condition)
    return table.filter(mask)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_candidate(
    table: pa.Table,
    data_dir: Path,
    partition_by: list[str],
    workload: list[dict[str, Any]],
    grain: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    partition_schema = pa.schema([table.schema.field(name) for name in partition_by])
    dataset = ds.dataset(
        data_dir,
        format="parquet",
        partitioning=ds.partitioning(partition_schema, flavor="hive"),
    )
    expected_names = table.column_names
    returned = dataset.to_table(columns=expected_names)
    source_names_types = [(field.name, str(field.type)) for field in table.schema]
    returned_names_types = [(field.name, str(field.type)) for field in returned.schema]
    checks = {
        "row_count_preserved": table.num_rows == returned.num_rows,
        "names_and_types_preserved": source_names_types == returned_names_types,
        "values_preserved": _canonical_rows(table, grain) == _canonical_rows(returned, grain),
        "null_counts_preserved": _null_counts(table) == _null_counts(returned),
        "grain_preserved": not _grain_errors(returned, grain),
    }
    all_fragments = list(dataset.get_fragments())

    def package_path(fragment_path: str) -> str:
        path = Path(fragment_path)
        if path.is_absolute():
            path = path.relative_to(data_dir)
        return str(Path("data") / path)

    workload_report: dict[str, Any] = {}
    for query in workload:
        expression = _filter_expression(query["filters"])
        expected = _filter_table(table, query["filters"])
        observed = dataset.to_table(filter=expression, columns=expected_names)
        fragments = list(dataset.get_fragments(filter=expression))
        semantic_match = _canonical_rows(expected, grain) == _canonical_rows(observed, grain)
        workload_report[query["name"]] = {
            "filters": query["filters"],
            "expected_rows": expected.num_rows,
            "returned_rows": observed.num_rows,
            "total_fragments": len(all_fragments),
            "selected_fragments": len(fragments),
            "fragment_reduction_observed": len(fragments) < len(all_fragments),
            "selected_paths": sorted(package_path(fragment.path) for fragment in fragments),
            "semantic_match": semantic_match,
        }
    checks["workload_results_preserved"] = all(
        observation["semantic_match"] for observation in workload_report.values()
    )
    return checks, workload_report


def _write_manifest(path: Path, report: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_dataset(
    input_path: str | Path,
    contract_path: str | Path,
    output_dir: str | Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> dict[str, Any]:
    source_path = Path(input_path)
    contract_file = Path(contract_path)
    output = Path(output_dir)
    if output.exists():
        raise LayoutContractError(f"output directory already exists: {output}")
    source_raw = _read_bounded(source_path, max_bytes=max_bytes, label="input Parquet")
    contract_raw = _read_bounded(
        contract_file,
        max_bytes=MAX_CONTRACT_BYTES,
        label="layout contract",
    )
    contract = _parse_contract(contract_raw)
    try:
        source = pq.read_table(pa.BufferReader(source_raw))
    except pa.ArrowException as error:
        raise LayoutContractError(f"cannot decode input Parquet: {error}") from error
    _validate_source(source, contract)
    table = _add_derived_columns(source, contract["derived_columns"])
    candidates = analyze_candidates(table, contract)
    selected = next(item for item in candidates if item["name"] == contract["selected"])
    warnings: list[str] = []
    if selected["small_partition_count"]:
        warnings.append(
            "selected layout has partitions below the educational row-count diagnostic; "
            "validate file-size targets on representative production volume"
        )
    if selected["one_partition_per_row"]:
        warnings.append("selected layout creates one partition per source row")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.",
            suffix=".staging",
            dir=output.parent,
        )
    )
    data_dir = staging / "data"
    partition_by = selected["partition_by"]
    partition_schema = pa.schema([table.schema.field(name) for name in partition_by])
    try:
        ds.write_dataset(
            table,
            data_dir,
            format="parquet",
            partitioning=ds.partitioning(partition_schema, flavor="hive"),
            basename_template="part-{i}.parquet",
            existing_data_behavior="error",
        )
        checks, workload_report = _verify_candidate(
            table,
            data_dir,
            partition_by,
            contract["workload"],
            contract["source"]["grain"],
        )
        files = sorted(data_dir.rglob("*.parquet"))
        checks["files_created"] = bool(files)
        artifacts = {
            str(path.relative_to(staging)): {
                "bytes": path.stat().st_size,
                "rows": pq.ParquetFile(path).metadata.num_rows,
                "sha256": _file_sha256(path),
            }
            for path in files
        }
        report = {
            "manifest_version": MANIFEST_VERSION,
            "source": {
                "name": source_path.name,
                "bytes": len(source_raw),
                "sha256": _sha256(source_raw),
                "rows": source.num_rows,
                "schema": _schema_manifest(source.schema),
                "null_counts": _null_counts(source),
            },
            "contract": {
                "name": contract_file.name,
                "bytes": len(contract_raw),
                "sha256": _sha256(contract_raw),
                "value": contract,
            },
            "libraries": {"pyarrow": pa.__version__},
            "decision": {
                "selected": contract["selected"],
                "partition_by": partition_by,
                "candidates": candidates,
                "warnings": warnings,
                "diagnostic_scope": (
                    "row-count distribution on this input; not a production file-size target"
                ),
            },
            "workload": workload_report,
            "package": {
                "name": output.name,
                "files": artifacts,
            },
            "checks": checks,
            "summary": {
                "valid": all(checks.values()),
                "rows": table.num_rows,
                "file_count": len(files),
                "partition_count": selected["partition_count"],
                "warning_count": len(warnings),
            },
        }
        if not report["summary"]["valid"]:
            failed = [name for name, passed in checks.items() if not passed]
            raise DatasetBuildError(f"candidate verification failed: {failed}")
        _write_manifest(staging / "manifest.json", report)
        if output.exists():
            raise LayoutContractError(f"output directory appeared during build: {output}")
        os.replace(staging, output)
        return report
    except (LayoutContractError, DatasetBuildError):
        raise
    except (OSError, pa.ArrowException) as error:
        raise DatasetBuildError(f"dataset build failed: {error}") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _positive_cli_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build and verify one workload-declared Hive-partitioned dataset"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-bytes", type=_positive_cli_int, default=DEFAULT_MAX_BYTES)
    args = parser.parse_args()
    resolved = {
        args.input.resolve(strict=False),
        args.contract.resolve(strict=False),
        args.output_dir.resolve(strict=False),
    }
    if len(resolved) != 3:
        parser.error("input, contract and output paths must be distinct")
    try:
        report = build_dataset(
            args.input,
            args.contract,
            args.output_dir,
            max_bytes=args.max_bytes,
        )
    except LayoutContractError as error:
        print(
            json.dumps({"kind": "contract", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(2) from error
    except DatasetBuildError as error:
        print(
            json.dumps({"kind": "build", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(1) from error
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
