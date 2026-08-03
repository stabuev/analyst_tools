from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "duckdb_plan_audit.py"
BASELINE_SQL = ROOT / "outputs" / "repeated_scan.sql"
CANDIDATE_SQL = ROOT / "outputs" / "single_scan.sql"


def load_artifact():
    spec = importlib.util.spec_from_file_location("duckdb_plan_audit", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_cohort_activity() -> pd.DataFrame:
    """Return the typed cohort result introduced in lessons 04/10 and 04/11."""

    return pd.DataFrame(
        {
            "cohort_month": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-01",
                    "2026-01-01",
                    "2026-01-01",
                    "2026-02-01",
                    "2026-02-01",
                    "2026-02-01",
                ]
            ),
            "activity_month": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-02-01",
                    "2026-03-01",
                    "2026-04-01",
                    "2026-02-01",
                    "2026-03-01",
                    "2026-04-01",
                ]
            ),
            "period_index": pd.Series([0, 1, 2, 3, 0, 1, 2], dtype="int64"),
            "cohort_size": pd.Series([4, 4, 4, 4, 3, 3, 3], dtype="int64"),
            "active_users": pd.Series([4, 3, 2, 0, 3, 2, 1], dtype="int64"),
            "activity_rate": pd.Series(
                [1.0, 0.75, 0.5, 0.0, 1.0, 0.6667, 0.3333],
                dtype="float64",
            ),
        }
    )


def main() -> None:
    plans = load_artifact()
    connection = duckdb.connect()
    try:
        report = plans.compare_dataframe_queries(
            connection,
            relation_name="cohort_activity",
            frame=build_cohort_activity(),
            baseline_sql=BASELINE_SQL.read_text(encoding="utf-8"),
            candidate_sql=CANDIDATE_SQL.read_text(encoding="utf-8"),
            parameters={"cohort_month": "2026-01-01"},
        )
    finally:
        connection.close()

    payload = {
        "results_equal": report["results_equal"],
        "result": report["result"].to_dict(orient="records"),
        "baseline_summary": report["baseline"]["summary"],
        "candidate_summary": report["candidate"]["summary"],
        "scan_operators_removed": report["comparison"]["scan_operators_removed"],
        "baseline_operators": report["baseline"]["operators"].to_dict(orient="records"),
        "candidate_operators": report["candidate"]["operators"].to_dict(orient="records"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
