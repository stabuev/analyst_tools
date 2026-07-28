from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb

TOTAL_TIME = re.compile(r"Total Time:\s*([0-9.]+)s")

INEFFICIENT_SQL = """
SELECT
    (
        SELECT count(*)
        FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        WHERE event_name = ?
    ) AS event_rows,
    (
        SELECT count(DISTINCT user_id)
        FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        WHERE event_name = ?
    ) AS active_users
"""

OPTIMIZED_SQL = """
SELECT
    count(*) FILTER (WHERE event_name = ?) AS event_rows,
    count(DISTINCT user_id) FILTER (WHERE event_name = ?) AS active_users
FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
"""


def analyze(
    connection: duckdb.DuckDBPyConnection,
    label: str,
    sql: str,
    params: Sequence[Any],
) -> dict[str, Any]:
    plan_row = connection.execute(
        "EXPLAIN ANALYZE " + sql,
        list(params),
    ).fetchone()
    if plan_row is None:
        raise ValueError(f"{label} plan is empty")
    plan = plan_row[1]
    result = connection.execute(sql, list(params)).fetchone()
    if result is None:
        raise ValueError(f"{label} result is empty")
    total_time_match = TOTAL_TIME.search(plan)
    return {
        "label": label,
        "result": {"event_rows": result[0], "active_users": result[1]},
        "scan_nodes": plan.count("TABLE_SCAN"),
        "total_time_seconds": (float(total_time_match.group(1)) if total_time_match else None),
        "plan": plan,
    }


def compare_plans(events_path: Path, event_name: str = "order_paid") -> dict[str, Any]:
    connection = duckdb.connect()
    try:
        inefficient = analyze(
            connection,
            "two_scans",
            INEFFICIENT_SQL,
            [str(events_path), event_name, str(events_path), event_name],
        )
        optimized = analyze(
            connection,
            "one_scan",
            OPTIMIZED_SQL,
            [event_name, event_name, str(events_path)],
        )
    finally:
        connection.close()
    return {
        "event_name": event_name,
        "queries": [inefficient, optimized],
        "checks": {
            "results_equal": inefficient["result"] == optimized["result"],
            "scan_nodes_removed": inefficient["scan_nodes"] - optimized["scan_nodes"],
            "optimized_has_one_scan": optimized["scan_nodes"] == 1,
        },
        "interpretation": (
            "Treat timing as an observation, not a guarantee; compare repeated runs "
            "on the generated sample profile."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare DuckDB EXPLAIN ANALYZE plans")
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--event-name", default="order_paid")
    args = parser.parse_args()
    try:
        report = compare_plans(args.events, args.event_name)
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
