from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "duckdb_dataframe_query.py"
SQL = ROOT / "outputs" / "cohort_activity_slice.sql"

INPUT_COLUMNS = [
    "cohort_month",
    "activity_month",
    "period_index",
    "cohort_size",
    "active_users",
    "activity_rate",
    "business_timezone",
    "last_complete_activity_month",
]
INPUT_DTYPES = {
    "cohort_month": "datetime64[us]",
    "activity_month": "datetime64[us]",
    "period_index": "int64",
    "cohort_size": "int64",
    "active_users": "int64",
    "activity_rate": "float64",
    "business_timezone": "string",
    "last_complete_activity_month": "datetime64[us]",
}
OUTPUT_COLUMNS = [
    "cohort_month",
    "activity_month",
    "period_index",
    "cohort_size",
    "active_users",
    "activity_rate",
]
OUTPUT_DTYPES = {
    "cohort_month": "datetime64[us]",
    "activity_month": "datetime64[us]",
    "period_index": "int64",
    "cohort_size": "int64",
    "active_users": "int64",
    "activity_rate": "float64",
}


def load_artifact():
    spec = importlib.util.spec_from_file_location("duckdb_dataframe_query", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_cohort_activity() -> pd.DataFrame:
    """Small typed reference result with the same contract as lesson 04/10."""

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
            "business_timezone": pd.Series(
                ["Europe/Moscow"] * 7,
                dtype="string",
            ),
            "last_complete_activity_month": pd.to_datetime(["2026-04-01"] * 7),
        }
    )


def main() -> None:
    query = load_artifact()
    cohort_activity = build_cohort_activity()
    connection = duckdb.connect()
    try:
        result = query.query_dataframe(
            connection,
            sql=SQL.read_text(encoding="utf-8"),
            relation_name="cohort_activity",
            frame=cohort_activity,
            parameters={"cohort_month": "2026-01-01", "max_period": 2},
            expected_input_columns=INPUT_COLUMNS,
            expected_input_dtypes=INPUT_DTYPES,
            expected_output_columns=OUTPUT_COLUMNS,
            expected_output_dtypes=OUTPUT_DTYPES,
        )
    finally:
        connection.close()

    payload = {
        "rows": len(result),
        "dtypes": {column: str(dtype) for column, dtype in result.dtypes.items()},
        "records": result.to_dict(orient="records"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
