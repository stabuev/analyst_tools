from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq


class PushdownAuditError(ValueError):
    """Raised when the Parquet pushdown audit cannot produce a valid report."""


PARTITION_COLUMN = "week_start"
ROW_GROUP_STAT_COLUMN = "week_index"
DEFAULT_REQUIRED_COLUMNS = [
    "week_start",
    "week_index",
    "platform",
    "paid_orders",
    "net_revenue_cents",
]
WIDE_COLUMNS = ["raw_event_json", "debug_payload", "support_notes"]


def generate_revenue_rows(rows: int, seed: int) -> pd.DataFrame:
    if rows <= 0:
        raise PushdownAuditError("rows must be positive")

    rng = np.random.default_rng(seed)
    index = np.arange(rows, dtype=np.int64)
    week_count = 8
    week_index = index % week_count
    base_week = pd.Timestamp("2026-01-05")
    week_start = [
        (base_week + pd.Timedelta(days=int(position) * 7)).date().isoformat()
        for position in week_index
    ]

    platforms = np.array(["web", "ios", "android"], dtype=object)
    regions = np.array(["ru", "kz", "am", "tr"], dtype=object)
    plans = np.array(["trial", "basic", "plus", "pro"], dtype=object)
    paid_orders = rng.binomial(1, 0.72, size=rows).astype(np.int64)
    unit_price = rng.integers(399, 45_000, size=rows, dtype=np.int64)
    quantity = rng.integers(1, 5, size=rows, dtype=np.int64)
    gross = unit_price * quantity * paid_orders
    refunds = np.where(
        rng.random(rows) < 0.07,
        np.rint(gross * rng.uniform(0.1, 0.9, size=rows)).astype(np.int64),
        0,
    )
    net = gross - refunds
    payload_ids = rng.integers(100_000, 999_999, size=rows)

    frame = pd.DataFrame(
        {
            "order_id": [f"O{position // 3:08d}" for position in index],
            "line_number": (index % 3 + 1).astype(np.int64),
            "user_id": [
                f"U{int(value):07d}"
                for value in rng.integers(1, max(2, rows // 2), size=rows)
            ],
            "week_start": week_start,
            "week_index": week_index.astype(np.int16),
            "platform": platforms[index % len(platforms)],
            "region": regions[rng.integers(0, len(regions), size=rows)],
            "plan": plans[rng.integers(0, len(plans), size=rows)],
            "paid_orders": paid_orders,
            "gross_revenue_cents": gross.astype(np.int64),
            "refund_amount_cents": refunds.astype(np.int64),
            "net_revenue_cents": net.astype(np.int64),
            "active_subscription_days": rng.integers(0, 8, size=rows, dtype=np.int64),
            "support_ticket_count": rng.poisson(0.18, size=rows).astype(np.int64),
            "raw_event_json": [
                (
                    '{"source":"lesson","event_id":'
                    f'"evt-{int(value)}","attributes":"wide-column-for-projection"}}'
                )
                for value in payload_ids
            ],
            "debug_payload": [
                "trace=" + str(int(value)) + ";stage=checkout;experiment=pushdown-audit"
                for value in payload_ids
            ],
            "support_notes": [
                "no ticket" if value == 0 else f"ticket bucket {int(value % 5)}"
                for value in rng.poisson(0.12, size=rows)
            ],
        }
    )
    return frame.sort_values(["week_index", "order_id", "line_number"]).reset_index(drop=True)


def _available_week_indices(frame: pd.DataFrame) -> dict[str, int]:
    pairs = frame[[PARTITION_COLUMN, ROW_GROUP_STAT_COLUMN]].drop_duplicates()
    return {str(row[PARTITION_COLUMN]): int(row[ROW_GROUP_STAT_COLUMN]) for _, row in pairs.iterrows()}


def _validate_required_columns(frame: pd.DataFrame, required_columns: list[str]) -> None:
    missing = sorted(set(required_columns) - set(frame.columns))
    if missing:
        raise PushdownAuditError(f"required columns are missing: {missing}")


def write_parquet_layout(frame: pd.DataFrame, output_dir: Path, row_group_size: int) -> Path:
    if row_group_size <= 0:
        raise PushdownAuditError("row_group_size must be positive")

    dataset_dir = output_dir / "dataset"
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pq.write_to_dataset(
        table,
        root_path=str(dataset_dir),
        partition_cols=[PARTITION_COLUMN],
        row_group_size=row_group_size,
        compression="zstd",
        use_dictionary=True,
        write_statistics=True,
    )
    return dataset_dir


def parquet_files(dataset_dir: Path) -> list[Path]:
    files = sorted(dataset_dir.rglob("*.parquet"))
    if not files:
        raise PushdownAuditError(f"no parquet files found in {dataset_dir}")
    return files


def _partition_value(path: Path) -> str | None:
    for part in path.parts:
        prefix = f"{PARTITION_COLUMN}="
        if part.startswith(prefix):
            return part[len(prefix) :]
    return None


def inspect_layout(
    dataset_dir: Path,
    *,
    target_week: str,
    target_week_index: int,
    required_columns: list[str],
    row_group_size: int,
) -> dict[str, Any]:
    files = parquet_files(dataset_dir)
    partitions: dict[str, int] = {}
    total_row_groups = 0
    candidate_row_groups = 0
    row_group_examples: list[dict[str, Any]] = []
    stats_missing = 0
    physical_columns = pq.ParquetFile(files[0]).schema_arrow.names
    physical_required = [
        column
        for column in required_columns
        if column != PARTITION_COLUMN and column in physical_columns
    ]

    for file_path in files:
        partition = _partition_value(file_path)
        if partition is not None:
            partitions[partition] = partitions.get(partition, 0) + 1

        parquet_file = pq.ParquetFile(file_path)
        metadata = parquet_file.metadata
        total_row_groups += metadata.num_row_groups
        schema_names = list(metadata.schema.names)
        if ROW_GROUP_STAT_COLUMN not in schema_names:
            stats_missing += metadata.num_row_groups
            continue
        column_index = schema_names.index(ROW_GROUP_STAT_COLUMN)
        for row_group_index in range(metadata.num_row_groups):
            row_group = metadata.row_group(row_group_index)
            column = row_group.column(column_index)
            stats = column.statistics
            if stats is None or not stats.has_min_max:
                stats_missing += 1
                continue
            minimum = int(stats.min)
            maximum = int(stats.max)
            is_candidate = minimum <= target_week_index <= maximum
            candidate_row_groups += int(is_candidate)
            if len(row_group_examples) < 8:
                row_group_examples.append(
                    {
                        "file": str(file_path.relative_to(dataset_dir)),
                        "row_group": row_group_index,
                        "rows": int(row_group.num_rows),
                        "week_index_min": minimum,
                        "week_index_max": maximum,
                        "candidate_for_target": bool(is_candidate),
                    }
                )

    candidate_files = [
        str(file_path.relative_to(dataset_dir))
        for file_path in files
        if _partition_value(file_path) == target_week
    ]
    omitted_physical_columns = [
        column
        for column in physical_columns
        if column not in physical_required
    ]

    return {
        "dataset_dir": str(dataset_dir),
        "format": "parquet",
        "compression": "zstd",
        "partition_columns": [PARTITION_COLUMN],
        "row_group_stat_column": ROW_GROUP_STAT_COLUMN,
        "configured_row_group_size": int(row_group_size),
        "file_count": len(files),
        "row_group_count": int(total_row_groups),
        "partitions": dict(sorted(partitions.items())),
        "physical_columns": physical_columns,
        "physical_required_columns": physical_required,
        "omitted_physical_columns": omitted_physical_columns,
        "partition_pruning": {
            "target_week": target_week,
            "candidate_file_count": len(candidate_files),
            "pruned_file_count": len(files) - len(candidate_files),
            "candidate_files": candidate_files,
            "passed": 0 < len(candidate_files) < len(files),
        },
        "row_group_statistics": {
            "target_week_index": int(target_week_index),
            "candidate_row_group_count": int(candidate_row_groups),
            "skipped_row_group_count": int(total_row_groups - candidate_row_groups),
            "missing_statistics_count": int(stats_missing),
            "examples": row_group_examples,
            "passed": (
                stats_missing == 0
                and 0 < candidate_row_groups < total_row_groups
            ),
        },
    }


def _scan_arrow(
    dataset: ds.Dataset,
    *,
    columns: list[str] | None = None,
    filter_expression: ds.Expression | None = None,
) -> tuple[pa.Table, float]:
    started = time.perf_counter()
    table = dataset.to_table(columns=columns, filter=filter_expression)
    elapsed = time.perf_counter() - started
    return table, elapsed


def arrow_scan_measurements(
    dataset_dir: Path,
    *,
    target_week: str,
    target_week_index: int,
    required_columns: list[str],
) -> dict[str, Any]:
    dataset = ds.dataset(dataset_dir, format="parquet", partitioning="hive")
    filter_expression = (
        (ds.field(PARTITION_COLUMN) == target_week)
        & (ds.field(ROW_GROUP_STAT_COLUMN) == target_week_index)
    )
    full_table, full_seconds = _scan_arrow(dataset)
    pushed_table, pushed_seconds = _scan_arrow(
        dataset,
        columns=required_columns,
        filter_expression=filter_expression,
    )

    measurements = [
        {
            "name": "full_arrow_scan",
            "rows": int(full_table.num_rows),
            "columns": int(full_table.num_columns),
            "output_bytes": int(full_table.nbytes),
            "wall_seconds": float(full_seconds),
        },
        {
            "name": "projected_filtered_arrow_scan",
            "rows": int(pushed_table.num_rows),
            "columns": int(pushed_table.num_columns),
            "output_bytes": int(pushed_table.nbytes),
            "wall_seconds": float(pushed_seconds),
        },
    ]
    return {
        "measurements": measurements,
        "projection": {
            "required_columns": required_columns,
            "full_column_count": int(full_table.num_columns),
            "projected_column_count": int(pushed_table.num_columns),
            "full_scan_output_bytes": int(full_table.nbytes),
            "pushed_scan_output_bytes": int(pushed_table.nbytes),
            "passed": (
                pushed_table.num_columns == len(required_columns)
                and pushed_table.num_columns < full_table.num_columns
                and pushed_table.nbytes < full_table.nbytes
            ),
        },
        "predicate": {
            "full_rows": int(full_table.num_rows),
            "pushed_rows": int(pushed_table.num_rows),
            "passed": 0 < pushed_table.num_rows < full_table.num_rows,
        },
    }


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def duckdb_query_and_plan(
    dataset_dir: Path,
    *,
    target_week: str,
    target_week_index: int,
) -> dict[str, Any]:
    glob = str(dataset_dir / "**" / "*.parquet")
    escaped_glob = _sql_literal(glob)
    escaped_week = _sql_literal(target_week)
    query = f"""
SELECT
  platform,
  CAST(sum(net_revenue_cents) AS BIGINT) AS net_revenue_cents,
  CAST(sum(paid_orders) AS BIGINT) AS paid_orders
FROM read_parquet('{escaped_glob}', hive_partitioning = true)
WHERE week_start = DATE '{escaped_week}'
  AND week_index = {int(target_week_index)}
GROUP BY platform
ORDER BY platform
""".strip()

    with duckdb.connect(database=":memory:") as connection:
        plan_rows = connection.execute("EXPLAIN " + query).fetchall()
        plan_text = "\n".join(str(row[-1]) for row in plan_rows)
        result_rows = connection.execute(query).fetchall()

    rows = [
        {
            "platform": str(platform_name),
            "net_revenue_cents": int(net_revenue_cents),
            "paid_orders": int(paid_orders),
        }
        for platform_name, net_revenue_cents, paid_orders in result_rows
    ]
    upper_plan = plan_text.upper()
    return {
        "query": query,
        "plan_text": plan_text,
        "rows": rows,
        "checks": {
            "parquet_scan_present": "PARQUET" in upper_plan,
            "partition_filter_visible": "WEEK_START" in upper_plan,
            "row_group_filter_visible": "WEEK_INDEX" in upper_plan,
            "projection_columns_visible": all(
                column.upper() in upper_plan
                for column in ["PLATFORM", "NET_REVENUE_CENTS", "PAID_ORDERS"]
            ),
        },
    }


def pandas_control(frame: pd.DataFrame, *, target_week: str, target_week_index: int) -> list[dict[str, Any]]:
    filtered = frame[
        (frame[PARTITION_COLUMN] == target_week)
        & (frame[ROW_GROUP_STAT_COLUMN] == target_week_index)
    ]
    grouped = (
        filtered.groupby("platform", as_index=False)[["net_revenue_cents", "paid_orders"]]
        .sum()
        .sort_values("platform")
        .reset_index(drop=True)
    )
    return [
        {
            "platform": str(row["platform"]),
            "net_revenue_cents": int(row["net_revenue_cents"]),
            "paid_orders": int(row["paid_orders"]),
        }
        for _, row in grouped.iterrows()
    ]


def build_pushdown_audit(
    *,
    rows: int = 4_800,
    seed: int = 42,
    row_group_size: int = 128,
    target_week: str = "2026-02-02",
    output_dir: str | Path,
    required_columns: list[str] | None = None,
) -> dict[str, Any]:
    required = list(required_columns or DEFAULT_REQUIRED_COLUMNS)
    frame = generate_revenue_rows(rows=rows, seed=seed)
    _validate_required_columns(frame, required)
    week_indices = _available_week_indices(frame)
    if target_week not in week_indices:
        raise PushdownAuditError(
            f"target_week {target_week!r} is absent; available weeks: {sorted(week_indices)}"
        )
    target_week_index = week_indices[target_week]

    output_path = Path(output_dir)
    dataset_dir = write_parquet_layout(frame, output_path, row_group_size=row_group_size)
    layout = inspect_layout(
        dataset_dir,
        target_week=target_week,
        target_week_index=target_week_index,
        required_columns=required,
        row_group_size=row_group_size,
    )
    arrow_report = arrow_scan_measurements(
        dataset_dir,
        target_week=target_week,
        target_week_index=target_week_index,
        required_columns=required,
    )
    duckdb_report = duckdb_query_and_plan(
        dataset_dir,
        target_week=target_week,
        target_week_index=target_week_index,
    )
    control_rows = pandas_control(frame, target_week=target_week, target_week_index=target_week_index)
    result_passed = duckdb_report["rows"] == control_rows
    plan_checks = duckdb_report["checks"]

    findings = [
        (
            f"Projection reads {len(required)} logical columns and omits "
            f"{len(layout['omitted_physical_columns'])} physical Parquet columns."
        ),
        (
            f"Partition pruning keeps {layout['partition_pruning']['candidate_file_count']} of "
            f"{layout['file_count']} files for week_start={target_week}."
        ),
        (
            f"Row-group statistics keep {layout['row_group_statistics']['candidate_row_group_count']} "
            f"of {layout['row_group_count']} row groups for week_index={target_week_index}."
        ),
    ]
    core_checks = [
        bool(arrow_report["projection"]["passed"]),
        bool(arrow_report["predicate"]["passed"]),
        bool(layout["partition_pruning"]["passed"]),
        bool(layout["row_group_statistics"]["passed"]),
        bool(result_passed),
        bool(plan_checks["parquet_scan_present"]),
        bool(plan_checks["row_group_filter_visible"]),
    ]

    report: dict[str, Any] = {
        "scenario": {
            "scenario_id": "parquet-pushdown-audit",
            "rows": int(rows),
            "seed": int(seed),
            "target_week": target_week,
            "target_week_index": int(target_week_index),
            "required_columns": required,
            "partition_columns": [PARTITION_COLUMN],
            "row_group_size": int(row_group_size),
            "engine_versions": {
                "python": platform.python_version(),
                "pandas": pd.__version__,
                "numpy": np.__version__,
                "pyarrow": pa.__version__,
                "duckdb": duckdb.__version__,
            },
        },
        "layout": layout,
        "projection": arrow_report["projection"],
        "predicate_pushdown": {
            "arrow_filter": f"{PARTITION_COLUMN} = {target_week} AND {ROW_GROUP_STAT_COLUMN} = {target_week_index}",
            "arrow_predicate": arrow_report["predicate"],
            "partition_pruning": layout["partition_pruning"],
            "row_group_statistics": layout["row_group_statistics"],
        },
        "measurements": arrow_report["measurements"],
        "duckdb_plan": duckdb_report,
        "result_contract": {
            "grain": "platform for one week_start/week_index",
            "duckdb_rows": duckdb_report["rows"],
            "pandas_rows": control_rows,
            "passed": bool(result_passed),
        },
        "findings": findings,
        "interpretation": {
            "safe_to_ship": all(core_checks),
            "notes": [
                "The benchmark compares scan shapes, not a statistically stable speedup claim.",
                "Ship only when projection, predicate pruning, query plan and control totals agree.",
            ],
        },
    }
    return report


def write_audit_package(report: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    layout_subset = {
        "scenario": report["scenario"],
        "layout": report["layout"],
        "projection": report["projection"],
        "predicate_pushdown": report["predicate_pushdown"],
    }
    (output_dir / "parquet-layout.json").write_text(
        json.dumps(layout_subset, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "query-plan.txt").write_text(
        report["duckdb_plan"]["plan_text"],
        encoding="utf-8",
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Parquet projection/predicate pushdown audit")
    parser.add_argument("--rows", type=int, default=4_800)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--row-group-size", type=int, default=128)
    parser.add_argument("--target-week", default="2026-02-02")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for dataset/, report.json, parquet-layout.json and query-plan.txt",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.output_dir is None:
            with tempfile.TemporaryDirectory() as tmp:
                report = build_pushdown_audit(
                    rows=args.rows,
                    seed=args.seed,
                    row_group_size=args.row_group_size,
                    target_week=args.target_week,
                    output_dir=tmp,
                )
                print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            report = build_pushdown_audit(
                rows=args.rows,
                seed=args.seed,
                row_group_size=args.row_group_size,
                target_week=args.target_week,
                output_dir=args.output_dir,
            )
            write_audit_package(report, args.output_dir)
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except PushdownAuditError as error:
        print(f"pushdown audit error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
