from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import duckdb
import pandas as pd
from pandas.testing import assert_frame_equal

QueryParameters = Sequence[Any] | Mapping[str, Any]

OPERATOR_COLUMNS = [
    "path",
    "operator",
    "estimated_rows",
    "actual_rows",
    "rows_scanned",
    "timing_seconds",
]


class QueryPlanAuditError(ValueError):
    """Raised when reviewed queries cannot be compared under one contract."""


def _bound_parameters(parameters: QueryParameters) -> list[Any] | dict[str, Any]:
    return dict(parameters) if isinstance(parameters, Mapping) else list(parameters)


def _json_payload(row: tuple[Any, ...] | None, *, label: str) -> Any:
    if row is None or len(row) < 2:
        raise QueryPlanAuditError(f"{label} returned no JSON plan")
    try:
        return json.loads(row[1])
    except (TypeError, json.JSONDecodeError) as error:
        raise QueryPlanAuditError(f"{label} returned invalid JSON") from error


def _estimated_rows(extra_info: Mapping[str, Any]) -> int | None:
    raw_value = extra_info.get("Estimated Cardinality")
    if raw_value is None:
        return None
    normalized = str(raw_value).strip().lstrip("~").replace(",", "")
    try:
        return int(float(normalized))
    except ValueError:
        return None


def _flatten_explain_node(
    node: Mapping[str, Any],
    *,
    path: str,
) -> list[dict[str, Any]]:
    extra_info = node.get("extra_info")
    if not isinstance(extra_info, Mapping):
        extra_info = {}

    rows = [
        {
            "path": path,
            "operator": str(node.get("name", "UNKNOWN")).strip(),
            "estimated_rows": _estimated_rows(extra_info),
        }
    ]
    children = node.get("children", [])
    if not isinstance(children, list):
        raise QueryPlanAuditError("EXPLAIN node has invalid children")
    for index, child in enumerate(children):
        if not isinstance(child, Mapping):
            raise QueryPlanAuditError("EXPLAIN child is not an object")
        rows.extend(_flatten_explain_node(child, path=f"{path}.{index}"))
    return rows


def _flatten_analyze_node(
    node: Mapping[str, Any],
    *,
    path: str,
) -> list[dict[str, Any]]:
    rows = [
        {
            "path": path,
            "operator": str(node.get("operator_name", "UNKNOWN")).strip(),
            "actual_rows": int(node.get("operator_cardinality", 0)),
            "rows_scanned": int(node.get("operator_rows_scanned", 0)),
            "timing_seconds": float(node.get("operator_timing", 0.0)),
        }
    ]
    children = node.get("children", [])
    if not isinstance(children, list):
        raise QueryPlanAuditError("EXPLAIN ANALYZE node has invalid children")
    for index, child in enumerate(children):
        if not isinstance(child, Mapping):
            raise QueryPlanAuditError("EXPLAIN ANALYZE child is not an object")
        rows.extend(_flatten_analyze_node(child, path=f"{path}.{index}"))
    return rows


def _analyzed_plan_root(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    children = payload.get("children", [])
    if not isinstance(children, list) or len(children) != 1:
        raise QueryPlanAuditError("EXPLAIN ANALYZE has no single wrapper node")
    wrapper = children[0]
    if not isinstance(wrapper, Mapping):
        raise QueryPlanAuditError("EXPLAIN ANALYZE wrapper is invalid")
    plan_children = wrapper.get("children", [])
    if not isinstance(plan_children, list) or len(plan_children) != 1:
        raise QueryPlanAuditError("EXPLAIN ANALYZE has no single physical plan root")
    root = plan_children[0]
    if not isinstance(root, Mapping):
        raise QueryPlanAuditError("EXPLAIN ANALYZE physical plan root is invalid")
    return root


def inspect_reviewed_query(
    connection: duckdb.DuckDBPyConnection,
    *,
    sql: str,
    parameters: QueryParameters = (),
) -> dict[str, Any]:
    """Execute one reviewed query and return its result and structured plan evidence.

    ``EXPLAIN (ANALYZE, FORMAT JSON)`` executes ``sql``. This function is not a SQL
    sandbox and must only receive statements that the caller has already reviewed.
    The caller owns ``connection`` and remains responsible for closing it.
    """

    if not sql.strip():
        raise QueryPlanAuditError("sql must not be empty")

    normalized_parameters = _bound_parameters(parameters)
    result = connection.execute(sql, _bound_parameters(parameters)).fetchdf()
    explain_payload = _json_payload(
        connection.execute(
            "EXPLAIN (FORMAT JSON) " + sql,
            _bound_parameters(parameters),
        ).fetchone(),
        label="EXPLAIN",
    )
    analyze_payload = _json_payload(
        connection.execute(
            "EXPLAIN (ANALYZE, FORMAT JSON) " + sql,
            _bound_parameters(parameters),
        ).fetchone(),
        label="EXPLAIN ANALYZE",
    )

    if not isinstance(explain_payload, list) or len(explain_payload) != 1:
        raise QueryPlanAuditError("EXPLAIN has no single physical plan root")
    explain_root = explain_payload[0]
    if not isinstance(explain_root, Mapping):
        raise QueryPlanAuditError("EXPLAIN physical plan root is invalid")
    if not isinstance(analyze_payload, Mapping):
        raise QueryPlanAuditError("EXPLAIN ANALYZE payload is not an object")

    estimated = pd.DataFrame(_flatten_explain_node(explain_root, path="0"))
    actual = pd.DataFrame(_flatten_analyze_node(_analyzed_plan_root(analyze_payload), path="0"))
    operators = estimated.merge(
        actual,
        on=["path", "operator"],
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    if not operators["_merge"].eq("both").all():
        mismatch = operators.loc[
            ~operators["_merge"].eq("both"),
            ["path", "operator", "_merge"],
        ].to_dict(orient="records")
        raise QueryPlanAuditError(f"EXPLAIN and EXPLAIN ANALYZE plan shapes differ: {mismatch}")
    operators = operators.drop(columns="_merge")[OPERATOR_COLUMNS]
    operators["estimated_rows"] = operators["estimated_rows"].astype("Int64")
    operators["actual_rows"] = operators["actual_rows"].astype("int64")
    operators["rows_scanned"] = operators["rows_scanned"].astype("int64")

    scan_mask = operators["operator"].str.contains("SCAN", regex=False)
    return {
        "sql": sql.strip(),
        "parameters": normalized_parameters,
        "result": result,
        "operators": operators,
        "summary": {
            "operator_count": int(len(operators)),
            "scan_operators": int(scan_mask.sum()),
            "rows_scanned": int(operators.loc[scan_mask, "rows_scanned"].sum()),
        },
        "explain_json": explain_payload,
        "analyze_json": analyze_payload,
    }


def compare_reviewed_queries(
    connection: duckdb.DuckDBPyConnection,
    *,
    baseline_sql: str,
    candidate_sql: str,
    parameters: QueryParameters = (),
) -> dict[str, Any]:
    """Require exact result equivalence before comparing two physical plans."""

    baseline = inspect_reviewed_query(
        connection,
        sql=baseline_sql,
        parameters=parameters,
    )
    candidate = inspect_reviewed_query(
        connection,
        sql=candidate_sql,
        parameters=parameters,
    )
    try:
        assert_frame_equal(
            baseline["result"],
            candidate["result"],
            check_exact=True,
            check_dtype=True,
            check_like=False,
        )
    except AssertionError as error:
        raise QueryPlanAuditError(
            "candidate result differs from baseline; plans are not comparable"
        ) from error

    removed_scans = baseline["summary"]["scan_operators"] - candidate["summary"]["scan_operators"]
    return {
        "scope": {
            "engine": "duckdb",
            "engine_version": duckdb.__version__,
            "claim_boundary": (
                "The report diagnoses this reviewed query pair on this input and "
                "engine version. Operator timings are observations, not a benchmark "
                "or a speedup guarantee for another workload."
            ),
        },
        "results_equal": True,
        "result": baseline["result"],
        "baseline": baseline,
        "candidate": candidate,
        "comparison": {
            "safe_to_compare_work": True,
            "scan_operators_removed": int(removed_scans),
            "timing_is_observation_not_verdict": True,
            "conclusion": (
                "candidate preserves the exact result and changes the observed plan "
                f"by {removed_scans} scan operator(s); no timing claim is made"
            ),
        },
    }


def compare_dataframe_queries(
    connection: duckdb.DuckDBPyConnection,
    *,
    relation_name: str,
    frame: pd.DataFrame,
    baseline_sql: str,
    candidate_sql: str,
    parameters: QueryParameters = (),
) -> dict[str, Any]:
    """Register one typed DataFrame temporarily and compare two reviewed queries."""

    if not relation_name or not relation_name.isidentifier():
        raise QueryPlanAuditError("relation_name must be a non-empty Python-style identifier")
    if not isinstance(frame, pd.DataFrame):
        raise QueryPlanAuditError("frame must be a pandas DataFrame")

    connection.register(relation_name, frame)
    try:
        report = compare_reviewed_queries(
            connection,
            baseline_sql=baseline_sql,
            candidate_sql=candidate_sql,
            parameters=parameters,
        )
        report["scope"].update(
            {
                "relation_name": relation_name,
                "input_rows": int(len(frame)),
                "input_columns": frame.columns.tolist(),
                "input_dtypes": {column: str(dtype) for column, dtype in frame.dtypes.items()},
            }
        )
        return report
    finally:
        connection.unregister(relation_name)
