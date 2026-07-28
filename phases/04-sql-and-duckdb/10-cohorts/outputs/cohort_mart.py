from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb


def _json_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def build_cohort_mart(
    users_path: Path,
    events_path: Path,
    business_timezone: str = "Europe/Moscow",
) -> dict[str, Any]:
    query = """
        WITH
        users AS (
            SELECT
                user_id,
                date_trunc(
                    'month',
                    timezone(?, registered_at::TIMESTAMPTZ)
                )::DATE AS cohort_month
            FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        ),
        cohort_sizes AS (
            SELECT cohort_month, count(*) AS cohort_size
            FROM users
            GROUP BY cohort_month
        ),
        deduplicated_events AS (
            SELECT DISTINCT
                event_id,
                user_id,
                occurred_at::TIMESTAMPTZ AS occurred_at
            FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        ),
        activity AS (
            SELECT DISTINCT
                user_id,
                date_trunc(
                    'month',
                    timezone(?, occurred_at)
                )::DATE AS activity_month
            FROM deduplicated_events
        ),
        bounds AS (
            SELECT max(activity_month) AS max_activity_month
            FROM activity
        ),
        grid AS (
            SELECT
                cohort_sizes.cohort_month,
                cohort_sizes.cohort_size,
                periods.period_index,
                (
                    cohort_sizes.cohort_month
                    + periods.period_index * INTERVAL '1 month'
                )::DATE AS activity_month
            FROM cohort_sizes
            CROSS JOIN bounds
            CROSS JOIN LATERAL range(
                0,
                date_diff(
                    'month',
                    cohort_sizes.cohort_month,
                    bounds.max_activity_month
                ) + 1
            ) AS periods(period_index)
        ),
        active_users AS (
            SELECT
                users.cohort_month,
                activity.activity_month,
                count(DISTINCT users.user_id) AS active_users
            FROM users
            JOIN activity USING (user_id)
            GROUP BY users.cohort_month, activity.activity_month
        )
        SELECT
            grid.cohort_month,
            grid.activity_month,
            grid.period_index,
            grid.cohort_size,
            coalesce(active_users.active_users, 0) AS active_users,
            round(
                coalesce(active_users.active_users, 0)::DOUBLE / grid.cohort_size,
                4
            ) AS retention
        FROM grid
        LEFT JOIN active_users
          ON grid.cohort_month = active_users.cohort_month
         AND grid.activity_month = active_users.activity_month
        ORDER BY grid.cohort_month, grid.period_index
    """
    connection = duckdb.connect()
    try:
        relation = connection.execute(
            query,
            [
                business_timezone,
                str(users_path),
                str(events_path),
                business_timezone,
            ],
        )
        columns = [column[0] for column in relation.description]
        rows = [
            {column: _json_value(value) for column, value in zip(columns, row, strict=True)}
            for row in relation.fetchall()
        ]
        event_counts = connection.execute(
            """
            SELECT count(*) AS source_rows, count(DISTINCT event_id) AS unique_events
            FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
            """,
            [str(events_path)],
        ).fetchone()
    finally:
        connection.close()
    if event_counts is None:
        raise ValueError("event count audit returned no row")
    cohort_sizes = {
        row["cohort_month"]: row["cohort_size"] for row in rows if row["period_index"] == 0
    }
    return {
        "business_timezone": business_timezone,
        "grain": ["cohort_month", "period_index"],
        "cohort_sizes": cohort_sizes,
        "rows": rows,
        "checks": {
            "matrix_rows": len(rows),
            "grain_unique": len({(row["cohort_month"], row["period_index"]) for row in rows})
            == len(rows),
            "source_event_rows": event_counts[0],
            "unique_events": event_counts[1],
            "duplicate_event_rows": event_counts[0] - event_counts[1],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a checked SQL cohort matrix")
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--business-timezone", default="Europe/Moscow")
    args = parser.parse_args()
    try:
        report = build_cohort_mart(
            args.users,
            args.events,
            args.business_timezone,
        )
    except (duckdb.Error, OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
