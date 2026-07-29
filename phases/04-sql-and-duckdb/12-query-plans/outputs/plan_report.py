from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypedDict

import duckdb

TOTAL_TIME_PATTERN = re.compile(r"Total Time:\s*([0-9.]+)s")
ESTIMATED_ROWS_PATTERN = re.compile(r"~([0-9][0-9,]*) rows?")
ACTUAL_ROWS_PATTERN = re.compile(r"(?<!~)([0-9][0-9,]*) rows?")
SOURCE_READ_MARKER = "Function: READ_CSV"

BASELINE_SQL = """
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

CONSOLIDATED_SQL = """
SELECT
    count(*) FILTER (WHERE event_name = ?) AS event_rows,
    count(DISTINCT user_id) FILTER (WHERE event_name = ?) AS active_users
FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
"""

WRONG_POPULATION_SQL = """
SELECT
    count(*) FILTER (WHERE event_name = ?) AS event_rows,
    count(DISTINCT user_id) AS active_users
FROM read_csv(?, header = true, all_varchar = true, nullstr = '')
"""


class PlanAuditError(ValueError):
    """Raised when a plan comparison cannot satisfy its input contract."""


class QueryVariant(TypedDict):
    label: str
    sql: str
    parameters: Sequence[Any]


def _validated_events_path(events_path: Path) -> Path:
    path = Path(events_path).expanduser()
    if not path.is_file():
        raise PlanAuditError(f"events file does not exist: {path}")
    return path.resolve()


def _validated_event_name(event_name: str) -> str:
    if not isinstance(event_name, str) or not event_name.strip():
        raise PlanAuditError("event_name must be a non-empty string")
    return event_name


def _plan_text(
    connection: duckdb.DuckDBPyConnection,
    sql: str,
    parameters: Sequence[Any],
    *,
    analyze: bool,
) -> str:
    prefix = "EXPLAIN ANALYZE " if analyze else "EXPLAIN "
    rows = connection.execute(prefix + sql, list(parameters)).fetchall()
    if len(rows) != 1 or len(rows[0]) < 2 or not isinstance(rows[0][1], str):
        kind = "EXPLAIN ANALYZE" if analyze else "EXPLAIN"
        raise PlanAuditError(f"{kind} returned an unexpected result")
    return rows[0][1]


def _row_markers(pattern: re.Pattern[str], plan_text: str) -> list[int]:
    return [int(value.replace(",", "")) for value in pattern.findall(plan_text)]


def _plan_evidence(plan_text: str, *, analyzed: bool) -> dict[str, Any]:
    total_time_match = TOTAL_TIME_PATTERN.search(plan_text)
    return {
        "source_read_nodes": plan_text.count(SOURCE_READ_MARKER),
        "estimated_row_markers": (
            [] if analyzed else _row_markers(ESTIMATED_ROWS_PATTERN, plan_text)
        ),
        "actual_row_markers": (_row_markers(ACTUAL_ROWS_PATTERN, plan_text) if analyzed else []),
        "total_time_seconds": (float(total_time_match.group(1)) if total_time_match else None),
        "plan_text": plan_text,
    }


def _result(connection: duckdb.DuckDBPyConnection, variant: QueryVariant) -> dict[str, int]:
    row = connection.execute(
        variant["sql"],
        list(variant["parameters"]),
    ).fetchone()
    if row is None or len(row) != 2:
        raise PlanAuditError(f"{variant['label']} must return event_rows and active_users")
    return {
        "event_rows": int(row[0]),
        "active_users": int(row[1]),
    }


def inspect_variant(
    connection: duckdb.DuckDBPyConnection,
    variant: QueryVariant,
) -> dict[str, Any]:
    """Run one trusted query variant and preserve static and actual plan evidence."""
    explain_text = _plan_text(
        connection,
        variant["sql"],
        variant["parameters"],
        analyze=False,
    )
    analyzed_text = _plan_text(
        connection,
        variant["sql"],
        variant["parameters"],
        analyze=True,
    )
    return {
        "label": variant["label"],
        "sql": variant["sql"].strip(),
        "parameters": list(variant["parameters"]),
        "result": _result(connection, variant),
        "explain": _plan_evidence(explain_text, analyzed=False),
        "explain_analyze": _plan_evidence(analyzed_text, analyzed=True),
    }


def audit_variants(
    connection: duckdb.DuckDBPyConnection,
    baseline: QueryVariant,
    candidate: QueryVariant,
) -> dict[str, Any]:
    """Compare trusted query variants without taking ownership of the connection."""
    baseline_evidence = inspect_variant(connection, baseline)
    candidate_evidence = inspect_variant(connection, candidate)
    results_equal = baseline_evidence["result"] == candidate_evidence["result"]
    baseline_reads = baseline_evidence["explain"]["source_read_nodes"]
    candidate_reads = candidate_evidence["explain"]["source_read_nodes"]
    reads_removed = baseline_reads - candidate_reads

    if not results_equal:
        conclusion = (
            "blocked: candidate changes the analytical result, so plan and timing "
            "differences are not optimization evidence"
        )
    elif reads_removed > 0:
        conclusion = (
            "supported on this input: candidate preserves the result and removes "
            f"{reads_removed} repeated source read(s); timing remains an observation"
        )
    else:
        conclusion = (
            "inconclusive: results match, but this audit found no reduction in source "
            "reads; inspect other operators and use a separate benchmark if speed matters"
        )

    return {
        "variants": [baseline_evidence, candidate_evidence],
        "comparison": {
            "results_equal": results_equal,
            "safe_to_compare_work": results_equal,
            "baseline_source_read_nodes": baseline_reads,
            "candidate_source_read_nodes": candidate_reads,
            "source_reads_removed": reads_removed,
            "candidate_has_single_source_read": candidate_reads == 1,
            "timing_claim_allowed": False,
            "conclusion": conclusion,
        },
    }


def event_query_variants(
    events_path: Path,
    event_name: str,
    *,
    candidate_sql: str = CONSOLIDATED_SQL,
    candidate_label: str = "one_scan",
) -> tuple[QueryVariant, QueryVariant]:
    path = _validated_events_path(events_path)
    name = _validated_event_name(event_name)
    if candidate_sql == CONSOLIDATED_SQL:
        candidate_parameters = [name, name, str(path)]
    elif candidate_sql == WRONG_POPULATION_SQL:
        candidate_parameters = [name, str(path)]
    else:
        raise PlanAuditError(
            "candidate_sql must be a trusted built-in query; "
            "use audit_variants for an explicitly constructed trusted pair"
        )
    baseline: QueryVariant = {
        "label": "two_scans",
        "sql": BASELINE_SQL,
        "parameters": [str(path), name, str(path), name],
    }
    candidate: QueryVariant = {
        "label": candidate_label,
        "sql": candidate_sql,
        "parameters": candidate_parameters,
    }
    return baseline, candidate


def build_plan_report(
    connection: duckdb.DuckDBPyConnection,
    events_path: Path,
    event_name: str = "order_paid",
    *,
    candidate_sql: str = CONSOLIDATED_SQL,
    candidate_label: str = "one_scan",
) -> dict[str, Any]:
    """Build a bounded DuckDB plan audit for the lesson's event query."""
    path = _validated_events_path(events_path)
    baseline, candidate = event_query_variants(
        path,
        event_name,
        candidate_sql=candidate_sql,
        candidate_label=candidate_label,
    )
    audit = audit_variants(connection, baseline, candidate)
    return {
        "scope": {
            "engine": "duckdb",
            "engine_version": duckdb.__version__,
            "events_path": str(path),
            "event_name": _validated_event_name(event_name),
            "claim_boundary": (
                "The report diagnoses this query pair on this input. It does not "
                "guarantee a speedup for another dataset, engine version, or workload."
            ),
        },
        **audit,
    }


def _write_report(report: Mapping[str, Any], output_path: Path | None) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output_path is None:
        print(payload, end="")
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload, encoding="utf-8")
    print(output_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit equivalent DuckDB queries by result, EXPLAIN shape, and EXPLAIN ANALYZE evidence"
        )
    )
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--event-name", default="order_paid")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    connection = duckdb.connect()
    try:
        report = build_plan_report(connection, args.events, args.event_name)
        _write_report(report, args.output)
    except (duckdb.Error, OSError, PlanAuditError) as error:
        parser.error(str(error))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
