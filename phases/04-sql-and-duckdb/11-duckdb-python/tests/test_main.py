from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import duckdb
import pandas as pd
from pandas.testing import assert_frame_equal

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "duckdb_dataframe_query.py"
SQL = ROOT / "outputs" / "cohort_activity_slice.sql"
EXAMPLE = ROOT / "code" / "main.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


QUERY = load_module("duckdb_dataframe_query", ARTIFACT)
EXAMPLE_MODULE = load_module("duckdb_python_example", EXAMPLE)

INPUT_COLUMNS = EXAMPLE_MODULE.INPUT_COLUMNS
INPUT_DTYPES = EXAMPLE_MODULE.INPUT_DTYPES
OUTPUT_COLUMNS = EXAMPLE_MODULE.OUTPUT_COLUMNS
OUTPUT_DTYPES = EXAMPLE_MODULE.OUTPUT_DTYPES


def run_slice(
    connection: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
    *,
    cohort_month: str = "2026-01-01",
    max_period: int = 2,
) -> pd.DataFrame:
    return QUERY.query_dataframe(
        connection,
        sql=SQL.read_text(encoding="utf-8"),
        relation_name="cohort_activity",
        frame=frame,
        parameters={"cohort_month": cohort_month, "max_period": max_period},
        expected_input_columns=INPUT_COLUMNS,
        expected_input_dtypes=INPUT_DTYPES,
        expected_output_columns=OUTPUT_COLUMNS,
        expected_output_dtypes=OUTPUT_DTYPES,
    )


class DuckDBDataFrameQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        self.frame = EXAMPLE_MODULE.build_cohort_activity()

    def tearDown(self) -> None:
        self.connection.close()

    def test_reference_slice_has_expected_values_order_and_grain(self) -> None:
        result = run_slice(self.connection, self.frame)

        self.assertEqual(result["period_index"].tolist(), [0, 1, 2])
        self.assertEqual(result["active_users"].tolist(), [4, 3, 2])
        self.assertEqual(result["activity_rate"].tolist(), [1.0, 0.75, 0.5])
        self.assertFalse(result.duplicated(["cohort_month", "period_index"]).any())

    def test_named_cohort_parameter_changes_population_without_sql_change(self) -> None:
        january = run_slice(self.connection, self.frame, cohort_month="2026-01-01")
        february = run_slice(self.connection, self.frame, cohort_month="2026-02-01")

        self.assertEqual(january["cohort_size"].unique().tolist(), [4])
        self.assertEqual(february["cohort_size"].unique().tolist(), [3])

    def test_max_period_parameter_changes_horizon_without_sql_change(self) -> None:
        short = run_slice(self.connection, self.frame, max_period=1)
        long = run_slice(self.connection, self.frame, max_period=3)

        self.assertEqual(short["period_index"].tolist(), [0, 1])
        self.assertEqual(long["period_index"].tolist(), [0, 1, 2, 3])

    def test_bound_text_remains_a_value(self) -> None:
        payload = "x'; DROP TABLE cohort_activity; --"
        result = QUERY.execute_trusted_query(
            self.connection,
            "SELECT ?::VARCHAR AS value",
            [payload],
            expected_columns=["value"],
            expected_dtypes={"value": "str"},
        )

        self.assertEqual(result.loc[0, "value"], payload)

    def test_placeholder_does_not_turn_a_value_into_an_identifier(self) -> None:
        self.connection.register("cohort_activity", self.frame)
        try:
            result = QUERY.execute_trusted_query(
                self.connection,
                "SELECT ?::VARCHAR AS chosen FROM cohort_activity LIMIT 1",
                ["active_users"],
                expected_columns=["chosen"],
                expected_dtypes={"chosen": "str"},
            )
        finally:
            self.connection.unregister("cohort_activity")

        self.assertEqual(result.loc[0, "chosen"], "active_users")
        self.assertNotEqual(result.loc[0, "chosen"], self.frame.loc[0, "active_users"])

    def test_query_fails_before_dataframe_is_registered(self) -> None:
        with self.assertRaises(duckdb.CatalogException):
            self.connection.execute(SQL.read_text(encoding="utf-8"), {
                "cohort_month": "2026-01-01",
                "max_period": 2,
            })

    def test_helper_unregisters_input_after_success(self) -> None:
        run_slice(self.connection, self.frame)

        with self.assertRaises(duckdb.CatalogException):
            self.connection.execute("SELECT * FROM cohort_activity")

    def test_helper_unregisters_input_after_contract_failure(self) -> None:
        with self.assertRaisesRegex(QUERY.QueryContractError, "columns"):
            QUERY.query_dataframe(
                self.connection,
                sql=SQL.read_text(encoding="utf-8"),
                relation_name="cohort_activity",
                frame=self.frame,
                parameters={"cohort_month": "2026-01-01", "max_period": 2},
                expected_input_columns=INPUT_COLUMNS,
                expected_input_dtypes=INPUT_DTYPES,
                expected_output_columns=["wrong_name"],
                expected_output_dtypes={"wrong_name": "int64"},
            )

        with self.assertRaises(duckdb.CatalogException):
            self.connection.execute("SELECT * FROM cohort_activity")

    def test_helper_never_closes_caller_connection(self) -> None:
        run_slice(self.connection, self.frame)

        self.assertEqual(self.connection.execute("SELECT 42").fetchone(), (42,))

    def test_unnamed_in_memory_connections_do_not_share_registered_relations(self) -> None:
        second_connection = duckdb.connect()
        self.connection.register("cohort_activity", self.frame)
        try:
            with self.assertRaises(duckdb.CatalogException):
                second_connection.execute("SELECT * FROM cohort_activity")
        finally:
            self.connection.unregister("cohort_activity")
            second_connection.close()

    def test_result_columns_and_order_follow_contract(self) -> None:
        result = run_slice(self.connection, self.frame)

        self.assertEqual(result.columns.tolist(), OUTPUT_COLUMNS)

    def test_result_pandas_dtypes_follow_contract(self) -> None:
        result = run_slice(self.connection, self.frame)

        self.assertEqual(
            {column: str(dtype) for column, dtype in result.dtypes.items()},
            OUTPUT_DTYPES,
        )

    def test_output_column_drift_is_rejected(self) -> None:
        with self.assertRaisesRegex(QUERY.QueryContractError, "columns"):
            QUERY.execute_trusted_query(
                self.connection,
                "SELECT 1 AS actual",
                expected_columns=["expected"],
                expected_dtypes={"expected": "int64"},
            )

    def test_output_dtype_drift_is_rejected(self) -> None:
        with self.assertRaisesRegex(QUERY.QueryContractError, "dtype contract"):
            QUERY.execute_trusted_query(
                self.connection,
                "SELECT 1::BIGINT AS value",
                expected_columns=["value"],
                expected_dtypes={"value": "float64"},
            )

    def test_input_dtype_drift_is_rejected_before_registration(self) -> None:
        broken = self.frame.copy()
        broken["period_index"] = broken["period_index"].astype("string")

        with self.assertRaisesRegex(QUERY.QueryContractError, "input relation.*dtype"):
            run_slice(self.connection, broken)
        with self.assertRaises(duckdb.CatalogException):
            self.connection.execute("SELECT * FROM cohort_activity")

    def test_input_dataframe_is_not_mutated(self) -> None:
        before = self.frame.copy(deep=True)

        run_slice(self.connection, self.frame)

        assert_frame_equal(self.frame, before)

    def test_artifact_avoids_default_connection_cli_and_regex_guard(self) -> None:
        source = ARTIFACT.read_text(encoding="utf-8")

        self.assertNotIn("duckdb.sql(", source)
        self.assertNotIn("argparse", source)
        self.assertNotIn("re.compile", source)
        self.assertNotIn("READ_ONLY", source)

    def test_sql_uses_registered_relation_not_raw_file_ingestion(self) -> None:
        sql = SQL.read_text(encoding="utf-8")

        self.assertIn("FROM cohort_activity", sql)
        self.assertIn("$cohort_month", sql)
        self.assertIn("$max_period", sql)
        self.assertNotIn("read_csv", sql)
        self.assertNotIn("DOUBLE AS amount", sql)


if __name__ == "__main__":
    unittest.main()
