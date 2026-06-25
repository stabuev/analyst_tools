from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class DtypePolicyError(ValueError):
    """Raised when a dtype optimization would change data semantics."""


CATEGORY_DOMAINS: dict[str, list[str]] = {
    "platform": ["web", "ios", "android"],
    "acquisition_channel": ["organic", "paid_search", "partner", "email"],
    "region": ["ru", "kz", "am", "tr"],
    "plan": ["free", "trial", "basic", "plus", "pro"],
}
IDENTIFIER_COLUMNS = {"order_id", "user_id"}
TIMESTAMP_COLUMNS = {"week_start"}
BOOLEAN_COLUMNS = {"activated_7d"}
UNSIGNED_INTEGER_COLUMNS = {
    "line_number",
    "paid_orders",
    "gross_revenue_cents",
    "refund_amount_cents",
    "active_subscription_days",
    "support_ticket_count",
    "first_paid_order_age_days",
}
SIGNED_INTEGER_COLUMNS = {"net_revenue_cents"}
MONEY_COLUMNS = ["gross_revenue_cents", "refund_amount_cents", "net_revenue_cents"]
NULLABLE_COLUMNS = {"first_paid_order_age_days", "activated_7d"}
SOURCE_GRAIN = ["order_id", "line_number"]
UNSIGNED_DTYPES = ["UInt8", "UInt16", "UInt32", "UInt64"]
SIGNED_DTYPES = ["Int8", "Int16", "Int32", "Int64"]


class ColumnPolicy:
    def __init__(
        self,
        *,
        column: str,
        role: str,
        source_dtype: str,
        target_dtype: str,
        nullable: bool,
        reason: str,
        semantic_checks: tuple[str, ...],
        source_memory_bytes: int,
        target_memory_bytes: int | None = None,
    ) -> None:
        self.column = column
        self.role = role
        self.source_dtype = source_dtype
        self.target_dtype = target_dtype
        self.nullable = nullable
        self.reason = reason
        self.semantic_checks = semantic_checks
        self.source_memory_bytes = source_memory_bytes
        self.target_memory_bytes = target_memory_bytes

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "role": self.role,
            "source_dtype": self.source_dtype,
            "target_dtype": self.target_dtype,
            "nullable": self.nullable,
            "reason": self.reason,
            "semantic_checks": list(self.semantic_checks),
            "source_memory_bytes": self.source_memory_bytes,
            "target_memory_bytes": self.target_memory_bytes,
        }


def generate_revenue_extract(rows: int, seed: int) -> pd.DataFrame:
    if rows <= 0:
        raise DtypePolicyError("rows must be positive")

    rng = np.random.default_rng(seed)
    index = np.arange(rows)
    platforms = np.array(CATEGORY_DOMAINS["platform"], dtype=object)
    channels = np.array(CATEGORY_DOMAINS["acquisition_channel"], dtype=object)
    regions = np.array(CATEGORY_DOMAINS["region"], dtype=object)
    plans = np.array(CATEGORY_DOMAINS["plan"], dtype=object)

    unit_price = rng.integers(199, 40_000, size=rows, dtype=np.int64)
    quantity = rng.integers(1, 5, size=rows, dtype=np.int64)
    paid_orders = rng.binomial(1, 0.72, size=rows).astype(np.int64)
    gross = (unit_price * quantity * paid_orders).astype(np.int64)
    refund_flag = rng.random(rows) < 0.08
    refund_multiplier = rng.uniform(0.2, 1.25, size=rows)
    refunds = np.where(refund_flag, np.rint(gross * refund_multiplier).astype(np.int64), 0)
    net = gross - refunds
    first_paid_age = rng.integers(0, 365, size=rows, dtype=np.int64)
    first_paid_age_values: list[int | None] = [
        int(value) if paid_orders[position] else None
        for position, value in enumerate(first_paid_age)
    ]
    activated_roll = rng.random(rows)
    activated_values: list[bool | None] = [
        None if value < 0.05 else bool(value < 0.73)
        for value in activated_roll
    ]
    base_week = pd.Timestamp("2026-01-05", tz="UTC")
    week_values = [
        (base_week + pd.Timedelta(days=int((position % 12) * 7))).isoformat()
        for position in range(rows)
    ]

    return pd.DataFrame(
        {
            "order_id": [f"O{position // 3:08d}" for position in index],
            "line_number": (index % 3 + 1).astype(np.int64),
            "user_id": [
                f"U{int(value):07d}"
                for value in rng.integers(1, max(2, rows // 2), size=rows)
            ],
            "week_start": week_values,
            "platform": platforms[index % len(platforms)],
            "acquisition_channel": channels[rng.integers(0, len(channels), size=rows)],
            "region": regions[rng.integers(0, len(regions), size=rows)],
            "plan": plans[rng.integers(0, len(plans), size=rows)],
            "paid_orders": paid_orders,
            "gross_revenue_cents": gross,
            "refund_amount_cents": refunds,
            "net_revenue_cents": net,
            "active_subscription_days": rng.integers(0, 8, size=rows, dtype=np.int64),
            "support_ticket_count": rng.poisson(0.18, size=rows).astype(np.int64),
            "first_paid_order_age_days": first_paid_age_values,
            "activated_7d": activated_values,
        }
    )


def dataframe_memory(frame: pd.DataFrame) -> dict[str, Any]:
    usage = frame.memory_usage(index=True, deep=True)
    total = int(usage.sum())
    columns: list[dict[str, Any]] = []
    for name, bytes_used in usage.items():
        column_name = str(name)
        dtype = "index" if column_name == "Index" else str(frame[column_name].dtype)
        columns.append(
            {
                "column": column_name,
                "dtype": dtype,
                "bytes": int(bytes_used),
                "share": float(bytes_used / total) if total else 0.0,
            }
        )
    columns.sort(key=lambda row: row["bytes"], reverse=True)
    return {"total_bytes": total, "columns": columns}


def _column_memory(frame: pd.DataFrame, column: str) -> int:
    return int(frame[[column]].memory_usage(index=False, deep=True).sum())


def _integer_info(dtype_name: str) -> np.iinfo:
    return np.iinfo(np.dtype(dtype_name.lower()))


def _integer_bounds(series: pd.Series, column: str) -> tuple[int, int]:
    numeric = pd.to_numeric(series, errors="raise")
    non_null = numeric.dropna()
    if non_null.empty:
        return 0, 0
    values = non_null.to_numpy(dtype="float64")
    if not np.all(np.equal(values, np.trunc(values))):
        raise DtypePolicyError(f"{column} contains fractional values; integer dtype is unsafe")
    return int(values.min()), int(values.max())


def choose_integer_dtype(series: pd.Series, *, signed: bool, column: str) -> str:
    minimum, maximum = _integer_bounds(series, column)
    candidates = SIGNED_DTYPES if signed or minimum < 0 else UNSIGNED_DTYPES
    if minimum < 0 and not signed:
        raise DtypePolicyError(f"{column} contains negative values; unsigned dtype is unsafe")
    for dtype_name in candidates:
        info = _integer_info(dtype_name)
        if info.min <= minimum and maximum <= info.max:
            return dtype_name
    raise DtypePolicyError(f"{column} does not fit supported integer policy")


def _validate_category_values(series: pd.Series, column: str) -> None:
    allowed = set(CATEGORY_DOMAINS[column])
    observed = set(series.dropna().astype(str).unique())
    unknown = sorted(observed - allowed)
    if unknown:
        raise DtypePolicyError(f"{column} has unknown categories: {unknown}")


def build_dtype_policy(
    frame: pd.DataFrame,
    *,
    category_threshold: float = 0.5,
) -> list[ColumnPolicy]:
    if not 0 < category_threshold <= 1:
        raise DtypePolicyError("category_threshold must be between 0 and 1")

    policies: list[ColumnPolicy] = []
    row_count = max(len(frame), 1)
    for column in frame.columns:
        source_dtype = str(frame[column].dtype)
        source_memory = _column_memory(frame, column)
        nullable = column in NULLABLE_COLUMNS or bool(frame[column].isna().any())

        if column in IDENTIFIER_COLUMNS:
            policy = ColumnPolicy(
                column=column,
                role="identifier",
                source_dtype=source_dtype,
                target_dtype="string[pyarrow]",
                nullable=nullable,
                reason="high-cardinality identifiers stay strings, not categories",
                semantic_checks=("values_preserved", "missing_count_preserved"),
                source_memory_bytes=source_memory,
            )
        elif column in CATEGORY_DOMAINS:
            _validate_category_values(frame[column], column)
            cardinality_ratio = frame[column].nunique(dropna=True) / row_count
            if cardinality_ratio <= category_threshold:
                target_dtype = "category"
                reason = "low-cardinality dimension with explicit allowed categories"
            else:
                target_dtype = "string[pyarrow]"
                reason = "cardinality is too high for category under the policy threshold"
            policy = ColumnPolicy(
                column=column,
                role="dimension",
                source_dtype=source_dtype,
                target_dtype=target_dtype,
                nullable=nullable,
                reason=reason,
                semantic_checks=("allowed_categories", "values_preserved", "missing_count_preserved"),
                source_memory_bytes=source_memory,
            )
        elif column in TIMESTAMP_COLUMNS:
            policy = ColumnPolicy(
                column=column,
                role="timestamp",
                source_dtype=source_dtype,
                target_dtype="datetime64[ns, UTC]",
                nullable=nullable,
                reason="timestamps need timezone-aware datetime semantics",
                semantic_checks=("utc_timezone", "values_preserved", "missing_count_preserved"),
                source_memory_bytes=source_memory,
            )
        elif column in BOOLEAN_COLUMNS:
            policy = ColumnPolicy(
                column=column,
                role="nullable_boolean",
                source_dtype=source_dtype,
                target_dtype="boolean",
                nullable=True,
                reason="nullable boolean preserves unknown separately from False",
                semantic_checks=("values_preserved", "missing_count_preserved"),
                source_memory_bytes=source_memory,
            )
        elif column in SIGNED_INTEGER_COLUMNS:
            target_dtype = choose_integer_dtype(frame[column], signed=True, column=column)
            policy = ColumnPolicy(
                column=column,
                role="signed_integer",
                source_dtype=source_dtype,
                target_dtype=target_dtype,
                nullable=nullable,
                reason="signed integer range check protects negative net revenue",
                semantic_checks=("integer_bounds", "sum_preserved", "missing_count_preserved"),
                source_memory_bytes=source_memory,
            )
        elif column in UNSIGNED_INTEGER_COLUMNS:
            target_dtype = choose_integer_dtype(frame[column], signed=False, column=column)
            policy = ColumnPolicy(
                column=column,
                role="unsigned_integer",
                source_dtype=source_dtype,
                target_dtype=target_dtype,
                nullable=nullable,
                reason="non-negative integer range check chooses the smallest safe dtype",
                semantic_checks=("integer_bounds", "sum_preserved", "missing_count_preserved"),
                source_memory_bytes=source_memory,
            )
        else:
            policy = ColumnPolicy(
                column=column,
                role="unclassified",
                source_dtype=source_dtype,
                target_dtype=source_dtype,
                nullable=nullable,
                reason="no optimization rule declared",
                semantic_checks=("values_preserved",),
                source_memory_bytes=source_memory,
            )
        policies.append(policy)
    return policies


def _cast_integer(series: pd.Series, target_dtype: str, column: str) -> pd.Series:
    _integer_bounds(series, column)
    numeric = pd.to_numeric(series, errors="raise")
    return numeric.astype(target_dtype)


def apply_dtype_policy(frame: pd.DataFrame, policies: list[ColumnPolicy]) -> pd.DataFrame:
    optimized = frame.copy()
    for policy in policies:
        column = policy.column
        if policy.target_dtype == "category":
            _validate_category_values(optimized[column], column)
            optimized[column] = pd.Categorical(
                optimized[column],
                categories=CATEGORY_DOMAINS[column],
            )
        elif policy.target_dtype == "datetime64[ns, UTC]":
            optimized[column] = pd.to_datetime(optimized[column], utc=True, errors="raise")
        elif policy.target_dtype == "boolean":
            optimized[column] = optimized[column].astype("boolean")
        elif policy.target_dtype.startswith(("UInt", "Int")):
            optimized[column] = _cast_integer(optimized[column], policy.target_dtype, column)
        elif policy.target_dtype == "string[pyarrow]":
            optimized[column] = optimized[column].astype("string[pyarrow]")
        elif policy.target_dtype != policy.source_dtype:
            optimized[column] = optimized[column].astype(policy.target_dtype)
    return optimized


def semantic_checks(source: pd.DataFrame, optimized: pd.DataFrame) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add_check(check_id: str, passed: bool, message: str, evidence: dict[str, Any]) -> None:
        checks.append(
            {
                "id": check_id,
                "passed": bool(passed),
                "message": message,
                "evidence": evidence,
            }
        )

    duplicate_count = int(source.duplicated(SOURCE_GRAIN).sum())
    add_check(
        "source_grain_unique",
        duplicate_count == 0,
        "source grain order_id,line_number must be unique",
        {"duplicate_count": duplicate_count},
    )
    add_check(
        "row_count_preserved",
        len(source) == len(optimized),
        "dtype optimization must not filter rows",
        {"source_rows": len(source), "optimized_rows": len(optimized)},
    )

    for column in sorted(IDENTIFIER_COLUMNS):
        source_values = source[column].astype("string").fillna("<NA>").tolist()
        optimized_values = optimized[column].astype("string").fillna("<NA>").tolist()
        add_check(
            f"{column}_values_preserved",
            source_values == optimized_values,
            f"{column} values must stay byte-for-byte equivalent as labels",
            {"changed": source_values != optimized_values},
        )

    for column in MONEY_COLUMNS:
        source_total = int(pd.to_numeric(source[column], errors="raise").sum())
        optimized_total = int(pd.to_numeric(optimized[column], errors="raise").sum())
        add_check(
            f"{column}_sum_preserved",
            source_total == optimized_total,
            f"{column} total must stay exact after dtype change",
            {"source_total": source_total, "optimized_total": optimized_total},
        )
        add_check(
            f"{column}_not_float",
            "float" not in str(optimized[column].dtype).lower(),
            f"{column} must remain integer cents, not floating money",
            {"optimized_dtype": str(optimized[column].dtype)},
        )

    for column in sorted(NULLABLE_COLUMNS):
        source_missing = int(source[column].isna().sum())
        optimized_missing = int(optimized[column].isna().sum())
        add_check(
            f"{column}_missing_count_preserved",
            source_missing == optimized_missing,
            f"{column} missing values must keep the same semantics",
            {"source_missing": source_missing, "optimized_missing": optimized_missing},
        )

    for column, categories in CATEGORY_DOMAINS.items():
        observed = set(optimized[column].dropna().astype(str).unique())
        unknown = sorted(observed - set(categories))
        add_check(
            f"{column}_allowed_categories",
            not unknown,
            f"{column} must stay inside declared category domain",
            {"unknown": unknown, "categories": categories},
        )

    week_dtype = str(optimized["week_start"].dtype)
    week_tz = str(optimized["week_start"].dt.tz)
    add_check(
        "week_start_utc_timezone",
        week_tz == "UTC",
        "week_start must be timezone-aware UTC datetime",
        {"optimized_dtype": week_dtype, "timezone": week_tz},
    )
    return checks


def _fail_on_broken_checks(checks: list[dict[str, Any]]) -> None:
    failed = [check["id"] for check in checks if not check["passed"]]
    if failed:
        raise DtypePolicyError(f"semantic checks failed: {failed}")


def attach_target_memory(
    policies: list[ColumnPolicy],
    optimized: pd.DataFrame,
) -> list[ColumnPolicy]:
    return [
        ColumnPolicy(
            column=policy.column,
            role=policy.role,
            source_dtype=policy.source_dtype,
            target_dtype=policy.target_dtype,
            nullable=policy.nullable,
            reason=policy.reason,
            semantic_checks=policy.semantic_checks,
            source_memory_bytes=policy.source_memory_bytes,
            target_memory_bytes=_column_memory(optimized, policy.column),
        )
        for policy in policies
    ]


def memory_budget_status(optimized_bytes: int, memory_budget_mb: float) -> dict[str, Any]:
    if memory_budget_mb <= 0:
        raise DtypePolicyError("memory_budget_mb must be positive")
    budget_bytes = int(memory_budget_mb * 1024 * 1024)
    if optimized_bytes > budget_bytes:
        severity = "block"
        message = "optimized DataFrame exceeds the memory budget"
    elif optimized_bytes > budget_bytes * 0.7:
        severity = "watch"
        message = "optimized DataFrame is close to the memory budget"
    else:
        severity = "info"
        message = "optimized DataFrame is within the memory budget"
    return {
        "memory_budget_mb": memory_budget_mb,
        "budget_bytes": budget_bytes,
        "optimized_bytes": optimized_bytes,
        "passed": optimized_bytes <= budget_bytes,
        "severity": severity,
        "message": message,
    }


def optimize_dataframe(
    frame: pd.DataFrame,
    *,
    memory_budget_mb: float,
    category_threshold: float = 0.5,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    policies = build_dtype_policy(frame, category_threshold=category_threshold)
    optimized = apply_dtype_policy(frame, policies)
    checks = semantic_checks(frame, optimized)
    _fail_on_broken_checks(checks)

    baseline_memory = dataframe_memory(frame)
    optimized_memory = dataframe_memory(optimized)
    policies = attach_target_memory(policies, optimized)
    reduction_ratio = (
        optimized_memory["total_bytes"] / baseline_memory["total_bytes"]
        if baseline_memory["total_bytes"]
        else 1.0
    )
    budget = memory_budget_status(optimized_memory["total_bytes"], memory_budget_mb)
    largest_baseline = baseline_memory["columns"][0] if baseline_memory["columns"] else {}
    largest_optimized = optimized_memory["columns"][0] if optimized_memory["columns"] else {}

    report = {
        "scenario": {
            "scenario_id": "dtype-policy-memory-plan",
            "pipeline_name": "customer_revenue_health_weekly",
            "rows": int(len(frame)),
            "columns": list(frame.columns),
            "memory_budget_mb": memory_budget_mb,
            "category_threshold": category_threshold,
        },
        "environment": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "pandas_version": pd.__version__,
            "numpy_version": np.__version__,
            "platform": platform.platform(),
        },
        "baseline": baseline_memory,
        "optimized": {
            **optimized_memory,
            "dtypes": {column: str(dtype) for column, dtype in optimized.dtypes.items()},
            "reduction_ratio": reduction_ratio,
            "reduction_percent": (1.0 - reduction_ratio) * 100,
        },
        "policy": [policy.to_dict() for policy in policies],
        "semantic_checks": checks,
        "memory_budget": budget,
        "findings": [
            {
                "id": "largest_baseline_column",
                "severity": "review",
                "message": "Start memory review from the largest source column.",
                "evidence": largest_baseline,
            },
            {
                "id": "largest_optimized_column",
                "severity": "review",
                "message": "Check whether the largest optimized column still matches its semantics.",
                "evidence": largest_optimized,
            },
            {
                "id": "memory_budget",
                "severity": budget["severity"],
                "message": budget["message"],
                "evidence": budget,
            },
        ],
        "interpretation": {
            "safe_to_ship": budget["passed"] and all(check["passed"] for check in checks),
            "notes": [
                "Memory reduction is accepted only together with semantic checks.",
                "Integer money stays in cents; float downcast is not allowed for money columns.",
                "Category dtypes are used only for declared low-cardinality dimensions.",
            ],
        },
    }
    return optimized, report


def build_schema_optimization_plan(
    *,
    rows: int,
    seed: int,
    memory_budget_mb: float,
    category_threshold: float = 0.5,
) -> dict[str, Any]:
    frame = generate_revenue_extract(rows=rows, seed=seed)
    _optimized, report = optimize_dataframe(
        frame,
        memory_budget_mb=memory_budget_mb,
        category_threshold=category_threshold,
    )
    return report


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a DataFrame dtype optimization plan.")
    parser.add_argument("--rows", type=int, default=5_000, help="number of source rows")
    parser.add_argument("--seed", type=int, default=42, help="deterministic input seed")
    parser.add_argument(
        "--memory-budget-mb",
        type=float,
        default=4.0,
        help="optimized DataFrame memory budget in MiB",
    )
    parser.add_argument(
        "--category-threshold",
        type=float,
        default=0.5,
        help="maximum unique/row ratio for automatic category dtype",
    )
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_schema_optimization_plan(
            rows=args.rows,
            seed=args.seed,
            memory_budget_mb=args.memory_budget_mb,
            category_threshold=args.category_threshold,
        )
        if args.output is not None:
            write_json(args.output, report)
    except (DtypePolicyError, TypeError, ValueError) as error:
        print(f"dtype policy error: {error}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
