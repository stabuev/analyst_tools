from __future__ import annotations

import argparse
import inspect
import json
import platform
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq


class PolarsLazyPlanError(ValueError):
    """Raised when the Polars lazy plan audit cannot produce a valid report."""


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

OUTPUT_COLUMNS = [
    "week_start",
    "platform",
    "region",
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
    "week_revenue_rank",
]

FORBIDDEN_PATTERNS = {
    "early_collect": r"\.collect\s*\(",
    "map_elements": r"\.map_elements\s*\(",
    "map_rows": r"\.map_rows\s*\(",
    "iter_rows": r"\.iter_rows\s*\(",
    "read_parquet": r"pl\.read_parquet\s*\(",
}


def generate_customer_revenue_rows(
    *,
    rows: int = 4_800,
    users: int = 640,
    seed: int = 42,
) -> pd.DataFrame:
    if rows < 256:
        raise PolarsLazyPlanError("rows must be at least 256")
    if users < 32:
        raise PolarsLazyPlanError("users must be at least 32")
    if users > rows:
        raise PolarsLazyPlanError("users must be less than or equal to rows")

    rng = np.random.default_rng(seed)
    index = np.arange(rows, dtype=np.int64)
    user_ids = np.array([f"U{position:07d}" for position in range(users)], dtype=object)
    platforms = np.array(["web", "ios", "android"], dtype=object)
    regions = np.array(["ru", "kz", "am", "tr"], dtype=object)
    plans = np.array(["trial", "basic", "plus", "pro"], dtype=object)
    statuses = np.array(["paid", "paid", "paid", "trial", "refunded"], dtype=object)
    week_index = (index % 8).astype(np.int16)
    base_week = pd.Timestamp("2026-01-05")
    week_start = [
        (base_week + pd.Timedelta(days=int(position) * 7)).date().isoformat()
        for position in week_index
    ]
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
            "week_start": week_start,
            "platform": platforms[(index * 13) % len(platforms)],
            "region": regions[(index * 17) % len(regions)],
            "plan": plans[rng.integers(0, len(plans), size=rows)],
            "status": status,
            "gross_revenue_cents": gross.astype(np.int64),
            "refund_amount_cents": refund.astype(np.int64),
            "support_ticket_count": rng.poisson(0.18, size=rows).astype(np.int64),
            "active_subscription_days": rng.integers(0, 8, size=rows, dtype=np.int64),
            "is_test_user": (index % 113 == 0),
            "debug_payload": [
                "trace="
                + str(int(value))
                + ";stage=polars-lazy;wide-column-for-projection"
                for value in payload_ids
            ],
            "raw_event_json": [
                (
                    '{"source":"lesson","event_id":"evt-'
                    + str(int(value))
                    + '","attributes":"unused-wide-column"}'
                )
                for value in payload_ids
            ],
        }
    )
    return frame.sort_values(["week_index", "order_id"]).reset_index(drop=True)


def validate_input_frame(frame: pd.DataFrame) -> dict[str, Any]:
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise PolarsLazyPlanError(f"required columns are missing: {missing}")
    if frame.empty:
        raise PolarsLazyPlanError("input frame is empty")
    if frame["order_id"].isna().any() or frame["order_id"].duplicated().any():
        raise PolarsLazyPlanError("order_id must be non-null and unique")
    for column in ["gross_revenue_cents", "refund_amount_cents", "support_ticket_count"]:
        if (frame[column] < 0).any():
            raise PolarsLazyPlanError(f"{column} must be non-negative")
    if (frame["refund_amount_cents"] > frame["gross_revenue_cents"]).any():
        raise PolarsLazyPlanError("refund_amount_cents cannot exceed gross_revenue_cents")
    return {
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "unique_orders": int(frame["order_id"].nunique()),
        "wide_unused_columns": ["debug_payload", "raw_event_json"],
    }


def write_parquet_input(
    frame: pd.DataFrame,
    output_dir: str | Path,
    *,
    row_group_size: int = 256,
) -> Path:
    if row_group_size <= 0:
        raise PolarsLazyPlanError("row_group_size must be positive")
    validate_input_frame(frame)
    output_path = Path(output_dir) / "data" / "orders.parquet"
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


def build_lazy_scan_pipeline(parquet_path: str | Path) -> pl.LazyFrame:
    return (
        pl.scan_parquet(parquet_path)
        .with_columns(
            [
                (pl.col("gross_revenue_cents") - pl.col("refund_amount_cents")).alias(
                    "net_revenue_cents"
                ),
                (
                    (pl.col("status") == "paid")
                    & (pl.col("gross_revenue_cents") > 0)
                )
                .cast(pl.Int64)
                .alias("paid_order"),
            ]
        )
        .filter(
            pl.col("week_index").is_between(1, 6)
            & (pl.col("region") != "tr")
            & (~pl.col("is_test_user"))
        )
        .group_by(["week_start", "platform", "region"])
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
                        pl.col("refund_amount_cents") * 10_000
                        / pl.col("gross_revenue_cents")
                    )
                    .round(0)
                    .cast(pl.Int64)
                )
                .otherwise(None)
                .alias("refund_rate_bp"),
            ]
        )
        .with_columns(
            [
                pl.when(pl.col("net_revenue_cents") >= 2_400_000)
                .then(pl.lit("healthy"))
                .when(pl.col("net_revenue_cents") >= 1_400_000)
                .then(pl.lit("watch"))
                .otherwise(pl.lit("weak"))
                .alias("health_band"),
                pl.col("net_revenue_cents")
                .rank(method="dense", descending=True)
                .over("week_start")
                .cast(pl.Int64)
                .alias("week_revenue_rank"),
            ]
        )
        .filter(pl.col("week_revenue_rank") <= 3)
        .select(OUTPUT_COLUMNS)
        .sort(["week_start", "week_revenue_rank", "platform", "region"])
    )


def run_pandas_control(frame: pd.DataFrame) -> pd.DataFrame:
    validate_input_frame(frame)
    prepared = frame.loc[
        frame["week_index"].between(1, 6)
        & (frame["region"] != "tr")
        & ~frame["is_test_user"],
        REQUIRED_COLUMNS,
    ].copy()
    prepared["net_revenue_cents"] = (
        prepared["gross_revenue_cents"] - prepared["refund_amount_cents"]
    )
    prepared["paid_order"] = (
        (prepared["status"] == "paid") & (prepared["gross_revenue_cents"] > 0)
    ).astype("int64")
    grouped = (
        prepared.groupby(["week_start", "platform", "region"], as_index=False)
        .agg(
            orders=("order_id", "nunique"),
            paid_orders=("paid_order", "sum"),
            gross_revenue_cents=("gross_revenue_cents", "sum"),
            refund_amount_cents=("refund_amount_cents", "sum"),
            net_revenue_cents=("net_revenue_cents", "sum"),
            support_ticket_count=("support_ticket_count", "sum"),
            active_subscription_days=("active_subscription_days", "sum"),
        )
    )
    grouped["revenue_per_paid_order_cents"] = np.where(
        grouped["paid_orders"] > 0,
        grouped["net_revenue_cents"] // grouped["paid_orders"],
        pd.NA,
    )
    grouped["refund_rate_bp"] = np.where(
        grouped["gross_revenue_cents"] > 0,
        np.rint(grouped["refund_amount_cents"] * 10_000 / grouped["gross_revenue_cents"]),
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
    grouped["week_revenue_rank"] = (
        grouped.groupby("week_start")["net_revenue_cents"]
        .rank(method="dense", ascending=False)
        .astype("int64")
    )
    return normalize_output(grouped[grouped["week_revenue_rank"] <= 3])


def normalize_output(frame: pd.DataFrame | pl.DataFrame) -> pd.DataFrame:
    pandas_frame = frame.to_pandas() if isinstance(frame, pl.DataFrame) else frame.copy()
    normalized = pandas_frame[OUTPUT_COLUMNS].copy()
    for column in ["week_start", "platform", "region", "health_band"]:
        normalized[column] = normalized[column].astype("string")
    for column in [
        "orders",
        "paid_orders",
        "gross_revenue_cents",
        "refund_amount_cents",
        "net_revenue_cents",
        "support_ticket_count",
        "active_subscription_days",
        "revenue_per_paid_order_cents",
        "refund_rate_bp",
        "week_revenue_rank",
    ]:
        normalized[column] = pd.to_numeric(normalized[column]).astype("Int64")
    return normalized.sort_values(
        ["week_start", "week_revenue_rank", "platform", "region"],
        kind="mergesort",
    ).reset_index(drop=True)


def compare_outputs(control: pd.DataFrame, observed: pl.DataFrame) -> dict[str, Any]:
    expected = normalize_output(control)
    actual = normalize_output(observed)
    matches = expected.equals(actual)
    diff_preview: list[dict[str, Any]] = []
    if not matches:
        diff = actual.merge(
            expected,
            on=["week_start", "platform", "region", "week_revenue_rank"],
            how="outer",
            suffixes=("_polars", "_pandas"),
            indicator=True,
        )
        diff_preview = _records(diff.head(10))
    return {
        "matches_pandas": bool(matches),
        "pandas_rows": int(len(expected)),
        "polars_rows": int(len(actual)),
        "result_preview": _records(actual.head(12)),
        "diff_preview": diff_preview,
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def explain_lazy_frame(lazy_frame: pl.LazyFrame) -> dict[str, str]:
    return {
        "unoptimized": lazy_frame.explain(optimized=False),
        "optimized": lazy_frame.explain(optimized=True),
    }


def _parse_project_columns(plan_text: str) -> dict[str, Any]:
    match = re.search(r"PROJECT\s+(\d+)/(\d+)\s+COLUMNS", plan_text)
    if match:
        selected = int(match.group(1))
        total = int(match.group(2))
        return {
            "selected_columns": selected,
            "total_columns": total,
            "reduced": selected < total,
            "raw": match.group(0),
        }
    all_match = re.search(r"PROJECT\s+\*/(\d+)\s+COLUMNS", plan_text)
    if all_match:
        total = int(all_match.group(1))
        return {
            "selected_columns": total,
            "total_columns": total,
            "reduced": False,
            "raw": all_match.group(0),
        }
    return {"selected_columns": None, "total_columns": None, "reduced": False, "raw": None}


def audit_source_text(source_text: str) -> dict[str, Any]:
    findings = [
        {"name": name, "pattern": pattern}
        for name, pattern in FORBIDDEN_PATTERNS.items()
        if re.search(pattern, source_text)
    ]
    return {
        "forbidden_patterns": findings,
        "early_materialization_detected": any(
            finding["name"] in {"early_collect", "read_parquet"}
            for finding in findings
        ),
        "python_udf_detected": any(
            finding["name"] in {"map_elements", "map_rows", "iter_rows"}
            for finding in findings
        ),
        "safe_lazy_source": not findings,
    }


def audit_lazy_pipeline_source() -> dict[str, Any]:
    return audit_source_text(inspect.getsource(build_lazy_scan_pipeline))


def audit_plans(plans: dict[str, str]) -> dict[str, Any]:
    optimized = plans["optimized"]
    unoptimized = plans["unoptimized"]
    optimized_project = _parse_project_columns(optimized)
    unoptimized_project = _parse_project_columns(unoptimized)
    selection_match = re.search(r"SELECTION:\s*(.+)", optimized)
    selection_text = selection_match.group(1).strip() if selection_match else ""
    return {
        "has_parquet_scan": "PARQUET SCAN" in optimized.upper(),
        "unoptimized_reads_all_columns": bool(unoptimized_project["raw"])
        and not unoptimized_project["reduced"],
        "optimized_projection_pushdown": optimized_project,
        "optimized_has_selection_at_scan": bool(selection_match),
        "selection_text": selection_text,
        "selection_mentions_expected_filters": all(
            token in selection_text
            for token in ["week_index", "region", "is_test_user"]
        ),
        "has_aggregate": "AGGREGATE" in optimized.upper(),
        "has_rank": "rank" in optimized.lower(),
        "has_final_sort": "SORT BY" in optimized.upper(),
    }


def build_polars_lazy_plan_audit(
    *,
    rows: int = 4_800,
    users: int = 640,
    seed: int = 42,
    row_group_size: int = 256,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    if output_dir is None:
        raise PolarsLazyPlanError("output_dir is required so scan_parquet has a stable file path")
    package_dir = Path(output_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    frame = generate_customer_revenue_rows(rows=rows, users=users, seed=seed)
    input_summary = validate_input_frame(frame)
    parquet_path = write_parquet_input(frame, package_dir, row_group_size=row_group_size)
    lazy_frame = build_lazy_scan_pipeline(parquet_path)
    plans = explain_lazy_frame(lazy_frame)
    plan_audit = audit_plans(plans)
    source_audit = audit_lazy_pipeline_source()
    polars_output = lazy_frame.collect()
    pandas_control = run_pandas_control(frame)
    equivalence = compare_outputs(pandas_control, polars_output)
    output = normalize_output(polars_output)
    checks = {
        "lazy_source_has_no_early_collect": not source_audit["early_materialization_detected"],
        "lazy_source_has_no_python_udf": not source_audit["python_udf_detected"],
        "parquet_scan_present": plan_audit["has_parquet_scan"],
        "projection_pushdown_confirmed": bool(plan_audit["optimized_projection_pushdown"]["reduced"]),
        "predicate_pushdown_confirmed": plan_audit["optimized_has_selection_at_scan"]
        and plan_audit["selection_mentions_expected_filters"],
        "aggregate_and_rank_present": plan_audit["has_aggregate"] and plan_audit["has_rank"],
        "result_matches_pandas": equivalence["matches_pandas"],
        "output_grain_unique": not output[["week_start", "platform", "region"]].duplicated().any(),
    }
    report = {
        "scenario": {
            "scenario_id": "polars-lazy-plan-audit",
            "pipeline_name": "customer_revenue_health_weekly_lazy_top_regions",
            "rows": int(rows),
            "users": int(users),
            "seed": int(seed),
            "row_group_size": int(row_group_size),
            "engine": "polars-lazy",
            "polars_version": pl.__version__,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "input": input_summary,
        "package": {
            "output_dir": str(package_dir),
            "input_parquet": str(parquet_path.relative_to(package_dir)),
        },
        "plans": plans,
        "plan_audit": plan_audit,
        "source_audit": source_audit,
        "equivalence": equivalence,
        "interpretation": {
            "checks": checks,
            "safe_to_ship": all(checks.values()),
            "notes": [
                "Lazy execution postpones work until collect, allowing projection and predicate pushdown at scan.",
                "The optimized plan must be read, not assumed from method chaining.",
                "Early collect and Python UDF patterns are treated as optimization blockers by policy.",
            ],
        },
    }
    output.to_csv(package_dir / "polars-lazy-output.csv", index=False)
    normalize_output(pandas_control).to_csv(package_dir / "pandas-control.csv", index=False)
    (package_dir / "optimized-plan.txt").write_text(plans["optimized"] + "\n", encoding="utf-8")
    (package_dir / "unoptimized-plan.txt").write_text(plans["unoptimized"] + "\n", encoding="utf-8")
    (package_dir / "plan-audit.json").write_text(
        json.dumps(plan_audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report["package"]["files"] = [
        "data/orders.parquet",
        "polars-lazy-output.csv",
        "pandas-control.csv",
        "optimized-plan.txt",
        "unoptimized-plan.txt",
        "plan-audit.json",
        "report.json",
    ]
    (package_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an optimized Polars lazy plan audit")
    parser.add_argument("--rows", type=int, default=4_800)
    parser.add_argument("--users", type=int, default=640)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--row-group-size", type=int, default=256)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_polars_lazy_plan_audit(
            rows=args.rows,
            users=args.users,
            seed=args.seed,
            row_group_size=args.row_group_size,
            output_dir=args.output_dir,
        )
    except PolarsLazyPlanError as error:
        print(f"polars lazy plan error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
