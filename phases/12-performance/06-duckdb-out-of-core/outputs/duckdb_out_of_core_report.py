from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


class DuckDBOutOfCoreError(ValueError):
    """Raised when the DuckDB out-of-core report cannot be built safely."""


RESULT_COLUMNS = [
    "week_start",
    "segment",
    "platform",
    "net_revenue_cents",
    "paid_orders",
    "order_rows",
    "revenue_rank",
]

OPERATOR_PATTERNS = {
    "PARQUET_SCAN": ("PARQUET_SCAN", "READ_PARQUET"),
    "HASH_JOIN": ("HASH_JOIN",),
    "HASH_GROUP_BY": ("HASH_GROUP_BY", "PERFECT_HASH_GROUP_BY"),
    "WINDOW": ("WINDOW",),
    "ORDER_BY": ("ORDER_BY",),
}

BLOCKING_OPERATOR_NOTES = {
    "HASH_JOIN": "build-side hash table keeps state before probe rows can finish",
    "HASH_GROUP_BY": "aggregate groups keep state until the input is consumed",
    "WINDOW": "rank over a partition needs partition state and ordering",
    "ORDER_BY": "global ordering is a full-coordination operator",
}


def generate_customer_revenue_workload(
    *,
    rows: int = 12_000,
    users: int = 800,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if rows < 128:
        raise DuckDBOutOfCoreError("rows must be at least 128")
    if users < 16:
        raise DuckDBOutOfCoreError("users must be at least 16")
    if users > rows:
        raise DuckDBOutOfCoreError("users must be less than or equal to rows")

    rng = np.random.default_rng(seed)
    user_index = np.arange(users, dtype=np.int64)
    segments = np.array(["new", "returning", "power", "at_risk"], dtype=object)
    regions = np.array(["ru", "kz", "am", "tr"], dtype=object)
    acquisition = np.array(["organic", "paid", "partner", "crm"], dtype=object)
    plans = np.array(["trial", "basic", "plus", "pro"], dtype=object)

    users_frame = pd.DataFrame(
        {
            "user_id": [f"U{position:07d}" for position in user_index],
            "segment": segments[(user_index * 5) % len(segments)],
            "region": regions[(user_index * 7) % len(regions)],
            "acquisition_channel": acquisition[(user_index * 11) % len(acquisition)],
            "plan": plans[rng.integers(0, len(plans), size=users)],
            "signup_week": (user_index % 8).astype(np.int16),
        }
    )

    order_index = np.arange(rows, dtype=np.int64)
    week_index = (order_index % 8).astype(np.int16)
    base_week = pd.Timestamp("2026-01-05")
    week_start = [
        (base_week + pd.Timedelta(days=int(position) * 7)).date().isoformat()
        for position in week_index
    ]
    platforms = np.array(["web", "ios", "android"], dtype=object)
    user_ids = users_frame["user_id"].to_numpy()[rng.integers(0, users, size=rows)]
    paid_orders = rng.binomial(1, 0.70, size=rows).astype(np.int64)
    unit_price = rng.integers(399, 45_000, size=rows, dtype=np.int64)
    quantity = rng.integers(1, 4, size=rows, dtype=np.int64)
    gross = unit_price * quantity * paid_orders
    refunds = np.where(
        rng.random(rows) < 0.06,
        np.rint(gross * rng.uniform(0.15, 0.75, size=rows)).astype(np.int64),
        0,
    )
    support_tickets = rng.poisson(0.16, size=rows).astype(np.int64)

    orders_frame = pd.DataFrame(
        {
            "order_id": [f"O{position:010d}" for position in order_index],
            "user_id": user_ids,
            "week_index": week_index,
            "week_start": week_start,
            "platform": platforms[(order_index * 13) % len(platforms)],
            "paid_orders": paid_orders,
            "gross_revenue_cents": gross.astype(np.int64),
            "refund_amount_cents": refunds.astype(np.int64),
            "net_revenue_cents": (gross - refunds).astype(np.int64),
            "support_ticket_count": support_tickets,
            "payload": [
                f"trace={int(value)};stage=duckdb-out-of-core;wide=true"
                for value in rng.integers(100_000, 999_999, size=rows)
            ],
        }
    )
    orders_frame = orders_frame.sort_values(["week_index", "order_id"]).reset_index(drop=True)
    return orders_frame, users_frame


def write_workload_files(
    orders_frame: pd.DataFrame,
    users_frame: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, str]:
    data_dir = Path(output_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    orders_path = data_dir / "orders.parquet"
    users_path = data_dir / "users.parquet"
    pq.write_table(
        pa.Table.from_pandas(orders_frame, preserve_index=False),
        orders_path,
        compression="zstd",
        use_dictionary=True,
        write_statistics=True,
    )
    pq.write_table(
        pa.Table.from_pandas(users_frame, preserve_index=False),
        users_path,
        compression="zstd",
        use_dictionary=True,
        write_statistics=True,
    )
    return {"orders": str(orders_path), "users": str(users_path)}


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def configure_connection(
    connection: duckdb.DuckDBPyConnection,
    *,
    temp_directory: str | Path,
    memory_limit: str = "64MB",
    threads: int = 1,
    max_temp_directory_size: str = "256MB",
) -> dict[str, Any]:
    if threads <= 0:
        raise DuckDBOutOfCoreError("threads must be positive")
    temp_path = Path(temp_directory)
    temp_path.mkdir(parents=True, exist_ok=True)
    try:
        connection.execute(f"SET memory_limit = {_sql_literal(memory_limit)}")
        connection.execute(f"SET temp_directory = {_sql_literal(temp_path)}")
        connection.execute(f"SET max_temp_directory_size = {_sql_literal(max_temp_directory_size)}")
        connection.execute(f"SET threads = {int(threads)}")
    except Exception as error:  # noqa: BLE001 - converted to lesson-level error.
        raise DuckDBOutOfCoreError(f"cannot configure DuckDB: {error}") from error

    settings = connection.execute(
        """
        SELECT
          current_setting('memory_limit') AS memory_limit,
          current_setting('temp_directory') AS temp_directory,
          current_setting('max_temp_directory_size') AS max_temp_directory_size,
          current_setting('threads') AS threads
        """
    ).fetchone()
    if settings is None:
        raise DuckDBOutOfCoreError("DuckDB did not return current settings")
    database_size = connection.execute("PRAGMA database_size").fetchdf().iloc[0].to_dict()
    return {
        "memory_limit_requested": memory_limit,
        "memory_limit": str(settings[0]),
        "temp_directory": str(settings[1]),
        "max_temp_directory_size_requested": max_temp_directory_size,
        "max_temp_directory_size": str(settings[2]),
        "threads_requested": int(threads),
        "threads": int(settings[3]),
        "database_size": {str(key): str(value) for key, value in database_size.items()},
    }


def build_workload_query(paths: dict[str, str], *, min_week_index: int = 1, max_week_index: int = 6) -> str:
    orders_path = _sql_literal(paths["orders"])
    users_path = _sql_literal(paths["users"])
    return f"""
WITH weekly AS (
  SELECT
    o.week_start,
    u.segment,
    o.platform,
    CAST(sum(o.net_revenue_cents) AS BIGINT) AS net_revenue_cents,
    CAST(sum(o.paid_orders) AS BIGINT) AS paid_orders,
    CAST(count(*) AS BIGINT) AS order_rows
  FROM read_parquet({orders_path}) AS o
  INNER JOIN read_parquet({users_path}) AS u
    USING (user_id)
  WHERE o.week_index BETWEEN {int(min_week_index)} AND {int(max_week_index)}
  GROUP BY 1, 2, 3
),
ranked AS (
  SELECT
    week_start,
    segment,
    platform,
    net_revenue_cents,
    paid_orders,
    order_rows,
    CAST(rank() OVER (
      PARTITION BY week_start
      ORDER BY net_revenue_cents DESC
    ) AS BIGINT) AS revenue_rank
  FROM weekly
)
SELECT
  week_start,
  segment,
  platform,
  net_revenue_cents,
  paid_orders,
  order_rows,
  revenue_rank
FROM ranked
WHERE revenue_rank <= 3
ORDER BY week_start, revenue_rank, segment, platform
""".strip()


def _plan_text(rows: list[tuple[Any, ...]]) -> str:
    if not rows:
        return ""
    if len(rows[0]) >= 2:
        return "\n".join(str(row[1]) for row in rows)
    return "\n".join(" ".join(str(value) for value in row) for row in rows)


def explain_query(connection: duckdb.DuckDBPyConnection, query: str) -> str:
    return _plan_text(connection.execute("EXPLAIN " + query).fetchall())


def explain_analyze_query(connection: duckdb.DuckDBPyConnection, query: str) -> str:
    return _plan_text(connection.execute("EXPLAIN ANALYZE " + query).fetchall())


def detect_plan_operators(plan_text: str) -> dict[str, bool]:
    upper_plan = plan_text.upper()
    return {
        operator: any(pattern in upper_plan for pattern in patterns)
        for operator, patterns in OPERATOR_PATTERNS.items()
    }


def classify_blocking_operators(plan_text: str) -> list[dict[str, str]]:
    detected = detect_plan_operators(plan_text)
    return [
        {"operator": operator, "reason": BLOCKING_OPERATOR_NOTES[operator]}
        for operator in BLOCKING_OPERATOR_NOTES
        if detected.get(operator, False)
    ]


def execute_workload(connection: duckdb.DuckDBPyConnection, query: str) -> pd.DataFrame:
    return connection.execute(query).fetchdf()


def pandas_control_result(
    orders_frame: pd.DataFrame,
    users_frame: pd.DataFrame,
    *,
    min_week_index: int = 1,
    max_week_index: int = 6,
) -> pd.DataFrame:
    filtered = orders_frame[
        orders_frame["week_index"].between(min_week_index, max_week_index)
    ].copy()
    joined = filtered.merge(users_frame[["user_id", "segment"]], on="user_id", how="inner")
    weekly = (
        joined.groupby(["week_start", "segment", "platform"], as_index=False)
        .agg(
            net_revenue_cents=("net_revenue_cents", "sum"),
            paid_orders=("paid_orders", "sum"),
            order_rows=("order_id", "size"),
        )
    )
    weekly["revenue_rank"] = (
        weekly.groupby("week_start")["net_revenue_cents"]
        .rank(method="min", ascending=False)
        .astype("int64")
    )
    result = weekly[weekly["revenue_rank"] <= 3].copy()
    return _normalize_result_frame(result)


def _normalize_result_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame[RESULT_COLUMNS].copy()
    normalized["week_start"] = normalized["week_start"].astype(str)
    normalized["segment"] = normalized["segment"].astype(str)
    normalized["platform"] = normalized["platform"].astype(str)
    for column in ["net_revenue_cents", "paid_orders", "order_rows", "revenue_rank"]:
        normalized[column] = normalized[column].astype("int64")
    return normalized.sort_values(
        ["week_start", "revenue_rank", "segment", "platform"],
        kind="mergesort",
    ).reset_index(drop=True)


def compare_with_control(duckdb_result: pd.DataFrame, control_result: pd.DataFrame) -> dict[str, Any]:
    observed = _normalize_result_frame(duckdb_result)
    expected = _normalize_result_frame(control_result)
    matches = observed.equals(expected)
    diff_preview: list[dict[str, Any]] = []
    if not matches:
        merged = observed.merge(
            expected,
            on=["week_start", "segment", "platform", "revenue_rank"],
            how="outer",
            suffixes=("_duckdb", "_control"),
            indicator=True,
        )
        diff_preview = merged.head(10).to_dict(orient="records")
    return {
        "matches_control": bool(matches),
        "duckdb_rows": int(len(observed)),
        "control_rows": int(len(expected)),
        "result_preview": observed.head(12).to_dict(orient="records"),
        "diff_preview": diff_preview,
    }


def _temp_directory_state(temp_directory: str | Path) -> dict[str, Any]:
    temp_path = Path(temp_directory)
    files = [
        path
        for path in sorted(temp_path.rglob("*"))
        if path.is_file()
    ] if temp_path.exists() else []
    return {
        "exists": temp_path.exists(),
        "file_count": len(files),
        "total_bytes": int(sum(path.stat().st_size for path in files)),
        "files": [
            {"path": str(path.relative_to(temp_path)), "size_bytes": int(path.stat().st_size)}
            for path in files[:20]
        ],
    }


def _profile_has_runtime_evidence(profile_text: str) -> bool:
    upper_profile = profile_text.upper()
    return "TOTAL TIME" in upper_profile and ("ROWS" in upper_profile or "QUERY PROFILING" in upper_profile)


def _build_interpretation(
    *,
    settings: dict[str, Any],
    operators: dict[str, bool],
    blocking_operators: list[dict[str, str]],
    profile_text: str,
    comparison: dict[str, Any],
    temp_before: dict[str, Any],
    temp_after: dict[str, Any],
) -> dict[str, Any]:
    spill_observed = temp_after["file_count"] > temp_before["file_count"] or temp_after["total_bytes"] > temp_before["total_bytes"]
    checks = {
        "memory_limit_set": bool(settings["memory_limit"]),
        "temp_directory_exists": bool(temp_after["exists"]),
        "threads_set": settings["threads"] == settings["threads_requested"],
        "max_temp_directory_size_set": bool(settings["max_temp_directory_size"]),
        "parquet_scan_present": operators.get("PARQUET_SCAN", False),
        "blocking_operators_identified": len(blocking_operators) >= 2,
        "profile_has_runtime_evidence": _profile_has_runtime_evidence(profile_text),
        "result_matches_control": bool(comparison["matches_control"]),
    }
    notes = [
        "The workload is spill-ready because memory_limit, temp_directory and temp size are explicit.",
        "Actual spill is environment-dependent; this report records spill_observed instead of claiming it.",
        "DuckDB memory_limit applies to the buffer manager, not every allocation in the process.",
        "Multiple blocking operators can still create out-of-memory risk on larger inputs.",
    ]
    return {
        "checks": checks,
        "spill_observed": bool(spill_observed),
        "spill_ready": bool(
            checks["memory_limit_set"]
            and checks["temp_directory_exists"]
            and checks["max_temp_directory_size_set"]
            and checks["blocking_operators_identified"]
        ),
        "does_not_claim_spill": not spill_observed,
        "safe_to_ship": all(checks.values()),
        "notes": notes,
    }


def write_runbook(report: dict[str, Any], output_dir: str | Path) -> Path:
    output_path = Path(output_dir) / "runbook.md"
    blocking = "\n".join(
        f"- `{item['operator']}`: {item['reason']}"
        for item in report["plan"]["blocking_operators"]
    )
    checks = "\n".join(
        f"- `{name}`: {value}"
        for name, value in report["interpretation"]["checks"].items()
    )
    limitations = "\n".join(f"- {note}" for note in report["interpretation"]["notes"])
    output_path.write_text(
        "\n".join(
            [
                "# DuckDB Out-of-Core Runbook",
                "",
                "## Configuration",
                "",
                f"- `memory_limit`: {report['settings']['memory_limit']} (requested {report['settings']['memory_limit_requested']})",
                f"- `temp_directory`: {report['settings']['temp_directory']}",
                f"- `max_temp_directory_size`: {report['settings']['max_temp_directory_size']}",
                f"- `threads`: {report['settings']['threads']}",
                "",
                "## Blocking Operators",
                "",
                blocking,
                "",
                "## Larger-than-memory Checks",
                "",
                checks,
                "",
                "## Spill Observation",
                "",
                f"- `spill_ready`: {report['interpretation']['spill_ready']}",
                f"- `spill_observed`: {report['interpretation']['spill_observed']}",
                "",
                "## Limitations",
                "",
                limitations,
                "",
                "## Query",
                "",
                "```sql",
                report["query"],
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return output_path


def _build_report_in_directory(
    work_dir: Path,
    *,
    rows: int,
    users: int,
    seed: int,
    memory_limit: str,
    threads: int,
    max_temp_directory_size: str,
    persistent_output: bool,
) -> dict[str, Any]:
    orders_frame, users_frame = generate_customer_revenue_workload(rows=rows, users=users, seed=seed)
    paths = write_workload_files(orders_frame, users_frame, work_dir)
    temp_directory = work_dir / "duckdb-temp"

    connection = duckdb.connect(":memory:")
    try:
        settings = configure_connection(
            connection,
            temp_directory=temp_directory,
            memory_limit=memory_limit,
            threads=threads,
            max_temp_directory_size=max_temp_directory_size,
        )
        query = build_workload_query(paths)
        temp_before = _temp_directory_state(temp_directory)
        plan_text = explain_query(connection, query)
        profile_text = explain_analyze_query(connection, query)
        result = execute_workload(connection, query)
    finally:
        connection.close()

    control = pandas_control_result(orders_frame, users_frame)
    comparison = compare_with_control(result, control)
    temp_after = _temp_directory_state(temp_directory)
    operators = detect_plan_operators(plan_text)
    blocking_operators = classify_blocking_operators(plan_text)
    report = {
        "scenario": {
            "scenario_id": "duckdb-out-of-core-query-profile",
            "pipeline_name": "customer_revenue_health_weekly_top_segments",
            "dataset_profile": "sample",
            "rows": int(rows),
            "users": int(users),
            "seed": int(seed),
            "engine": "duckdb",
            "duckdb_version": duckdb.__version__,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "package": {
            "persistent_output": bool(persistent_output),
            "output_dir": str(work_dir) if persistent_output else None,
            "data_files": {
                "orders": str(Path(paths["orders"]).relative_to(work_dir)),
                "users": str(Path(paths["users"]).relative_to(work_dir)),
            },
        },
        "settings": settings,
        "query": query,
        "plan": {
            "operators": operators,
            "blocking_operators": blocking_operators,
            "text": plan_text,
        },
        "profile": {
            "has_runtime_evidence": _profile_has_runtime_evidence(profile_text),
            "text": profile_text,
        },
        "temp_directory": {
            "before": temp_before,
            "after": temp_after,
        },
        "equivalence": comparison,
    }
    report["interpretation"] = _build_interpretation(
        settings=settings,
        operators=operators,
        blocking_operators=blocking_operators,
        profile_text=profile_text,
        comparison=comparison,
        temp_before=temp_before,
        temp_after=temp_after,
    )

    if persistent_output:
        (work_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (work_dir / "query-plan.txt").write_text(plan_text + "\n", encoding="utf-8")
        (work_dir / "query-profile.txt").write_text(profile_text + "\n", encoding="utf-8")
        runbook = write_runbook(report, work_dir)
        report["package"]["files"] = [
            "report.json",
            "query-plan.txt",
            "query-profile.txt",
            str(runbook.relative_to(work_dir)),
        ]
        (work_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def build_duckdb_out_of_core_report(
    *,
    rows: int = 12_000,
    users: int = 800,
    seed: int = 42,
    memory_limit: str = "64MB",
    threads: int = 1,
    max_temp_directory_size: str = "256MB",
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    if output_dir is None:
        with tempfile.TemporaryDirectory() as tmp:
            return _build_report_in_directory(
                Path(tmp),
                rows=rows,
                users=users,
                seed=seed,
                memory_limit=memory_limit,
                threads=threads,
                max_temp_directory_size=max_temp_directory_size,
                persistent_output=False,
            )

    work_dir = Path(output_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    return _build_report_in_directory(
        work_dir,
        rows=rows,
        users=users,
        seed=seed,
        memory_limit=memory_limit,
        threads=threads,
        max_temp_directory_size=max_temp_directory_size,
        persistent_output=True,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a DuckDB out-of-core runbook and query profile report")
    parser.add_argument("--rows", type=int, default=12_000)
    parser.add_argument("--users", type=int, default=800)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--memory-limit", default="64MB")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--max-temp-directory-size", default="256MB")
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_duckdb_out_of_core_report(
            rows=args.rows,
            users=args.users,
            seed=args.seed,
            memory_limit=args.memory_limit,
            threads=args.threads,
            max_temp_directory_size=args.max_temp_directory_size,
            output_dir=args.output_dir,
        )
    except DuckDBOutOfCoreError as error:
        print(f"duckdb out-of-core error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
