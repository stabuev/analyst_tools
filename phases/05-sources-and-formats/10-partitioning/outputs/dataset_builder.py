from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq


class DatasetLayoutError(ValueError):
    """Raised when a partitioned dataset layout cannot be built."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_derived_columns(table: pa.Table) -> pa.Table:
    if "ordered_at" not in table.column_names:
        raise DatasetLayoutError("input table must contain ordered_at")
    months = pc.strftime(table["ordered_at"], format="%Y-%m")
    dates = pc.strftime(table["ordered_at"], format="%Y-%m-%d")
    return table.append_column("order_month", months).append_column("order_date", dates)


def file_rows(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


def build_dataset(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    partition_by: tuple[str, ...] = ("order_month", "currency"),
    filter_currency: str = "EUR",
    small_file_rows: int = 2,
) -> dict[str, Any]:
    source = Path(input_path)
    output = Path(output_dir)
    if not source.is_file():
        raise DatasetLayoutError(f"input Parquet does not exist: {source}")
    if output.exists():
        raise DatasetLayoutError(f"output directory already exists: {output}")
    table = add_derived_columns(pq.read_table(source))
    missing = [name for name in partition_by if name not in table.column_names]
    if missing:
        raise DatasetLayoutError(f"unknown partition columns: {missing}")
    if not partition_by:
        raise DatasetLayoutError("partition_by must not be empty")

    partition_schema = pa.schema([table.schema.field(name) for name in partition_by])
    staging = output.with_name(f".{output.name}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        ds.write_dataset(
            table,
            staging,
            format="parquet",
            partitioning=ds.partitioning(partition_schema, flavor="hive"),
            basename_template="part-{i}.parquet",
            existing_data_behavior="error",
        )
        staging.rename(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    files = sorted(output.rglob("*.parquet"))
    dataset = ds.dataset(output, format="parquet", partitioning="hive")
    all_fragments = list(dataset.get_fragments())
    selected_fragments = list(dataset.get_fragments(filter=ds.field("currency") == filter_currency))
    rows_by_file = {str(path.relative_to(output)): file_rows(path) for path in files}
    daily_partitions = len(set(table["order_date"].to_pylist()))
    chosen_partitions = len(
        set(zip(*(table[name].to_pylist() for name in partition_by), strict=True))
    )
    pattern = str(output / "**" / "*.parquet")
    duckdb_rows = duckdb.sql(
        "SELECT count(*) FROM read_parquet(?, hive_partitioning=true)",
        params=[pattern],
    ).fetchone()[0]
    checks = {
        "all_rows_readable": duckdb_rows == table.num_rows,
        "partition_count_reduces_daily_layout": chosen_partitions < daily_partitions,
        "filter_prunes_fragments": len(selected_fragments) < len(all_fragments),
    }
    return {
        "source": {"path": str(source), "rows": table.num_rows, "sha256": sha256(source)},
        "layout": {
            "partition_by": list(partition_by),
            "chosen_partitions": chosen_partitions,
            "daily_candidate_partitions": daily_partitions,
            "files": rows_by_file,
            "small_files": [name for name, rows in rows_by_file.items() if rows < small_file_rows],
        },
        "pruning": {
            "filter": {"currency": filter_currency},
            "all_fragments": len(all_fragments),
            "selected_fragments": len(selected_fragments),
            "selected_paths": [fragment.path for fragment in selected_fragments],
        },
        "artifacts": {
            str(path.relative_to(output)): {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        },
        "checks": checks,
        "summary": {
            "valid": all(checks.values()),
            "rows": table.num_rows,
            "file_count": len(files),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a partitioned Parquet dataset")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--partition-by",
        nargs="+",
        default=["order_month", "currency"],
    )
    parser.add_argument("--filter-currency", default="EUR")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    try:
        report = build_dataset(
            args.input,
            args.output_dir,
            partition_by=tuple(args.partition_by),
            filter_currency=args.filter_currency,
        )
    except DatasetLayoutError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    content = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(content, encoding="utf-8")
    sys.stdout.write(content)
    if not report["summary"]["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
