from __future__ import annotations

import argparse
import cProfile
import csv
import hashlib
import inspect
import json
import platform
import pstats
import random
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb
import ibis
import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq


class PerformancePackageError(ValueError):
    """Raised when the final benchmark package cannot be trusted."""


PROFILE_ROWS = {
    "tiny": 1_200,
    "sample": 12_000,
    "large": 1_000_000,
}

REQUIRED_COLUMNS = [
    "order_id",
    "user_id",
    "week_index",
    "week_start",
    "platform",
    "region",
    "plan",
    "status",
    "gross_revenue_cents",
    "refund_amount_cents",
    "support_ticket_count",
    "active_subscription_days",
    "is_test_user",
    "debug_payload",
    "raw_event_json",
]

PIPELINE_COLUMNS = [
    "order_id",
    "week_index",
    "week_start",
    "platform",
    "region",
    "status",
    "gross_revenue_cents",
    "refund_amount_cents",
    "support_ticket_count",
    "active_subscription_days",
    "is_test_user",
]

GROUP_COLUMNS = ["week_start", "platform", "region"]

OUTPUT_COLUMNS = [
    *GROUP_COLUMNS,
    "orders",
    "paid_orders",
    "gross_revenue_cents",
    "refund_amount_cents",
    "net_revenue_cents",
    "support_ticket_count",
    "active_subscription_days",
    "revenue_per_paid_order_cents",
    "refund_rate_bp",
    "health_band",
]

INTEGER_OUTPUT_COLUMNS = [
    "orders",
    "paid_orders",
    "gross_revenue_cents",
    "refund_amount_cents",
    "net_revenue_cents",
    "support_ticket_count",
    "active_subscription_days",
    "revenue_per_paid_order_cents",
    "refund_rate_bp",
]

ENGINE_NAMES = [
    "pandas",
    "duckdb_native",
    "polars_native",
    "ibis_duckdb",
    "ibis_polars",
]

ALLOWED_DECISIONS = {
    "keep_pandas",
    "use_duckdb",
    "use_polars",
    "use_ibis_over_backend",
    "redesign_layout",
    "split_pipeline",
}

NATIVE_DUCKDB_SQL = """
WITH prepared AS (
    SELECT
        order_id,
        week_start,
        platform,
        region,
        gross_revenue_cents,
        refund_amount_cents,
        support_ticket_count,
        active_subscription_days,
        gross_revenue_cents - refund_amount_cents AS net_revenue_cents,
        CAST(
            status = 'paid' AND gross_revenue_cents > 0
            AS BIGINT
        ) AS paid_order
    FROM read_parquet(?)
    WHERE week_index BETWEEN 1 AND 6
      AND region <> 'tr'
      AND NOT is_test_user
),
aggregated AS (
    SELECT
        week_start,
        platform,
        region,
        COUNT(DISTINCT order_id) AS orders,
        SUM(paid_order) AS paid_orders,
        SUM(gross_revenue_cents) AS gross_revenue_cents,
        SUM(refund_amount_cents) AS refund_amount_cents,
        SUM(net_revenue_cents) AS net_revenue_cents,
        SUM(support_ticket_count) AS support_ticket_count,
        SUM(active_subscription_days) AS active_subscription_days
    FROM prepared
    GROUP BY week_start, platform, region
)
SELECT
    week_start,
    platform,
    region,
    orders,
    paid_orders,
    gross_revenue_cents,
    refund_amount_cents,
    net_revenue_cents,
    support_ticket_count,
    active_subscription_days,
    CASE
        WHEN paid_orders > 0
        THEN CAST(FLOOR(net_revenue_cents / paid_orders) AS BIGINT)
        ELSE NULL
    END AS revenue_per_paid_order_cents,
    CASE
        WHEN gross_revenue_cents > 0
        THEN CAST(
            FLOOR(
                (
                    refund_amount_cents * 10000
                    + FLOOR(gross_revenue_cents / 2)
                ) / gross_revenue_cents
            )
            AS BIGINT
        )
        ELSE NULL
    END AS refund_rate_bp,
    CASE
        WHEN net_revenue_cents >= 2400000 THEN 'healthy'
        WHEN net_revenue_cents >= 1400000 THEN 'watch'
        ELSE 'weak'
    END AS health_band
FROM aggregated
ORDER BY week_start, platform, region
""".strip()


TINY_ROWS = [
    {
        "order_id": "T001",
        "user_id": "U001",
        "week_index": 1,
        "week_start": "2026-01-12",
        "platform": "web",
        "region": "ru",
        "plan": "basic",
        "status": "paid",
        "gross_revenue_cents": 1_000,
        "refund_amount_cents": 0,
        "support_ticket_count": 1,
        "active_subscription_days": 4,
        "is_test_user": False,
        "debug_payload": "tiny",
        "raw_event_json": "{}",
    },
    {
        "order_id": "T002",
        "user_id": "U002",
        "week_index": 1,
        "week_start": "2026-01-12",
        "platform": "web",
        "region": "ru",
        "plan": "plus",
        "status": "refunded",
        "gross_revenue_cents": 500,
        "refund_amount_cents": 200,
        "support_ticket_count": 1,
        "active_subscription_days": 4,
        "is_test_user": False,
        "debug_payload": "tiny",
        "raw_event_json": "{}",
    },
    {
        "order_id": "T003",
        "user_id": "U003",
        "week_index": 1,
        "week_start": "2026-01-12",
        "platform": "web",
        "region": "ru",
        "plan": "trial",
        "status": "trial",
        "gross_revenue_cents": 0,
        "refund_amount_cents": 0,
        "support_ticket_count": 0,
        "active_subscription_days": 0,
        "is_test_user": False,
        "debug_payload": "tiny",
        "raw_event_json": "{}",
    },
    {
        "order_id": "T004",
        "user_id": "U004",
        "week_index": 1,
        "week_start": "2026-01-12",
        "platform": "ios",
        "region": "kz",
        "plan": "plus",
        "status": "paid",
        "gross_revenue_cents": 3_000,
        "refund_amount_cents": 0,
        "support_ticket_count": 0,
        "active_subscription_days": 7,
        "is_test_user": False,
        "debug_payload": "tiny",
        "raw_event_json": "{}",
    },
    {
        "order_id": "T005",
        "user_id": "U005",
        "week_index": 1,
        "week_start": "2026-01-12",
        "platform": "ios",
        "region": "kz",
        "plan": "pro",
        "status": "paid",
        "gross_revenue_cents": 4_000,
        "refund_amount_cents": 0,
        "support_ticket_count": 0,
        "active_subscription_days": 7,
        "is_test_user": False,
        "debug_payload": "tiny",
        "raw_event_json": "{}",
    },
    {
        "order_id": "T006",
        "user_id": "U006",
        "week_index": 2,
        "week_start": "2026-01-19",
        "platform": "android",
        "region": "am",
        "plan": "pro",
        "status": "paid",
        "gross_revenue_cents": 10_000,
        "refund_amount_cents": 0,
        "support_ticket_count": 2,
        "active_subscription_days": 7,
        "is_test_user": False,
        "debug_payload": "tiny",
        "raw_event_json": "{}",
    },
    {
        "order_id": "T007",
        "user_id": "U007",
        "week_index": 2,
        "week_start": "2026-01-19",
        "platform": "android",
        "region": "am",
        "plan": "plus",
        "status": "refunded",
        "gross_revenue_cents": 6_000,
        "refund_amount_cents": 3_000,
        "support_ticket_count": 1,
        "active_subscription_days": 5,
        "is_test_user": False,
        "debug_payload": "tiny",
        "raw_event_json": "{}",
    },
    {
        "order_id": "T008",
        "user_id": "U008",
        "week_index": 2,
        "week_start": "2026-01-19",
        "platform": "web",
        "region": "tr",
        "plan": "basic",
        "status": "paid",
        "gross_revenue_cents": 99_000,
        "refund_amount_cents": 0,
        "support_ticket_count": 0,
        "active_subscription_days": 7,
        "is_test_user": False,
        "debug_payload": "excluded-region",
        "raw_event_json": "{}",
    },
    {
        "order_id": "T009",
        "user_id": "U009",
        "week_index": 2,
        "week_start": "2026-01-19",
        "platform": "web",
        "region": "ru",
        "plan": "basic",
        "status": "paid",
        "gross_revenue_cents": 88_000,
        "refund_amount_cents": 0,
        "support_ticket_count": 0,
        "active_subscription_days": 7,
        "is_test_user": True,
        "debug_payload": "excluded-test",
        "raw_event_json": "{}",
    },
    {
        "order_id": "T010",
        "user_id": "U010",
        "week_index": 0,
        "week_start": "2026-01-05",
        "platform": "web",
        "region": "ru",
        "plan": "basic",
        "status": "paid",
        "gross_revenue_cents": 77_000,
        "refund_amount_cents": 0,
        "support_ticket_count": 0,
        "active_subscription_days": 7,
        "is_test_user": False,
        "debug_payload": "excluded-week",
        "raw_event_json": "{}",
    },
]


TINY_EXPECTED = [
    {
        "week_start": "2026-01-12",
        "platform": "ios",
        "region": "kz",
        "orders": 2,
        "paid_orders": 2,
        "gross_revenue_cents": 7_000,
        "refund_amount_cents": 0,
        "net_revenue_cents": 7_000,
        "support_ticket_count": 0,
        "active_subscription_days": 14,
        "revenue_per_paid_order_cents": 3_500,
        "refund_rate_bp": 0,
        "health_band": "weak",
    },
    {
        "week_start": "2026-01-12",
        "platform": "web",
        "region": "ru",
        "orders": 3,
        "paid_orders": 1,
        "gross_revenue_cents": 1_500,
        "refund_amount_cents": 200,
        "net_revenue_cents": 1_300,
        "support_ticket_count": 2,
        "active_subscription_days": 8,
        "revenue_per_paid_order_cents": 1_300,
        "refund_rate_bp": 1_333,
        "health_band": "weak",
    },
    {
        "week_start": "2026-01-19",
        "platform": "android",
        "region": "am",
        "orders": 2,
        "paid_orders": 1,
        "gross_revenue_cents": 16_000,
        "refund_amount_cents": 3_000,
        "net_revenue_cents": 13_000,
        "support_ticket_count": 3,
        "active_subscription_days": 12,
        "revenue_per_paid_order_cents": 13_000,
        "refund_rate_bp": 1_875,
        "health_band": "weak",
    },
]


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def generate_customer_revenue_rows(
    *,
    rows: int = 12_000,
    users: int = 1_600,
    seed: int = 42,
) -> pd.DataFrame:
    if rows < 512:
        raise PerformancePackageError("rows must be at least 512")
    if users < 32 or users > rows:
        raise PerformancePackageError("users must be between 32 and rows")

    rng = np.random.default_rng(seed)
    index = np.arange(rows, dtype=np.int64)
    user_ids = np.array(
        [f"U{position:07d}" for position in range(users)],
        dtype=object,
    )
    platforms = np.array(["web", "ios", "android"], dtype=object)
    regions = np.array(["ru", "kz", "am", "tr"], dtype=object)
    plans = np.array(["trial", "basic", "plus", "pro"], dtype=object)
    statuses = np.array(
        ["paid", "paid", "paid", "trial", "refunded"],
        dtype=object,
    )
    week_index = (index % 8).astype(np.int16)
    base_week = pd.Timestamp("2026-01-05")
    status = statuses[rng.integers(0, len(statuses), size=rows)]
    gross = rng.integers(399, 70_000, size=rows, dtype=np.int64)
    gross = np.where(status == "trial", 0, gross)
    refund = np.where(
        status == "refunded",
        np.rint(gross * rng.uniform(0.2, 1.0, size=rows)).astype(np.int64),
        0,
    )
    payload_ids = rng.integers(100_000, 999_999, size=rows)
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
            "plan": plans[rng.integers(0, len(plans), size=rows)],
            "status": status,
            "gross_revenue_cents": gross.astype(np.int64),
            "refund_amount_cents": refund.astype(np.int64),
            "support_ticket_count": rng.poisson(0.18, size=rows).astype(np.int64),
            "active_subscription_days": rng.integers(
                0,
                8,
                size=rows,
                dtype=np.int64,
            ),
            "is_test_user": index % 113 == 0,
            "debug_payload": [
                f"trace={int(value)};stage=final-benchmark;unused-wide-column"
                for value in payload_ids
            ],
            "raw_event_json": [
                (
                    '{"source":"phase-12","event_id":"evt-'
                    f'{int(value)}","attributes":"unused-wide-column"}}'
                )
                for value in payload_ids
            ],
        }
    )
    return frame.sort_values(["week_index", "order_id"]).reset_index(drop=True)


def validate_input_frame(frame: pd.DataFrame) -> dict[str, Any]:
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise PerformancePackageError(f"required columns are missing: {missing}")
    if frame.empty:
        raise PerformancePackageError("input frame is empty")
    if frame["order_id"].isna().any() or frame["order_id"].duplicated().any():
        raise PerformancePackageError("order_id must be non-null and unique")
    for column in [
        "gross_revenue_cents",
        "refund_amount_cents",
        "support_ticket_count",
        "active_subscription_days",
    ]:
        if (frame[column] < 0).any():
            raise PerformancePackageError(f"{column} must be non-negative")
    if (frame["refund_amount_cents"] > frame["gross_revenue_cents"]).any():
        raise PerformancePackageError("refund_amount_cents cannot exceed gross_revenue_cents")
    return {
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "unique_orders": int(frame["order_id"].nunique()),
        "unused_wide_columns": ["debug_payload", "raw_event_json"],
    }


def write_parquet_input(
    frame: pd.DataFrame,
    path: str | Path,
    *,
    row_group_size: int = 1_024,
) -> Path:
    if row_group_size <= 0:
        raise PerformancePackageError("row_group_size must be positive")
    validate_input_frame(frame)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        output_path,
        row_group_size=row_group_size,
        compression="zstd",
        use_dictionary=True,
        write_statistics=True,
    )
    return output_path


def _eligible_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.loc[
        frame["week_index"].between(1, 6) & (frame["region"] != "tr") & ~frame["is_test_user"],
        PIPELINE_COLUMNS,
    ].copy()


def _health_band(net_revenue_cents: int) -> str:
    if net_revenue_cents >= 2_400_000:
        return "healthy"
    if net_revenue_cents >= 1_400_000:
        return "watch"
    return "weak"


def run_manual_reference(frame: pd.DataFrame) -> pd.DataFrame:
    validate_input_frame(frame)
    state: dict[tuple[str, str, str], dict[str, int]] = {}
    for row in _eligible_rows(frame).to_dict(orient="records"):
        key = (
            str(row["week_start"]),
            str(row["platform"]),
            str(row["region"]),
        )
        bucket = state.setdefault(
            key,
            {
                "orders": 0,
                "paid_orders": 0,
                "gross_revenue_cents": 0,
                "refund_amount_cents": 0,
                "net_revenue_cents": 0,
                "support_ticket_count": 0,
                "active_subscription_days": 0,
            },
        )
        gross = int(row["gross_revenue_cents"])
        refund = int(row["refund_amount_cents"])
        bucket["orders"] += 1
        bucket["paid_orders"] += int(row["status"] == "paid" and gross > 0)
        bucket["gross_revenue_cents"] += gross
        bucket["refund_amount_cents"] += refund
        bucket["net_revenue_cents"] += gross - refund
        bucket["support_ticket_count"] += int(row["support_ticket_count"])
        bucket["active_subscription_days"] += int(row["active_subscription_days"])

    rows = []
    for key, values in sorted(state.items()):
        gross = values["gross_revenue_cents"]
        paid = values["paid_orders"]
        net = values["net_revenue_cents"]
        rows.append(
            {
                **dict(zip(GROUP_COLUMNS, key, strict=True)),
                **values,
                "revenue_per_paid_order_cents": net // paid if paid > 0 else None,
                "refund_rate_bp": (values["refund_amount_cents"] * 10_000 + gross // 2) // gross
                if gross > 0
                else None,
                "health_band": _health_band(net),
            }
        )
    return normalize_output(pd.DataFrame(rows))


def run_pandas_pipeline(parquet_path: str | Path) -> pd.DataFrame:
    frame = pd.read_parquet(parquet_path, columns=PIPELINE_COLUMNS)
    prepared = _eligible_rows(frame)
    prepared["net_revenue_cents"] = (
        prepared["gross_revenue_cents"] - prepared["refund_amount_cents"]
    )
    prepared["paid_order"] = (
        (prepared["status"] == "paid") & (prepared["gross_revenue_cents"] > 0)
    ).astype("int64")
    grouped = prepared.groupby(GROUP_COLUMNS, as_index=False).agg(
        orders=("order_id", "nunique"),
        paid_orders=("paid_order", "sum"),
        gross_revenue_cents=("gross_revenue_cents", "sum"),
        refund_amount_cents=("refund_amount_cents", "sum"),
        net_revenue_cents=("net_revenue_cents", "sum"),
        support_ticket_count=("support_ticket_count", "sum"),
        active_subscription_days=("active_subscription_days", "sum"),
    )
    grouped["revenue_per_paid_order_cents"] = grouped["net_revenue_cents"] // grouped[
        "paid_orders"
    ].replace(0, pd.NA)
    grouped["refund_rate_bp"] = np.where(
        grouped["gross_revenue_cents"] > 0,
        (grouped["refund_amount_cents"] * 10_000 + grouped["gross_revenue_cents"] // 2)
        // grouped["gross_revenue_cents"],
        pd.NA,
    )
    grouped["health_band"] = np.select(
        [
            grouped["net_revenue_cents"] >= 2_400_000,
            grouped["net_revenue_cents"] >= 1_400_000,
        ],
        ["healthy", "watch"],
        default="weak",
    )
    return normalize_output(grouped)


def build_polars_lazy_pipeline(parquet_path: str | Path) -> pl.LazyFrame:
    return (
        pl.scan_parquet(parquet_path)
        .filter(
            pl.col("week_index").is_between(1, 6)
            & (pl.col("region") != "tr")
            & (~pl.col("is_test_user"))
        )
        .with_columns(
            [
                (pl.col("gross_revenue_cents") - pl.col("refund_amount_cents")).alias(
                    "net_revenue_cents"
                ),
                ((pl.col("status") == "paid") & (pl.col("gross_revenue_cents") > 0))
                .cast(pl.Int64)
                .alias("paid_order"),
            ]
        )
        .group_by(GROUP_COLUMNS)
        .agg(
            [
                pl.col("order_id").n_unique().alias("orders"),
                pl.col("paid_order").sum().alias("paid_orders"),
                pl.col("gross_revenue_cents").sum(),
                pl.col("refund_amount_cents").sum(),
                pl.col("net_revenue_cents").sum(),
                pl.col("support_ticket_count").sum(),
                pl.col("active_subscription_days").sum(),
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
                    (
                        (
                            pl.col("refund_amount_cents") * 10_000
                            + pl.col("gross_revenue_cents") // 2
                        )
                        // pl.col("gross_revenue_cents")
                    ).cast(pl.Int64)
                )
                .otherwise(None)
                .alias("refund_rate_bp"),
                pl.when(pl.col("net_revenue_cents") >= 2_400_000)
                .then(pl.lit("healthy"))
                .when(pl.col("net_revenue_cents") >= 1_400_000)
                .then(pl.lit("watch"))
                .otherwise(pl.lit("weak"))
                .alias("health_band"),
            ]
        )
        .select(OUTPUT_COLUMNS)
        .sort(GROUP_COLUMNS)
    )


def run_polars_pipeline(parquet_path: str | Path) -> pd.DataFrame:
    result = build_polars_lazy_pipeline(parquet_path).collect(engine="streaming")
    return normalize_output(result)


def run_duckdb_pipeline(
    connection: duckdb.DuckDBPyConnection,
    parquet_path: str | Path,
) -> pd.DataFrame:
    result = connection.execute(
        NATIVE_DUCKDB_SQL,
        [str(parquet_path)],
    ).fetchdf()
    return normalize_output(result)


def build_ibis_pipeline(table: Any) -> Any:
    prepared = table.filter(
        table.week_index.between(1, 6) & (table.region != "tr") & ~table.is_test_user
    ).mutate(
        net_revenue_cents=(table.gross_revenue_cents - table.refund_amount_cents),
        paid_order=((table.status == "paid") & (table.gross_revenue_cents > 0)).cast("int64"),
    )
    grouped = prepared.group_by(*GROUP_COLUMNS).aggregate(
        orders=prepared.order_id.nunique(),
        paid_orders=prepared.paid_order.sum(),
        gross_revenue_cents=prepared.gross_revenue_cents.sum(),
        refund_amount_cents=prepared.refund_amount_cents.sum(),
        net_revenue_cents=prepared.net_revenue_cents.sum(),
        support_ticket_count=prepared.support_ticket_count.sum(),
        active_subscription_days=prepared.active_subscription_days.sum(),
    )
    return (
        grouped.mutate(
            revenue_per_paid_order_cents=ibis.ifelse(
                grouped.paid_orders > 0,
                grouped.net_revenue_cents // grouped.paid_orders,
                ibis.null(),
            ).cast("int64"),
            refund_rate_bp=ibis.ifelse(
                grouped.gross_revenue_cents > 0,
                (
                    (grouped.refund_amount_cents * 10_000 + grouped.gross_revenue_cents // 2)
                    // grouped.gross_revenue_cents
                ).cast("int64"),
                ibis.null(),
            ).cast("int64"),
            health_band=ibis.cases(
                (
                    grouped.net_revenue_cents >= 2_400_000,
                    "healthy",
                ),
                (
                    grouped.net_revenue_cents >= 1_400_000,
                    "watch",
                ),
                else_="weak",
            ),
        )
        .select(*OUTPUT_COLUMNS)
        .order_by(*GROUP_COLUMNS)
    )


def build_ibis_rank_probe(table: Any) -> Any:
    portable = build_ibis_pipeline(table)
    window = ibis.window(
        group_by="week_start",
        order_by=ibis.desc(portable.net_revenue_cents),
    )
    return portable.mutate(week_revenue_rank=(ibis.dense_rank().over(window) + 1).cast("int64"))


def normalize_output(frame: pd.DataFrame | pl.DataFrame) -> pd.DataFrame:
    normalized = frame.to_pandas() if isinstance(frame, pl.DataFrame) else frame.copy()
    normalized = normalized[OUTPUT_COLUMNS].copy()
    for column in [*GROUP_COLUMNS, "health_band"]:
        normalized[column] = normalized[column].astype("string")
    for column in INTEGER_OUTPUT_COLUMNS:
        normalized[column] = pd.to_numeric(normalized[column]).astype("Int64")
    return normalized.sort_values(
        GROUP_COLUMNS,
        kind="mergesort",
    ).reset_index(drop=True)


def output_records(frame: pd.DataFrame | pl.DataFrame) -> list[dict[str, Any]]:
    normalized = normalize_output(frame)
    return json.loads(normalized.to_json(orient="records"))


def compare_output(
    reference: pd.DataFrame,
    observed: pd.DataFrame,
    *,
    engine: str,
) -> dict[str, Any]:
    expected = normalize_output(reference)
    actual = normalize_output(observed)
    matches = expected.equals(actual)
    mismatch_count = 0
    mismatch_preview: list[dict[str, Any]] = []
    if not matches:
        expected_records = output_records(expected)
        actual_records = output_records(actual)
        for index in range(max(len(expected_records), len(actual_records))):
            expected_row = expected_records[index] if index < len(expected_records) else None
            actual_row = actual_records[index] if index < len(actual_records) else None
            if expected_row != actual_row:
                mismatch_count += 1
                if len(mismatch_preview) < 10:
                    mismatch_preview.append(
                        {
                            "row_index": index,
                            "expected": expected_row,
                            "actual": actual_row,
                        }
                    )
    return {
        "engine": engine,
        "passed": bool(matches),
        "row_count": len(actual),
        "expected_checksum": stable_json_hash(output_records(expected)),
        "actual_checksum": stable_json_hash(output_records(actual)),
        "mismatch_count": mismatch_count,
        "mismatch_preview": mismatch_preview,
    }


def enforce_equivalence(checks: list[dict[str, Any]]) -> None:
    failed = [check["engine"] for check in checks if not check["passed"]]
    if failed:
        raise PerformancePackageError(
            "equivalence gate failed before timing for engines: " + ", ".join(failed)
        )


def measure_runner(
    runner: Callable[[], pd.DataFrame],
    *,
    engine: str,
    repeat: int,
    warmup: int,
) -> list[dict[str, Any]]:
    if repeat < 3:
        raise PerformancePackageError("repeat must be at least 3")
    if warmup < 1:
        raise PerformancePackageError("warmup must be at least 1")
    for _ in range(warmup):
        runner()
    runs = []
    for run_id in range(1, repeat + 1):
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        result = runner()
        cpu_seconds = time.process_time() - cpu_started
        wall_seconds = time.perf_counter() - wall_started
        runs.append(
            {
                "measurement_id": f"{engine}-run-{run_id}",
                "engine": engine,
                "run_id": run_id,
                "wall_seconds": wall_seconds,
                "process_cpu_seconds": cpu_seconds,
                "result_rows": len(result),
                "result_checksum": stable_json_hash(output_records(result)),
            }
        )
    return runs


def summarize_runs(
    raw_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in raw_runs:
        grouped.setdefault(str(run["engine"]), []).append(run)
    summary = []
    for engine, runs in sorted(grouped.items()):
        wall = [float(run["wall_seconds"]) for run in runs]
        cpu = [float(run["process_cpu_seconds"]) for run in runs]
        summary.append(
            {
                "engine": engine,
                "runs": len(runs),
                "min_wall_seconds": min(wall),
                "median_wall_seconds": statistics.median(wall),
                "max_wall_seconds": max(wall),
                "mean_wall_seconds": statistics.fmean(wall),
                "median_process_cpu_seconds": statistics.median(cpu),
            }
        )
    return summary


def profile_python_runner(
    runner: Callable[[], pd.DataFrame],
    *,
    engine: str,
) -> dict[str, Any]:
    profiler = cProfile.Profile()
    profiler.enable()
    runner()
    profiler.disable()
    stats = pstats.Stats(profiler).sort_stats("cumulative")
    top = []
    for (filename, line_number, function_name), values in list(stats.stats.items())[:20]:
        primitive_calls, total_calls, total_time, cumulative_time, _callers = values
        top.append(
            {
                "function": function_name,
                "file": Path(filename).name,
                "line": line_number,
                "primitive_calls": primitive_calls,
                "total_calls": total_calls,
                "total_time_seconds": total_time,
                "cumulative_time_seconds": cumulative_time,
            }
        )
    return {
        "engine": engine,
        "profiler": "cProfile",
        "top_functions": sorted(
            top,
            key=lambda row: row["cumulative_time_seconds"],
            reverse=True,
        )[:10],
        "limitation": (
            "cProfile attributes Python call time and does not expose native operator internals."
        ),
    }


def profile_python_memory(
    runners: dict[str, Callable[[], pd.DataFrame]],
) -> dict[str, Any]:
    measurements = []
    for engine, runner in runners.items():
        tracemalloc.start()
        runner()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        measurements.append(
            {
                "engine": engine,
                "current_python_bytes": current,
                "peak_python_bytes": peak,
            }
        )
    return {
        "tool": "tracemalloc",
        "measurements": measurements,
        "limitation": (
            "tracemalloc measures Python allocations and can miss native memory "
            "used by DuckDB, Arrow and Polars."
        ),
    }


def parquet_layout_report(
    parquet_path: str | Path,
    *,
    row_group_size: int,
) -> dict[str, Any]:
    path = Path(parquet_path)
    metadata = pq.ParquetFile(path).metadata
    row_groups = []
    for index in range(metadata.num_row_groups):
        group = metadata.row_group(index)
        row_groups.append(
            {
                "row_group": index,
                "rows": group.num_rows,
                "total_byte_size": group.total_byte_size,
            }
        )
    return {
        "format": "parquet",
        "compression": "zstd",
        "row_group_size_requested": row_group_size,
        "row_groups": row_groups,
        "files": 1,
        "file_size_bytes": path.stat().st_size,
        "partitioning": "none",
        "statistics_written": True,
    }


def plan_evidence(
    *,
    native_duckdb: duckdb.DuckDBPyConnection,
    parquet_path: Path,
    native_polars: pl.LazyFrame,
    ibis_duckdb_backend: Any,
    ibis_duckdb_expression: Any,
    ibis_polars_backend: Any,
    ibis_polars_expression: Any,
) -> dict[str, Any]:
    duckdb_plan = native_duckdb.execute(
        "EXPLAIN " + NATIVE_DUCKDB_SQL,
        [str(parquet_path)],
    ).fetchone()[1]
    polars_plan = native_polars.explain(optimized=True)
    ibis_duckdb_sql = ibis_duckdb_backend.compile(ibis_duckdb_expression)
    ibis_polars_lazy = ibis_polars_backend.compile(ibis_polars_expression)
    ibis_polars_plan = ibis_polars_lazy.explain(optimized=True)
    return {
        "duckdb_native": {
            "plan_text": duckdb_plan,
            "checks": {
                "parquet_scan": "PARQUET" in duckdb_plan.upper(),
                "aggregate": "GROUP_BY" in duckdb_plan.upper()
                or "AGGREGATE" in duckdb_plan.upper(),
                "filter": "FILTER" in duckdb_plan.upper(),
            },
        },
        "polars_native": {
            "plan_text": polars_plan,
            "checks": {
                "parquet_scan": "PARQUET SCAN" in polars_plan.upper(),
                "predicate_pushdown": "SELECTION:" in polars_plan,
                "aggregate": "AGGREGATE" in polars_plan.upper(),
            },
        },
        "ibis_duckdb": {
            "compiled_type": type(ibis_duckdb_sql).__name__,
            "compiled_sql": str(ibis_duckdb_sql),
            "checks": {
                "select": "SELECT" in str(ibis_duckdb_sql).upper(),
                "group_by": "GROUP BY" in str(ibis_duckdb_sql).upper(),
                "case": "CASE WHEN" in str(ibis_duckdb_sql).upper(),
            },
        },
        "ibis_polars": {
            "compiled_type": type(ibis_polars_lazy).__name__,
            "plan_text": ibis_polars_plan,
            "checks": {
                "lazy_frame": isinstance(
                    ibis_polars_lazy,
                    pl.LazyFrame,
                ),
                "parquet_scan": "PARQUET SCAN" in ibis_polars_plan.upper(),
                "aggregate": "AGGREGATE" in ibis_polars_plan.upper(),
            },
        },
    }


def compile_probe(
    backend: Any,
    expression: Any,
) -> dict[str, Any]:
    try:
        compiled = backend.compile(expression)
    except Exception as error:  # noqa: BLE001 - portability evidence.
        return {
            "supported": False,
            "error_type": type(error).__name__,
            "message": str(error),
        }
    return {
        "supported": True,
        "compiled_type": type(compiled).__name__,
        "preview": str(compiled)[:500],
    }


def portability_audit(
    *,
    ibis_duckdb_backend: Any,
    ibis_duckdb_table: Any,
    ibis_polars_backend: Any,
    ibis_polars_table: Any,
) -> dict[str, Any]:
    portable_duckdb = compile_probe(
        ibis_duckdb_backend,
        build_ibis_pipeline(ibis_duckdb_table),
    )
    portable_polars = compile_probe(
        ibis_polars_backend,
        build_ibis_pipeline(ibis_polars_table),
    )
    rank_duckdb = compile_probe(
        ibis_duckdb_backend,
        build_ibis_rank_probe(ibis_duckdb_table),
    )
    rank_polars = compile_probe(
        ibis_polars_backend,
        build_ibis_rank_probe(ibis_polars_table),
    )
    return {
        "portable_core": {
            "operations": [
                "parquet scan",
                "filter",
                "mutate",
                "group_by",
                "nunique",
                "sum",
                "integer floor division",
                "case",
                "sort",
            ],
            "duckdb": portable_duckdb,
            "polars": portable_polars,
            "portable_on_tested_backends": portable_duckdb["supported"]
            and portable_polars["supported"],
        },
        "window_rank_probe": {
            "operation": "dense_rank over week_start ordered by revenue",
            "duckdb": rank_duckdb,
            "polars": rank_polars,
            "divergence_detected": rank_duckdb["supported"] and not rank_polars["supported"],
            "policy": (
                "Keep rank outside the portable core or provide an explicit "
                "backend-specific fallback."
            ),
        },
        "conclusion": (
            "Ibis makes the shared relational core reusable, but backend "
            "capability checks remain mandatory."
        ),
    }


def environment_report(
    *,
    dataset_profile: str,
    rows: int,
    repeat: int,
    warmup: int,
) -> dict[str, Any]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "dataset_profile": dataset_profile,
        "rows": rows,
        "warmup_runs": warmup,
        "measured_runs": repeat,
        "versions": {
            "pandas": pd.__version__,
            "duckdb": duckdb.__version__,
            "polars": pl.__version__,
            "pyarrow": pa.__version__,
            "ibis": ibis.__version__,
        },
        "thread_policy": (
            "Library defaults; reported without claiming cross-machine comparability."
        ),
        "cache_policy": (
            "One warm-up per engine; measured runs use the same local Parquet "
            "file and therefore represent a warm filesystem cache."
        ),
        "timing_scope": (
            "Parquet scan, compute and conversion to normalized pandas output; "
            "data generation, Parquet write, connection setup and compilation "
            "are excluded."
        ),
    }


def default_benchmark_plan(
    *,
    dataset_profile: str,
    rows: int,
    repeat: int,
    warmup: int,
    parquet_path: str,
) -> dict[str, Any]:
    return {
        "scenario_id": "customer-revenue-health-multi-engine",
        "business_question": (
            "Which local engine should run the weekly customer revenue health "
            "pipeline without changing metric semantics?"
        ),
        "pipeline_name": "customer_revenue_health_weekly",
        "pipeline_version": "1.0",
        "dataset_profile": dataset_profile,
        "input_paths": [parquet_path],
        "input_format": "parquet",
        "layout_policy": "single zstd Parquet file with row-group statistics",
        "expected_output_contract": (
            "one row per week_start, platform, region with exact integer metrics"
        ),
        "scale_rows": rows,
        "memory_budget_mb": 512,
        "engines": ENGINE_NAMES,
        "engine_versions": "recorded in measurements/environment.json",
        "thread_policy": "library defaults",
        "cache_policy": ("warm filesystem cache after one warm-up; no cold-cache claim"),
        "warmup_runs": warmup,
        "measured_runs": repeat,
        "timer": "time.perf_counter and time.process_time",
        "memory_metric": "tracemalloc Python peak with native-memory limitation",
        "cpu_metric": "process_time plus cProfile for pandas control",
        "io_metric": "input file bytes and row-group metadata",
        "plan_checks": [
            "DuckDB EXPLAIN",
            "Polars optimized plan",
            "Ibis DuckDB compiled SQL",
            "Ibis Polars LazyFrame plan",
        ],
        "equivalence_checks": [
            "manual tiny expected output",
            "exact normalized output equality before timing",
            "stable result checksum on every measured run",
        ],
        "quality_gates": [
            "unique output grain",
            "all engines equivalent",
            "portable Ibis core supported by DuckDB and Polars",
            "decision references measurements and limitations",
        ],
        "selection_rule": (
            "Choose the fastest equivalent native backend; prefer Ibis over that "
            "backend when its median overhead is at most 25% and portability "
            "checks pass."
        ),
        "known_limitations": [
            "warm-cache local benchmark",
            "native memory is not fully measured",
            "Ibis Polars does not support the tested dense-rank window",
        ],
        "rerun_instructions": (
            "Run the packager again with the same profile, rows, seed, warm-up "
            "and repeat values on the target machine."
        ),
    }


def select_engine_decision(
    summary: list[dict[str, Any]],
    portability: dict[str, Any],
) -> dict[str, Any]:
    medians = {row["engine"]: float(row["median_wall_seconds"]) for row in summary}
    native_names = ["pandas", "duckdb_native", "polars_native"]
    fastest_native = min(native_names, key=medians.__getitem__)
    fastest_median = medians[fastest_native]
    ibis_for_native = {
        "duckdb_native": "ibis_duckdb",
        "polars_native": "ibis_polars",
    }
    if fastest_native == "pandas":
        decision = "keep_pandas"
        selected_engine = "pandas"
        reason = "pandas has the lowest native median for this measured profile."
    else:
        ibis_name = ibis_for_native[fastest_native]
        overhead_ratio = medians[ibis_name] / fastest_median
        if portability["portable_core"]["portable_on_tested_backends"] and overhead_ratio <= 1.25:
            decision = "use_ibis_over_backend"
            selected_engine = ibis_name
            reason = (
                f"{ibis_name} stays within 25% of {fastest_native} while "
                "preserving a tested portable core."
            )
        elif fastest_native == "duckdb_native":
            decision = "use_duckdb"
            selected_engine = fastest_native
            reason = "DuckDB has the lowest equivalent native median."
        else:
            decision = "use_polars"
            selected_engine = fastest_native
            reason = "Polars has the lowest equivalent native median."

    if decision not in ALLOWED_DECISIONS:
        raise PerformancePackageError(f"invalid engine decision: {decision}")
    selected_summary = next(row for row in summary if row["engine"] == selected_engine)
    limitation_ids = [
        "L1-warm-cache-local-only",
        "L2-native-memory-not-fully-measured",
        "L3-ibis-polars-window-rank-unsupported",
    ]
    return {
        "decision": decision,
        "selected_engine": selected_engine,
        "reason": reason,
        "evidence": {
            "measurement_ids": [
                f"{selected_engine}-run-{run_id}"
                for run_id in range(
                    1,
                    int(selected_summary["runs"]) + 1,
                )
            ],
            "profile_id": "customer-revenue-health-multi-engine",
            "plan_checks": [
                "duckdb_native",
                "polars_native",
                "ibis_duckdb",
                "ibis_polars",
            ],
            "limitation_ids": limitation_ids,
        },
        "medians": medians,
        "selection_rule_applied": True,
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise PerformancePackageError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _render_engine_decision(decision: dict[str, Any]) -> str:
    evidence = decision["evidence"]
    return f"""# Engine decision

**Decision:** `{decision["decision"]}`
**Selected engine:** `{decision["selected_engine"]}`

{decision["reason"]}

## Evidence

- Measurement IDs: {", ".join(evidence["measurement_ids"])}
- Profile ID: `{evidence["profile_id"]}`
- Plan checks: {", ".join(evidence["plan_checks"])}
- Limitations: {", ".join(evidence["limitation_ids"])}

The decision is valid only for the recorded dataset profile, environment and cache policy.
"""


def _render_portability_audit(portability: dict[str, Any]) -> str:
    core = portability["portable_core"]
    probe = portability["window_rank_probe"]
    return f"""# Ibis portability audit

## Portable core

- DuckDB supported: `{core["duckdb"]["supported"]}`
- Polars supported: `{core["polars"]["supported"]}`
- Portable on tested backends: `{core["portable_on_tested_backends"]}`
- Operations: {", ".join(core["operations"])}

## Backend divergence

- Probe: {probe["operation"]}
- DuckDB supported: `{probe["duckdb"]["supported"]}`
- Polars supported: `{probe["polars"]["supported"]}`
- Divergence detected: `{probe["divergence_detected"]}`

Policy: {probe["policy"]}

{portability["conclusion"]}
"""


def _limitations_markdown() -> str:
    return """# Limitations

## L1-warm-cache-local-only

The benchmark runs on one local machine after warm-up. It is not a cold-cache or
cross-machine claim.

## L2-native-memory-not-fully-measured

`tracemalloc` does not capture all native allocations made by Arrow, DuckDB and Polars.

## L3-ibis-polars-window-rank-unsupported

Ibis 12.0.0 compiles the tested dense-rank window for DuckDB but not for the Polars
backend. Rank remains outside the portable core.

## L4-default-thread-policy

Libraries use their defaults. A production decision should repeat the benchmark with an
explicit thread and concurrency policy.
"""


def _pipeline_sources() -> dict[str, str]:
    return {
        "pandas_pipeline.py": inspect.getsource(run_pandas_pipeline),
        "duckdb_pipeline.sql": NATIVE_DUCKDB_SQL,
        "polars_pipeline.py": (
            inspect.getsource(build_polars_lazy_pipeline)
            + "\n\n"
            + inspect.getsource(run_polars_pipeline)
        ),
        "ibis_pipeline.py": (
            inspect.getsource(build_ibis_pipeline)
            + "\n\n"
            + inspect.getsource(build_ibis_rank_probe)
        ),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(package_dir: Path) -> dict[str, Any]:
    files = []
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        files.append(
            {
                "path": str(path.relative_to(package_dir)),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    manifest = {
        "algorithm": "sha256",
        "files": files,
        "file_count": len(files),
    }
    _write_json(package_dir / "manifest.json", manifest)
    return manifest


def validate_manifest(package_dir: Path) -> dict[str, Any]:
    manifest_path = package_dir / "manifest.json"
    if not manifest_path.is_file():
        raise PerformancePackageError("manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches = []
    for item in manifest["files"]:
        path = package_dir / item["path"]
        if not path.is_file():
            mismatches.append({"path": item["path"], "reason": "missing"})
        elif _sha256_file(path) != item["sha256"]:
            mismatches.append({"path": item["path"], "reason": "checksum"})
    return {
        "valid": not mismatches,
        "checked_files": len(manifest["files"]),
        "mismatches": mismatches,
    }


def _build_runners(
    *,
    parquet_path: Path,
) -> tuple[
    dict[str, Callable[[], pd.DataFrame]],
    dict[str, Any],
]:
    native_duckdb = duckdb.connect()
    native_duckdb.execute("SET TimeZone = 'UTC'")
    native_polars = build_polars_lazy_pipeline(parquet_path)

    ibis_duckdb_backend = ibis.duckdb.connect()
    ibis_duckdb_table = ibis_duckdb_backend.read_parquet(
        parquet_path,
        table_name="orders",
    )
    ibis_duckdb_expression = build_ibis_pipeline(ibis_duckdb_table)

    ibis_polars_backend = ibis.polars.connect()
    ibis_polars_table = ibis_polars_backend.read_parquet(
        parquet_path,
        table_name="orders",
    )
    ibis_polars_expression = build_ibis_pipeline(ibis_polars_table)

    runners = {
        "pandas": lambda: run_pandas_pipeline(parquet_path),
        "duckdb_native": lambda: run_duckdb_pipeline(
            native_duckdb,
            parquet_path,
        ),
        "polars_native": lambda: normalize_output(native_polars.collect(engine="streaming")),
        "ibis_duckdb": lambda: normalize_output(
            ibis_duckdb_backend.execute(ibis_duckdb_expression)
        ),
        "ibis_polars": lambda: normalize_output(
            ibis_polars_backend.execute(
                ibis_polars_expression,
                engine="streaming",
            )
        ),
    }
    context = {
        "native_duckdb": native_duckdb,
        "native_polars": native_polars,
        "ibis_duckdb_backend": ibis_duckdb_backend,
        "ibis_duckdb_table": ibis_duckdb_table,
        "ibis_duckdb_expression": ibis_duckdb_expression,
        "ibis_polars_backend": ibis_polars_backend,
        "ibis_polars_table": ibis_polars_table,
        "ibis_polars_expression": ibis_polars_expression,
    }
    return runners, context


def build_performance_benchmark_package(
    *,
    dataset_profile: str = "sample",
    rows: int | None = None,
    users: int | None = None,
    seed: int = 42,
    repeat: int = 5,
    warmup: int = 1,
    row_group_size: int = 1_024,
    allow_large: bool = False,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    if dataset_profile not in PROFILE_ROWS:
        raise PerformancePackageError(f"unknown dataset_profile: {dataset_profile}")
    if dataset_profile == "large" and not allow_large:
        raise PerformancePackageError("large profile requires allow_large=True or --allow-large")
    if output_dir is None:
        raise PerformancePackageError("output_dir is required")
    if repeat < 3:
        raise PerformancePackageError("repeat must be at least 3")
    if warmup < 1:
        raise PerformancePackageError("warmup must be at least 1")

    resolved_rows = rows or PROFILE_ROWS[dataset_profile]
    resolved_users = users or max(32, resolved_rows // 8)
    package_dir = Path(output_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    frame = generate_customer_revenue_rows(
        rows=resolved_rows,
        users=resolved_users,
        seed=seed,
    )
    input_summary = validate_input_frame(frame)
    parquet_path = write_parquet_input(
        frame,
        package_dir / "data" / "orders.parquet",
        row_group_size=row_group_size,
    )
    layout = parquet_layout_report(
        parquet_path,
        row_group_size=row_group_size,
    )

    tiny_frame = pd.DataFrame(TINY_ROWS)
    tiny_observed = run_manual_reference(tiny_frame)
    tiny_expected = normalize_output(pd.DataFrame(TINY_EXPECTED))
    tiny_check = compare_output(
        tiny_expected,
        tiny_observed,
        engine="manual_reference",
    )
    if not tiny_check["passed"]:
        raise PerformancePackageError("manual tiny expected-output check failed")

    reference = run_manual_reference(frame)
    runners, context = _build_runners(parquet_path=parquet_path)
    try:
        outputs = {name: runner() for name, runner in runners.items()}
        checks = [
            compare_output(reference, output, engine=name) for name, output in outputs.items()
        ]
        enforce_equivalence(checks)

        engine_order = list(ENGINE_NAMES)
        random.Random(seed).shuffle(engine_order)
        raw_runs = []
        for engine in engine_order:
            raw_runs.extend(
                measure_runner(
                    runners[engine],
                    engine=engine,
                    repeat=repeat,
                    warmup=warmup,
                )
            )
        summary = summarize_runs(raw_runs)

        plans = plan_evidence(
            native_duckdb=context["native_duckdb"],
            parquet_path=parquet_path,
            native_polars=context["native_polars"],
            ibis_duckdb_backend=context["ibis_duckdb_backend"],
            ibis_duckdb_expression=context["ibis_duckdb_expression"],
            ibis_polars_backend=context["ibis_polars_backend"],
            ibis_polars_expression=context["ibis_polars_expression"],
        )
        portability = portability_audit(
            ibis_duckdb_backend=context["ibis_duckdb_backend"],
            ibis_duckdb_table=context["ibis_duckdb_table"],
            ibis_polars_backend=context["ibis_polars_backend"],
            ibis_polars_table=context["ibis_polars_table"],
        )
        decision = select_engine_decision(summary, portability)
        python_profile = profile_python_runner(
            runners["pandas"],
            engine="pandas",
        )
        memory_profile = profile_python_memory(runners)
    finally:
        context["native_duckdb"].close()
        context["ibis_duckdb_backend"].disconnect()

    environment = environment_report(
        dataset_profile=dataset_profile,
        rows=resolved_rows,
        repeat=repeat,
        warmup=warmup,
    )
    benchmark_plan = default_benchmark_plan(
        dataset_profile=dataset_profile,
        rows=resolved_rows,
        repeat=repeat,
        warmup=warmup,
        parquet_path="data/orders.parquet",
    )
    output_grain_unique = not reference[GROUP_COLUMNS].duplicated().any()
    report_checks = {
        "manual_tiny_expected_output_passed": tiny_check["passed"],
        "all_engines_equivalent_before_timing": all(check["passed"] for check in checks),
        "all_measured_runs_keep_result_checksum": all(
            run["result_checksum"] == checks[0]["actual_checksum"] for run in raw_runs
        ),
        "output_grain_unique": output_grain_unique,
        "duckdb_plan_checks_pass": all(plans["duckdb_native"]["checks"].values()),
        "polars_plan_checks_pass": all(plans["polars_native"]["checks"].values()),
        "ibis_portable_core_supported": portability["portable_core"]["portable_on_tested_backends"],
        "backend_divergence_documented": portability["window_rank_probe"]["divergence_detected"],
        "engine_decision_is_allowed": decision["decision"] in ALLOWED_DECISIONS,
        "engine_decision_has_measurement_links": bool(decision["evidence"]["measurement_ids"]),
        "engine_decision_has_limitations": bool(decision["evidence"]["limitation_ids"]),
    }

    _write_json(package_dir / "benchmark-plan.json", benchmark_plan)
    _write_json(
        package_dir / "data-contract" / "sources.json",
        {
            "table": "orders",
            "grain": "one order",
            "primary_key": ["order_id"],
            "required_columns": REQUIRED_COLUMNS,
            "input_summary": input_summary,
        },
    )
    _write_json(
        package_dir / "data-contract" / "output-contract.json",
        {
            "table": "customer_revenue_health_weekly",
            "grain": GROUP_COLUMNS,
            "columns": OUTPUT_COLUMNS,
            "integer_columns": INTEGER_OUTPUT_COLUMNS,
            "sort_order": GROUP_COLUMNS,
        },
    )
    _write_json(
        package_dir / "data-contract" / "dtype-policy.json",
        {
            "money": "int64 cents",
            "counts": "int64 nullable only when denominator is zero",
            "dimensions": "string labels",
            "test_user": "boolean",
            "forbidden": ["float money", "category codes as business keys"],
        },
    )
    _write_json(
        package_dir / "data-layout" / "parquet-layout.json",
        layout,
    )
    _write_json(
        package_dir / "data-layout" / "partition-summary.json",
        {
            "partitioned": False,
            "reason": (
                "The sample package uses one file; partitioning decisions require "
                "the target workload and scale."
            ),
        },
    )
    _write_json(
        package_dir / "data-layout" / "row-group-summary.json",
        {"row_groups": layout["row_groups"]},
    )
    for filename, content in _pipeline_sources().items():
        _write_text(package_dir / "pipelines" / filename, content)
    _write_json(
        package_dir / "profiles" / "python-profile.json",
        python_profile,
    )
    _write_json(
        package_dir / "profiles" / "memory-profile.json",
        memory_profile,
    )
    _write_json(
        package_dir / "profiles" / "duckdb-plan.json",
        plans["duckdb_native"],
    )
    _write_text(
        package_dir / "profiles" / "polars-plan.txt",
        plans["polars_native"]["plan_text"],
    )
    _write_text(
        package_dir / "profiles" / "ibis-duckdb.sql",
        plans["ibis_duckdb"]["compiled_sql"],
    )
    _write_text(
        package_dir / "profiles" / "ibis-polars-plan.txt",
        plans["ibis_polars"]["plan_text"],
    )
    _write_csv(
        package_dir / "measurements" / "raw-runs.csv",
        raw_runs,
    )
    _write_csv(
        package_dir / "measurements" / "summary.csv",
        summary,
    )
    _write_json(
        package_dir / "measurements" / "environment.json",
        environment,
    )
    _write_json(
        package_dir / "equivalence" / "output-checks.json",
        {
            "tiny_expected": tiny_check,
            "engine_checks": checks,
            "output_grain_unique": output_grain_unique,
        },
    )
    _write_csv(
        package_dir / "equivalence" / "reconciliation.csv",
        [
            {
                "engine": check["engine"],
                "passed": check["passed"],
                "row_count": check["row_count"],
                "expected_checksum": check["expected_checksum"],
                "actual_checksum": check["actual_checksum"],
                "mismatch_count": check["mismatch_count"],
            }
            for check in checks
        ],
    )
    _write_json(
        package_dir / "equivalence" / "tiny-expected-output.json",
        output_records(tiny_expected),
    )
    _write_json(
        package_dir / "reports" / "portability-audit.json",
        portability,
    )
    _write_text(
        package_dir / "reports" / "portability-audit.md",
        _render_portability_audit(portability),
    )
    _write_json(
        package_dir / "reports" / "engine-decision.json",
        decision,
    )
    _write_text(
        package_dir / "reports" / "engine-decision.md",
        _render_engine_decision(decision),
    )
    _write_text(
        package_dir / "reports" / "limitations.md",
        _limitations_markdown(),
    )

    report = {
        "scenario": benchmark_plan,
        "environment": environment,
        "input": {
            **input_summary,
            "parquet_path": "data/orders.parquet",
            "file_size_bytes": layout["file_size_bytes"],
            "seed": seed,
            "users": resolved_users,
        },
        "equivalence": {
            "tiny_expected": tiny_check,
            "engine_checks": checks,
        },
        "measurements": {
            "raw_runs": raw_runs,
            "summary": summary,
        },
        "plans": {
            name: {
                "checks": detail["checks"],
                "compiled_type": detail.get("compiled_type"),
            }
            for name, detail in plans.items()
        },
        "portability": portability,
        "decision": decision,
        "interpretation": {
            "checks": report_checks,
            "safe_to_ship": all(report_checks.values()),
        },
        "package": {
            "output_dir": str(package_dir),
            "expected_directories": [
                "data-contract",
                "data-layout",
                "pipelines",
                "profiles",
                "measurements",
                "equivalence",
                "reports",
            ],
        },
    }
    _write_json(package_dir / "report.json", report)
    manifest = write_manifest(package_dir)
    manifest_check = validate_manifest(package_dir)
    report["package"]["manifest_files"] = manifest["file_count"]
    report["package"]["manifest_valid"] = manifest_check["valid"]
    report["interpretation"]["checks"]["manifest_valid"] = manifest_check["valid"]
    report["interpretation"]["safe_to_ship"] = all(report["interpretation"]["checks"].values())
    _write_json(package_dir / "report.json", report)
    write_manifest(package_dir)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the final multi-engine performance benchmark package"
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_ROWS),
        default="sample",
    )
    parser.add_argument("--rows", type=int)
    parser.add_argument("--users", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--row-group-size", type=int, default=1_024)
    parser.add_argument("--allow-large", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_performance_benchmark_package(
            dataset_profile=args.profile,
            rows=args.rows,
            users=args.users,
            seed=args.seed,
            repeat=args.repeat,
            warmup=args.warmup,
            row_group_size=args.row_group_size,
            allow_large=args.allow_large,
            output_dir=args.output_dir,
        )
    except PerformancePackageError as error:
        print(f"performance package error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
