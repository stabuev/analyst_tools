from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq


class StreamingBatchError(ValueError):
    """Raised when the streaming batch package cannot be built safely."""


class SimulatedBatchInterruption(RuntimeError):
    """Raised after a durable checkpoint to exercise resume behavior."""


REQUIRED_COLUMNS = [
    "order_id",
    "user_id",
    "week_index",
    "week_start",
    "platform",
    "region",
    "status",
    "gross_revenue_cents",
    "refund_amount_cents",
    "support_ticket_count",
    "is_test_user",
]

GROUP_COLUMNS = ["week_start", "platform", "region"]

ADDITIVE_COLUMNS = [
    "orders",
    "paid_orders",
    "gross_revenue_cents",
    "refund_amount_cents",
    "net_revenue_cents",
    "support_ticket_count",
]

OUTPUT_COLUMNS = [
    *GROUP_COLUMNS,
    *ADDITIVE_COLUMNS,
    "revenue_per_paid_order_cents",
    "refund_rate_bp",
]

CHECKPOINT_VERSION = 1


def generate_order_batches(
    output_dir: str | Path,
    *,
    rows: int = 4_800,
    batch_size: int = 600,
    users: int = 640,
    seed: int = 42,
) -> list[Path]:
    if rows < 120:
        raise StreamingBatchError("rows must be at least 120")
    if batch_size < 20:
        raise StreamingBatchError("batch_size must be at least 20")
    if users < 16 or users > rows:
        raise StreamingBatchError("users must be between 16 and rows")

    data_dir = Path(output_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    for old_path in data_dir.glob("batch-*.parquet"):
        old_path.unlink()

    rng = np.random.default_rng(seed)
    index = np.arange(rows, dtype=np.int64)
    user_ids = np.array([f"U{position:07d}" for position in range(users)], dtype=object)
    platforms = np.array(["web", "ios", "android"], dtype=object)
    regions = np.array(["ru", "kz", "am", "tr"], dtype=object)
    statuses = np.array(["paid", "paid", "paid", "trial", "refunded"], dtype=object)
    week_index = (index % 6).astype(np.int16)
    base_week = pd.Timestamp("2026-01-05")
    status = statuses[rng.integers(0, len(statuses), size=rows)]
    gross = rng.integers(399, 70_000, size=rows, dtype=np.int64)
    gross = np.where(status == "trial", 0, gross)
    refund = np.where(
        status == "refunded",
        np.rint(gross * rng.uniform(0.2, 1.0, size=rows)).astype(np.int64),
        0,
    )
    frame = pd.DataFrame(
        {
            "order_id": [f"O{position:010d}" for position in index],
            "user_id": user_ids[rng.integers(0, users, size=rows)],
            "week_index": week_index,
            "week_start": [
                (base_week + pd.Timedelta(days=int(value) * 7)).date().isoformat()
                for value in week_index
            ],
            "platform": platforms[(index * 13) % len(platforms)],
            "region": regions[(index * 17) % len(regions)],
            "status": status,
            "gross_revenue_cents": gross.astype(np.int64),
            "refund_amount_cents": refund.astype(np.int64),
            "support_ticket_count": rng.poisson(0.18, size=rows).astype(np.int64),
            "is_test_user": index % 113 == 0,
        }
    )

    paths: list[Path] = []
    for batch_number, start in enumerate(range(0, rows, batch_size)):
        batch = frame.iloc[start : start + batch_size].reset_index(drop=True)
        path = data_dir / f"batch-{batch_number:04d}.parquet"
        pq.write_table(
            pa.Table.from_pandas(batch, preserve_index=False),
            path,
            compression="zstd",
            use_dictionary=True,
            write_statistics=True,
        )
        paths.append(path)
    return paths


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_input_manifest(input_dir: str | Path) -> dict[str, Any]:
    paths = sorted(Path(input_dir).glob("batch-*.parquet"))
    if not paths:
        raise StreamingBatchError("input directory has no batch-*.parquet files")
    files = [
        {
            "name": path.name,
            "size_bytes": path.stat().st_size,
            "rows": pq.ParquetFile(path).metadata.num_rows,
            "sha256": _sha256(path),
        }
        for path in paths
    ]
    manifest_payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {
        "version": 1,
        "files": files,
        "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
        "total_rows": sum(int(item["rows"]) for item in files),
    }


def validate_batch(frame: pd.DataFrame) -> None:
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise StreamingBatchError(f"required columns are missing: {missing}")
    if frame.empty:
        raise StreamingBatchError("batch is empty")
    if frame["order_id"].isna().any() or frame["order_id"].duplicated().any():
        raise StreamingBatchError("order_id must be non-null and unique inside a batch")
    for column in [
        "gross_revenue_cents",
        "refund_amount_cents",
        "support_ticket_count",
    ]:
        if (frame[column] < 0).any():
            raise StreamingBatchError(f"{column} must be non-negative")
    if (frame["refund_amount_cents"] > frame["gross_revenue_cents"]).any():
        raise StreamingBatchError("refund_amount_cents cannot exceed gross_revenue_cents")


def prepare_batch(frame: pd.DataFrame) -> pd.DataFrame:
    validate_batch(frame)
    prepared = frame.loc[
        frame["week_index"].between(1, 4) & (frame["region"] != "tr") & ~frame["is_test_user"],
        REQUIRED_COLUMNS,
    ].copy()
    prepared["paid_order"] = (
        (prepared["status"] == "paid") & (prepared["gross_revenue_cents"] > 0)
    ).astype("int64")
    prepared["net_revenue_cents"] = (
        prepared["gross_revenue_cents"] - prepared["refund_amount_cents"]
    )
    return prepared


def aggregate_batch(frame: pd.DataFrame) -> list[dict[str, Any]]:
    prepared = prepare_batch(frame)
    if prepared.empty:
        return []
    grouped = prepared.groupby(GROUP_COLUMNS, as_index=False, dropna=False).agg(
        orders=("order_id", "count"),
        paid_orders=("paid_order", "sum"),
        gross_revenue_cents=("gross_revenue_cents", "sum"),
        refund_amount_cents=("refund_amount_cents", "sum"),
        net_revenue_cents=("net_revenue_cents", "sum"),
        support_ticket_count=("support_ticket_count", "sum"),
    )
    return json.loads(grouped.to_json(orient="records"))


def _empty_state() -> dict[tuple[str, str, str], dict[str, int]]:
    return {}


def merge_partial_groups(
    state: dict[tuple[str, str, str], dict[str, int]],
    partial_groups: list[dict[str, Any]],
) -> None:
    for row in partial_groups:
        key = tuple(str(row[column]) for column in GROUP_COLUMNS)
        current = state.setdefault(key, {column: 0 for column in ADDITIVE_COLUMNS})
        for column in ADDITIVE_COLUMNS:
            current[column] += int(row[column])


def _state_records(
    state: dict[tuple[str, str, str], dict[str, int]],
) -> list[dict[str, Any]]:
    return [
        {
            **dict(zip(GROUP_COLUMNS, key, strict=True)),
            **values,
        }
        for key, values in sorted(state.items())
    ]


def _state_from_records(
    records: list[dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, int]]:
    state = _empty_state()
    for row in records:
        key = tuple(str(row[column]) for column in GROUP_COLUMNS)
        state[key] = {column: int(row[column]) for column in ADDITIVE_COLUMNS}
    return state


def finalize_state(
    state: dict[tuple[str, str, str], dict[str, int]],
) -> pd.DataFrame:
    frame = pd.DataFrame(_state_records(state))
    if frame.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    frame["revenue_per_paid_order_cents"] = frame["net_revenue_cents"] // frame[
        "paid_orders"
    ].replace(0, pd.NA)
    frame["refund_rate_bp"] = np.where(
        frame["gross_revenue_cents"] > 0,
        np.rint(frame["refund_amount_cents"] * 10_000 / frame["gross_revenue_cents"]),
        pd.NA,
    )
    return normalize_output(frame)


def normalize_output(frame: pd.DataFrame | pl.DataFrame) -> pd.DataFrame:
    normalized = frame.to_pandas() if isinstance(frame, pl.DataFrame) else frame.copy()
    normalized = normalized[OUTPUT_COLUMNS].copy()
    for column in GROUP_COLUMNS:
        normalized[column] = normalized[column].astype("string")
    for column in ADDITIVE_COLUMNS + [
        "revenue_per_paid_order_cents",
        "refund_rate_bp",
    ]:
        normalized[column] = pd.to_numeric(normalized[column]).astype("Int64")
    return normalized.sort_values(GROUP_COLUMNS, kind="mergesort").reset_index(drop=True)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _new_checkpoint(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": CHECKPOINT_VERSION,
        "manifest_sha256": manifest["manifest_sha256"],
        "completed_files": [],
        "rows_processed": 0,
        "eligible_rows": 0,
        "partial_groups": [],
    }


def load_checkpoint(
    checkpoint_path: str | Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    path = Path(checkpoint_path)
    if not path.exists():
        return _new_checkpoint(manifest)
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    if checkpoint.get("version") != CHECKPOINT_VERSION:
        raise StreamingBatchError("checkpoint version is not supported")
    if checkpoint.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise StreamingBatchError(
            "input manifest changed after checkpoint; start a new output directory"
        )
    manifest_names = {item["name"] for item in manifest["files"]}
    completed = checkpoint.get("completed_files")
    if not isinstance(completed, list) or not set(completed).issubset(manifest_names):
        raise StreamingBatchError("checkpoint completed_files are invalid")
    if not isinstance(checkpoint.get("partial_groups"), list):
        raise StreamingBatchError("checkpoint partial_groups must be a list")
    return checkpoint


def process_batches(
    input_dir: str | Path,
    checkpoint_path: str | Path,
    output_path: str | Path,
    *,
    stop_after_files: int | None = None,
) -> dict[str, Any]:
    if stop_after_files is not None and stop_after_files <= 0:
        raise StreamingBatchError("stop_after_files must be positive")

    input_root = Path(input_dir)
    manifest = build_input_manifest(input_root)
    checkpoint_file = Path(checkpoint_path)
    checkpoint = load_checkpoint(checkpoint_file, manifest)
    state = _state_from_records(checkpoint["partial_groups"])
    completed = list(checkpoint["completed_files"])
    completed_set = set(completed)
    processed_this_run = 0
    skipped_files = 0

    for file_info in manifest["files"]:
        name = file_info["name"]
        if name in completed_set:
            skipped_files += 1
            continue
        batch = pq.read_table(
            input_root / name,
            columns=REQUIRED_COLUMNS,
        ).to_pandas()
        prepared = prepare_batch(batch)
        merge_partial_groups(state, aggregate_batch(batch))
        completed.append(name)
        completed_set.add(name)
        processed_this_run += 1
        checkpoint = {
            "version": CHECKPOINT_VERSION,
            "manifest_sha256": manifest["manifest_sha256"],
            "completed_files": completed,
            "rows_processed": int(checkpoint["rows_processed"]) + len(batch),
            "eligible_rows": int(checkpoint["eligible_rows"]) + len(prepared),
            "partial_groups": _state_records(state),
        }
        _write_json_atomic(checkpoint_file, checkpoint)
        if stop_after_files is not None and processed_this_run >= stop_after_files:
            raise SimulatedBatchInterruption(
                f"interrupted after durable checkpoint for {processed_this_run} files"
            )

    output = finalize_state(state)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_file, index=False)
    return {
        "manifest": manifest,
        "completed_files": completed,
        "processed_this_run": processed_this_run,
        "skipped_files": skipped_files,
        "rows_processed": int(checkpoint["rows_processed"]),
        "eligible_rows": int(checkpoint["eligible_rows"]),
        "groups": len(output),
        "checkpoint_complete": len(completed) == len(manifest["files"]),
        "output": output,
    }


def _read_all_batches(input_dir: str | Path) -> pd.DataFrame:
    paths = sorted(Path(input_dir).glob("batch-*.parquet"))
    if not paths:
        raise StreamingBatchError("input directory has no batch files")
    return pd.concat(
        [pq.read_table(path, columns=REQUIRED_COLUMNS).to_pandas() for path in paths],
        ignore_index=True,
    )


def run_pandas_control(input_dir: str | Path) -> pd.DataFrame:
    frame = prepare_batch(_read_all_batches(input_dir))
    grouped = frame.groupby(GROUP_COLUMNS, as_index=False, dropna=False).agg(
        orders=("order_id", "count"),
        paid_orders=("paid_order", "sum"),
        gross_revenue_cents=("gross_revenue_cents", "sum"),
        refund_amount_cents=("refund_amount_cents", "sum"),
        net_revenue_cents=("net_revenue_cents", "sum"),
        support_ticket_count=("support_ticket_count", "sum"),
    )
    grouped["revenue_per_paid_order_cents"] = grouped["net_revenue_cents"] // grouped[
        "paid_orders"
    ].replace(0, pd.NA)
    grouped["refund_rate_bp"] = np.where(
        grouped["gross_revenue_cents"] > 0,
        np.rint(grouped["refund_amount_cents"] * 10_000 / grouped["gross_revenue_cents"]),
        pd.NA,
    )
    return normalize_output(grouped)


def build_polars_streaming_pipeline(input_dir: str | Path) -> pl.LazyFrame:
    source = str(Path(input_dir) / "batch-*.parquet")
    return (
        pl.scan_parquet(source)
        .filter(
            pl.col("week_index").is_between(1, 4)
            & (pl.col("region") != "tr")
            & (~pl.col("is_test_user"))
        )
        .with_columns(
            [
                ((pl.col("status") == "paid") & (pl.col("gross_revenue_cents") > 0))
                .cast(pl.Int64)
                .alias("paid_order"),
                (pl.col("gross_revenue_cents") - pl.col("refund_amount_cents")).alias(
                    "net_revenue_cents"
                ),
            ]
        )
        .group_by(GROUP_COLUMNS)
        .agg(
            [
                pl.len().alias("orders"),
                pl.col("paid_order").sum().alias("paid_orders"),
                pl.col("gross_revenue_cents").sum(),
                pl.col("refund_amount_cents").sum(),
                pl.col("net_revenue_cents").sum(),
                pl.col("support_ticket_count").sum(),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("paid_orders") > 0)
                .then(pl.col("net_revenue_cents") // pl.col("paid_orders"))
                .otherwise(None)
                .cast(pl.Int64)
                .alias("revenue_per_paid_order_cents"),
                pl.when(pl.col("gross_revenue_cents") > 0)
                .then(
                    (pl.col("refund_amount_cents") * 10_000 / pl.col("gross_revenue_cents"))
                    .round(0)
                    .cast(pl.Int64)
                )
                .otherwise(None)
                .alias("refund_rate_bp"),
            ]
        )
        .select(OUTPUT_COLUMNS)
    )


def run_polars_streaming(
    input_dir: str | Path,
) -> tuple[pd.DataFrame, str]:
    lazy_frame = build_polars_streaming_pipeline(input_dir)
    plan = lazy_frame.explain(engine="streaming")
    result = lazy_frame.collect(engine="streaming")
    return normalize_output(result), plan


def compare_outputs(
    expected: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, Any]:
    left = normalize_output(expected)
    right = normalize_output(observed)
    matches = left.equals(right)
    diff_preview: list[dict[str, Any]] = []
    if not matches:
        diff = right.merge(
            left,
            on=GROUP_COLUMNS,
            how="outer",
            suffixes=("_observed", "_expected"),
            indicator=True,
        )
        diff_preview = json.loads(diff.head(10).to_json(orient="records"))
    return {
        "matches": bool(matches),
        "expected_rows": len(left),
        "observed_rows": len(right),
        "diff_preview": diff_preview,
    }


def operation_classification() -> list[dict[str, Any]]:
    return [
        {
            "operation": "sum/count/min/max",
            "merge_strategy": "merge fixed-size partial state",
            "bounded_state": True,
            "safe_for_chunk_merge": True,
        },
        {
            "operation": "mean",
            "merge_strategy": "merge sum and count, divide only after the final merge",
            "bounded_state": True,
            "safe_for_chunk_merge": True,
        },
        {
            "operation": "exact median/quantile",
            "merge_strategy": "requires global ordering or an exact selection algorithm",
            "bounded_state": False,
            "safe_for_chunk_merge": False,
        },
        {
            "operation": "exact distinct count",
            "merge_strategy": "merge sets, whose state grows with cardinality",
            "bounded_state": False,
            "safe_for_chunk_merge": True,
        },
        {
            "operation": "global rank",
            "merge_strategy": "requires coordination across all candidate rows",
            "bounded_state": False,
            "safe_for_chunk_merge": False,
        },
    ]


def non_associative_counterexample() -> dict[str, Any]:
    chunks = [[1, 2, 100], [3, 4]]
    chunk_medians = [float(np.median(chunk)) for chunk in chunks]
    median_of_medians = float(np.median(chunk_medians))
    exact_median = float(np.median([value for chunk in chunks for value in chunk]))
    return {
        "chunks": chunks,
        "chunk_medians": chunk_medians,
        "median_of_medians": median_of_medians,
        "exact_median": exact_median,
        "naive_merge_matches": median_of_medians == exact_median,
        "lesson": "Exact median is not obtained by taking the median of batch medians.",
    }


def build_streaming_batch_report(
    *,
    rows: int = 4_800,
    batch_size: int = 600,
    users: int = 640,
    seed: int = 42,
    interrupt_after: int = 2,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    if output_dir is None:
        raise StreamingBatchError("output_dir is required")
    package_dir = Path(output_dir)
    data_dir = package_dir / "data"
    package_dir.mkdir(parents=True, exist_ok=True)
    batch_paths = generate_order_batches(
        data_dir,
        rows=rows,
        batch_size=batch_size,
        users=users,
        seed=seed,
    )
    manifest = build_input_manifest(data_dir)
    checkpoint_path = package_dir / "checkpoint.json"
    output_path = package_dir / "batch-output.csv"
    if checkpoint_path.exists():
        checkpoint_path.unlink()

    interruption = {
        "requested_after_files": int(interrupt_after),
        "observed": False,
        "checkpointed_files_before_resume": 0,
    }
    if interrupt_after > 0 and interrupt_after < len(batch_paths):
        try:
            process_batches(
                data_dir,
                checkpoint_path,
                output_path,
                stop_after_files=interrupt_after,
            )
        except SimulatedBatchInterruption:
            interruption["observed"] = True
            durable = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            interruption["checkpointed_files_before_resume"] = len(durable["completed_files"])

    resumed = process_batches(data_dir, checkpoint_path, output_path)
    batch_output = resumed.pop("output")
    pandas_control = run_pandas_control(data_dir)
    polars_output, streaming_plan = run_polars_streaming(data_dir)
    batch_vs_pandas = compare_outputs(pandas_control, batch_output)
    polars_vs_pandas = compare_outputs(pandas_control, polars_output)
    counterexample = non_associative_counterexample()
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))

    checks = {
        "input_is_split_into_multiple_batches": len(batch_paths) > 1,
        "batch_size_respects_configured_bound": max(int(item["rows"]) for item in manifest["files"])
        <= batch_size,
        "interruption_was_checkpointed": (
            interrupt_after <= 0 or interrupt_after >= len(batch_paths) or interruption["observed"]
        ),
        "resume_skipped_checkpointed_files": (
            interruption["checkpointed_files_before_resume"] == 0
            or resumed["skipped_files"] == interruption["checkpointed_files_before_resume"]
        ),
        "checkpoint_covers_manifest": set(checkpoint["completed_files"])
        == {item["name"] for item in manifest["files"]},
        "batch_result_matches_pandas": batch_vs_pandas["matches"],
        "polars_streaming_result_matches_pandas": polars_vs_pandas["matches"],
        "output_grain_is_unique": not batch_output[GROUP_COLUMNS].duplicated().any(),
        "median_of_medians_failure_is_visible": not counterexample["naive_merge_matches"],
    }
    report = {
        "scenario": {
            "scenario_id": "streaming-checkpointed-batch",
            "pipeline_name": "customer_revenue_health_weekly_streaming",
            "rows": int(rows),
            "batch_size": int(batch_size),
            "users": int(users),
            "seed": int(seed),
            "polars_version": pl.__version__,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "manifest": manifest,
        "interruption": interruption,
        "resume": resumed,
        "operation_classification": operation_classification(),
        "non_associative_counterexample": counterexample,
        "polars_streaming": {
            "engine_requested": "streaming",
            "plan": streaming_plan,
            "fallback_note": (
                "Polars may fall back to the in-memory engine for unsupported operations; "
                "requesting streaming is not a standalone memory-safety proof."
            ),
        },
        "correctness": {
            "batch_vs_pandas": batch_vs_pandas,
            "polars_vs_pandas": polars_vs_pandas,
        },
        "interpretation": {
            "checks": checks,
            "safe_to_ship": all(checks.values()),
            "notes": [
                "The checkpoint is written atomically after each fully merged input file.",
                (
                    "Only additive partial state is checkpointed; derived ratios are "
                    "calculated after the final merge."
                ),
                "Exact median and global rank need a different algorithm or full coordination.",
            ],
        },
        "package": {
            "output_dir": str(package_dir),
            "files": [
                "data/batch-*.parquet",
                "input-manifest.json",
                "checkpoint.json",
                "batch-output.csv",
                "pandas-control.csv",
                "polars-streaming-output.csv",
                "streaming-plan.txt",
                "correctness-report.json",
                "report.json",
            ],
        },
    }
    batch_output.to_csv(output_path, index=False)
    pandas_control.to_csv(package_dir / "pandas-control.csv", index=False)
    polars_output.to_csv(package_dir / "polars-streaming-output.csv", index=False)
    (package_dir / "streaming-plan.txt").write_text(
        streaming_plan + "\n",
        encoding="utf-8",
    )
    (package_dir / "input-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (package_dir / "correctness-report.json").write_text(
        json.dumps(report["correctness"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (package_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a checkpointed streaming batch correctness report"
    )
    parser.add_argument("--rows", type=int, default=4_800)
    parser.add_argument("--batch-size", type=int, default=600)
    parser.add_argument("--users", type=int, default=640)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--interrupt-after", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_streaming_batch_report(
            rows=args.rows,
            batch_size=args.batch_size,
            users=args.users,
            seed=args.seed,
            interrupt_after=args.interrupt_after,
            output_dir=args.output_dir,
        )
    except StreamingBatchError as error:
        print(f"streaming batch error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
