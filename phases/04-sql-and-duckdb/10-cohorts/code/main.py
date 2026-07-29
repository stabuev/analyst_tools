from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / "data" / "tiny"
MODEL_SQL_PATH = ROOT / "outputs" / "monthly_cohort_activity.sql"

EXPECTED_COLUMNS = [
    "cohort_month",
    "activity_month",
    "period_index",
    "cohort_size",
    "active_users",
    "activity_rate",
    "business_timezone",
    "last_complete_activity_month",
]
EXPECTED_TYPES = [
    "DATE",
    "DATE",
    "BIGINT",
    "BIGINT",
    "BIGINT",
    "DOUBLE",
    "VARCHAR",
    "DATE",
]


def prepare_inputs(
    connection: duckdb.DuckDBPyConnection,
    users_path: Path = DATA / "users.csv",
    events_path: Path = DATA / "events.csv",
) -> None:
    """Load typed fixtures; file ingestion is infrastructure, not the SQL artifact."""
    connection.execute(
        """
        CREATE OR REPLACE TABLE users AS
        SELECT
            CAST(user_id AS VARCHAR) AS user_id,
            CAST(registered_at AS TIMESTAMPTZ) AS registered_at
        FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        """,
        [str(users_path)],
    )
    connection.execute(
        """
        CREATE OR REPLACE TABLE events AS
        SELECT
            CAST(event_id AS VARCHAR) AS event_id,
            CAST(user_id AS VARCHAR) AS user_id,
            CAST(occurred_at AS TIMESTAMPTZ) AS occurred_at,
            CAST(event_name AS VARCHAR) AS event_name
        FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
        """,
        [str(events_path)],
    )


def _schema(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
) -> dict[str, str]:
    return {row[0]: str(row[1]) for row in connection.execute(f"DESCRIBE {relation}").fetchall()}


def _require_schema(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    expected: dict[str, str],
) -> None:
    actual = _schema(connection, relation)
    for column, expected_type in expected.items():
        actual_type = actual.get(column)
        if actual_type is None:
            raise ValueError(f"{relation} is missing required column {column}")
        if actual_type != expected_type:
            raise ValueError(f"{relation}.{column} must be {expected_type}, got {actual_type}")


def _require_populated(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    columns: tuple[str, ...],
) -> None:
    for column in columns:
        missing = connection.execute(
            f"""
            SELECT count(*)
            FROM {relation}
            WHERE {column} IS NULL
               OR (
                    typeof({column}) = 'VARCHAR'
                    AND trim(CAST({column} AS VARCHAR)) = ''
               )
            """
        ).fetchone()[0]
        if missing:
            raise ValueError(f"{relation}.{column} contains {missing} NULL or blank values")


def validate_inputs(connection: duckdb.DuckDBPyConnection) -> None:
    _require_schema(
        connection,
        "users",
        {
            "user_id": "VARCHAR",
            "registered_at": "TIMESTAMP WITH TIME ZONE",
        },
    )
    _require_schema(
        connection,
        "events",
        {
            "event_id": "VARCHAR",
            "user_id": "VARCHAR",
            "occurred_at": "TIMESTAMP WITH TIME ZONE",
            "event_name": "VARCHAR",
        },
    )
    _require_populated(connection, "users", ("user_id", "registered_at"))
    _require_populated(
        connection,
        "events",
        ("event_id", "user_id", "occurred_at", "event_name"),
    )

    duplicate_user = connection.execute(
        """
        SELECT user_id
        FROM users
        GROUP BY user_id
        HAVING count(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicate_user is not None:
        raise ValueError(f"users grain violation for user_id: {duplicate_user[0]}")

    conflicting_event = connection.execute(
        """
        SELECT event_id
        FROM events
        GROUP BY event_id
        HAVING count(DISTINCT user_id) > 1
            OR count(DISTINCT occurred_at) > 1
            OR count(DISTINCT event_name) > 1
        LIMIT 1
        """
    ).fetchone()
    if conflicting_event is not None:
        raise ValueError(
            f"events contains conflicting deliveries for event_id: {conflicting_event[0]}"
        )

    orphan_event = connection.execute(
        """
        SELECT events.event_id
        FROM events
        LEFT JOIN users USING (user_id)
        WHERE users.user_id IS NULL
        LIMIT 1
        """
    ).fetchone()
    if orphan_event is not None:
        raise ValueError(f"events contains an unknown user: {orphan_event[0]}")

    event_before_registration = connection.execute(
        """
        SELECT events.event_id
        FROM events
        JOIN users USING (user_id)
        WHERE events.occurred_at < users.registered_at
        LIMIT 1
        """
    ).fetchone()
    if event_before_registration is not None:
        raise ValueError(
            f"events contains activity before registration: {event_before_registration[0]}"
        )


def execute_model(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[list[str], list[str], list[tuple[Any, ...]]]:
    relation = connection.execute(MODEL_SQL_PATH.read_text(encoding="utf-8"))
    columns = [description[0] for description in relation.description]
    types = [str(description[1]) for description in relation.description]
    return columns, types, relation.fetchall()


def validate_model(
    columns: list[str],
    types: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    if columns != EXPECTED_COLUMNS:
        raise ValueError(f"cohort model columns must be {EXPECTED_COLUMNS}, got {columns}")
    if types != EXPECTED_TYPES:
        raise ValueError(f"cohort model types must be {EXPECTED_TYPES}, got {types}")

    cohort_at = columns.index("cohort_month")
    activity_at = columns.index("activity_month")
    period_at = columns.index("period_index")
    size_at = columns.index("cohort_size")
    active_at = columns.index("active_users")
    rate_at = columns.index("activity_rate")
    timezone_at = columns.index("business_timezone")
    cutoff_at = columns.index("last_complete_activity_month")

    if not rows:
        raise ValueError("cohort model must contain at least one observed period")

    grain = [(row[cohort_at], row[period_at]) for row in rows]
    if len(grain) != len(set(grain)):
        raise ValueError("cohort model grain must be unique")

    sizes_by_cohort: dict[Any, set[Any]] = {}
    periods_by_cohort: dict[date, set[int]] = {}
    cutoffs = {row[cutoff_at] for row in rows}
    timezones = {row[timezone_at] for row in rows}
    if len(cutoffs) != 1 or len(timezones) != 1:
        raise ValueError("settings must stay constant across the cohort model")
    cutoff = next(iter(cutoffs))

    for row in rows:
        sizes_by_cohort.setdefault(row[cohort_at], set()).add(row[size_at])
        periods_by_cohort.setdefault(row[cohort_at], set()).add(row[period_at])
        if row[size_at] <= 0:
            raise ValueError("cohort_size must be positive")
        if row[active_at] < 0 or row[active_at] > row[size_at]:
            raise ValueError("active_users must be between zero and cohort_size")
        if row[rate_at] < 0 or row[rate_at] > 1:
            raise ValueError("activity_rate must be between zero and one")
        if row[rate_at] != round(row[active_at] / row[size_at], 4):
            raise ValueError("activity_rate must use active_users / cohort_size")
        cohort_month: date = row[cohort_at]
        month_number = cohort_month.month - 1 + row[period_at]
        expected_month = date(
            cohort_month.year + month_number // 12,
            month_number % 12 + 1,
            1,
        )
        if row[activity_at] != expected_month:
            raise ValueError("activity_month must equal cohort_month shifted by period_index")
        if row[activity_at] > row[cutoff_at]:
            raise ValueError("activity_month must not exceed the observation cutoff")

    if any(len(sizes) != 1 for sizes in sizes_by_cohort.values()):
        raise ValueError("cohort_size must stay fixed within a cohort")
    for cohort_month, actual_periods in periods_by_cohort.items():
        last_period = (cutoff.year - cohort_month.year) * 12 + cutoff.month - cohort_month.month
        expected_periods = set(range(last_period + 1))
        if actual_periods != expected_periods:
            raise ValueError(
                "cohort periods must form a complete grid through the observation cutoff"
            )


def main() -> None:
    connection = duckdb.connect()
    try:
        connection.execute("SET TimeZone = 'UTC'")
        prepare_inputs(connection)
        validate_inputs(connection)
        columns, types, rows = execute_model(connection)
        validate_model(columns, types, rows)
    finally:
        connection.close()

    manual_december = {
        "cohort_size": 2,
        "period_0": {"active_users": 0, "activity_rate": 0.0},
        "period_1": {"active_users": 2, "activity_rate": 1.0},
        "period_2": {"active_users": 1, "activity_rate": 0.5},
    }
    report = {
        "manual_december": manual_december,
        "model": {
            "columns": columns,
            "types": types,
            "rows": [dict(zip(columns, row, strict=True)) for row in rows],
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
