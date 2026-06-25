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


class PolarsExpressionError(ValueError):
    """Raised when the Polars expression pipeline cannot produce a valid report."""


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

FORBIDDEN_UDF_PATTERNS = {
    "map_elements": r"\.map_elements\s*\(",
    "map_rows": r"\.map_rows\s*\(",
    "iter_rows": r"\.iter_rows\s*\(",
    "rows": r"\.rows\s*\(",
    "python_apply": r"\.apply\s*\(",
}


def generate_customer_revenue_rows(
    *,
    rows: int = 2_400,
    users: int = 320,
    seed: int = 42,
) -> pd.DataFrame:
    if rows < 128:
        raise PolarsExpressionError("rows must be at least 128")
    if users < 16:
        raise PolarsExpressionError("users must be at least 16")
    if users > rows:
        raise PolarsExpressionError("users must be less than or equal to rows")

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
    gross = rng.integers(399, 60_000, size=rows, dtype=np.int64)
    gross = np.where(status == "trial", 0, gross)
    refund = np.where(
        status == "refunded",
        np.rint(gross * rng.uniform(0.3, 1.0, size=rows)).astype(np.int64),
        0,
    )

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
        }
    )
    return frame.sort_values(["week_index", "order_id"]).reset_index(drop=True)


def validate_input_frame(frame: pd.DataFrame) -> dict[str, Any]:
    missing = sorted(set(REQUIRED_COLUMNS) - set(frame.columns))
    if missing:
        raise PolarsExpressionError(f"required columns are missing: {missing}")
    if frame.empty:
        raise PolarsExpressionError("input frame is empty")
    if frame["order_id"].isna().any() or frame["order_id"].duplicated().any():
        raise PolarsExpressionError("order_id must be non-null and unique")
    for column in ["gross_revenue_cents", "refund_amount_cents", "support_ticket_count"]:
        if (frame[column] < 0).any():
            raise PolarsExpressionError(f"{column} must be non-negative")
    if (frame["refund_amount_cents"] > frame["gross_revenue_cents"]).any():
        raise PolarsExpressionError("refund_amount_cents cannot exceed gross_revenue_cents")
    allowed_statuses = {"paid", "trial", "refunded"}
    unknown_statuses = sorted(set(frame["status"].astype(str)) - allowed_statuses)
    if unknown_statuses:
        raise PolarsExpressionError(f"unknown order statuses: {unknown_statuses}")
    return {
        "rows": int(len(frame)),
        "columns": list(frame.columns),
        "unique_orders": int(frame["order_id"].nunique()),
        "test_user_rows": int(frame["is_test_user"].sum()),
    }


def run_pandas_pipeline(frame: pd.DataFrame) -> pd.DataFrame:
    validate_input_frame(frame)
    prepared = frame.loc[
        frame["week_index"].between(1, 6) & ~frame["is_test_user"],
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
            grouped["net_revenue_cents"] >= 1_200_000,
            grouped["net_revenue_cents"] >= 700_000,
        ],
        ["healthy", "watch"],
        default="weak",
    )
    grouped["week_revenue_rank"] = (
        grouped.groupby("week_start")["net_revenue_cents"]
        .rank(method="dense", ascending=False)
        .astype("int64")
    )
    result = grouped[grouped["week_revenue_rank"] <= 3].copy()
    return normalize_output(result)


def run_polars_expression_pipeline(frame: pd.DataFrame) -> pl.DataFrame:
    validate_input_frame(frame)
    return (
        pl.from_pandas(frame)
        .select(
            [
                pl.col("order_id").cast(pl.Utf8),
                pl.col("user_id").cast(pl.Utf8),
                pl.col("week_index").cast(pl.Int16),
                pl.col("week_start").cast(pl.Utf8),
                pl.col("platform").cast(pl.Utf8),
                pl.col("region").cast(pl.Utf8),
                pl.col("plan").cast(pl.Utf8),
                pl.col("status").cast(pl.Utf8),
                pl.col("gross_revenue_cents").cast(pl.Int64),
                pl.col("refund_amount_cents").cast(pl.Int64),
                pl.col("support_ticket_count").cast(pl.Int64),
                pl.col("active_subscription_days").cast(pl.Int64),
                pl.col("is_test_user").cast(pl.Boolean),
            ]
        )
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
                pl.when(pl.col("net_revenue_cents") >= 1_200_000)
                .then(pl.lit("healthy"))
                .when(pl.col("net_revenue_cents") >= 700_000)
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


def normalize_output(frame: pd.DataFrame | pl.DataFrame) -> pd.DataFrame:
    if isinstance(frame, pl.DataFrame):
        pandas_frame = frame.to_pandas()
    else:
        pandas_frame = frame.copy()
    normalized = pandas_frame[OUTPUT_COLUMNS].copy()
    for column in ["week_start", "platform", "region", "health_band"]:
        normalized[column] = normalized[column].astype("string")
    integer_columns = [
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
    ]
    for column in integer_columns:
        normalized[column] = pd.to_numeric(normalized[column]).astype("Int64")
    return normalized.sort_values(
        ["week_start", "week_revenue_rank", "platform", "region"],
        kind="mergesort",
    ).reset_index(drop=True)


def compare_outputs(pandas_output: pd.DataFrame, polars_output: pl.DataFrame) -> dict[str, Any]:
    expected = normalize_output(pandas_output)
    observed = normalize_output(polars_output)
    matches = expected.equals(observed)
    diff_preview: list[dict[str, Any]] = []
    if not matches:
        diff = observed.merge(
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
        "polars_rows": int(len(observed)),
        "result_preview": _records(observed.head(12)),
        "diff_preview": diff_preview,
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def audit_expression_source(source_text: str) -> dict[str, Any]:
    context_counts = {
        "select": len(re.findall(r"\.select\s*\(", source_text)),
        "with_columns": len(re.findall(r"\.with_columns\s*\(", source_text)),
        "filter": len(re.findall(r"\.filter\s*\(", source_text)),
        "group_by": len(re.findall(r"\.group_by\s*\(", source_text)),
    }
    forbidden = [
        {"name": name, "pattern": pattern}
        for name, pattern in FORBIDDEN_UDF_PATTERNS.items()
        if re.search(pattern, source_text)
    ]
    return {
        "contexts": context_counts,
        "required_contexts_present": all(count > 0 for count in context_counts.values()),
        "forbidden_python_udf_usages": forbidden,
        "row_wise_python_detected": bool(forbidden),
        "uses_polars_expressions": all(count > 0 for count in context_counts.values()) and not forbidden,
    }


def audit_artifact_expression_pipeline() -> dict[str, Any]:
    return audit_expression_source(inspect.getsource(run_polars_expression_pipeline))


def build_polars_expression_report(
    *,
    rows: int = 2_400,
    users: int = 320,
    seed: int = 42,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    frame = generate_customer_revenue_rows(rows=rows, users=users, seed=seed)
    input_summary = validate_input_frame(frame)
    pandas_output = run_pandas_pipeline(frame)
    polars_output = run_polars_expression_pipeline(frame)
    comparison = compare_outputs(pandas_output, polars_output)
    expression_audit = audit_artifact_expression_pipeline()
    schema = {
        "input": {column: str(dtype) for column, dtype in frame.dtypes.items()},
        "polars_output": {name: str(dtype) for name, dtype in polars_output.schema.items()},
        "output_columns": OUTPUT_COLUMNS,
    }
    interpretation_checks = {
        "input_contract_valid": input_summary["rows"] == rows,
        "required_contexts_present": expression_audit["required_contexts_present"],
        "no_row_wise_python_udf": not expression_audit["row_wise_python_detected"],
        "result_matches_pandas": comparison["matches_pandas"],
        "output_grain_unique": not normalize_output(polars_output)[
            ["week_start", "platform", "region"]
        ].duplicated().any(),
    }
    report = {
        "scenario": {
            "scenario_id": "polars-expression-equivalence",
            "pipeline_name": "customer_revenue_health_weekly_top_regions",
            "rows": int(rows),
            "users": int(users),
            "seed": int(seed),
            "engine": "polars",
            "polars_version": pl.__version__,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "input": input_summary,
        "schema": schema,
        "expression_audit": expression_audit,
        "equivalence": comparison,
        "interpretation": {
            "checks": interpretation_checks,
            "safe_to_ship": all(interpretation_checks.values()),
            "notes": [
                "This lesson uses eager Polars expressions; lazy optimization is handled in 12/08.",
                "The pipeline is expression-based because select, with_columns, filter and group_by contexts are present.",
                "Row-wise Python UDF patterns are blocked because they bypass the Polars expression engine.",
            ],
        },
    }
    if output_dir is not None:
        package_dir = Path(output_dir)
        package_dir.mkdir(parents=True, exist_ok=True)
        normalize_output(polars_output).to_csv(package_dir / "polars-output.csv", index=False)
        normalize_output(pandas_output).to_csv(package_dir / "pandas-control.csv", index=False)
        (package_dir / "expression-audit.json").write_text(
            json.dumps(expression_audit, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (package_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        report["package"] = {
            "output_dir": str(package_dir),
            "files": [
                "polars-output.csv",
                "pandas-control.csv",
                "expression-audit.json",
                "report.json",
            ],
        }
        (package_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Polars expression pipeline equivalence report")
    parser.add_argument("--rows", type=int, default=2_400)
    parser.add_argument("--users", type=int, default=320)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_polars_expression_report(
            rows=args.rows,
            users=args.users,
            seed=args.seed,
            output_dir=args.output_dir,
        )
    except PolarsExpressionError as error:
        print(f"polars expression error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
