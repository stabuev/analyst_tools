from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "duckdb_plan_audit.py"
BASELINE_SQL = (ROOT / "outputs" / "repeated_scan.sql").read_text(encoding="utf-8")
CANDIDATE_SQL = (ROOT / "outputs" / "single_scan.sql").read_text(encoding="utf-8")
SPEC = importlib.util.spec_from_file_location("duckdb_plan_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PLANS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLANS)


def build_cohort_activity() -> pd.DataFrame:
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


class DuckDBPlanAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frame = build_cohort_activity()
        connection = duckdb.connect()
        try:
            cls.report = PLANS.compare_dataframe_queries(
                connection,
                relation_name="cohort_activity",
                frame=cls.frame,
                baseline_sql=BASELINE_SQL,
                candidate_sql=CANDIDATE_SQL,
                parameters={"cohort_month": "2026-01-01"},
            )
        finally:
            connection.close()

    def test_equivalent_queries_return_exact_same_result(self) -> None:
        self.assertTrue(self.report["results_equal"])
        self.assertEqual(
            self.report["result"].to_dict(orient="records"),
            [{"cohort_period_rows": 4, "active_user_period_sum": 9}],
        )
        self.assertEqual(
            {column: str(dtype) for column, dtype in self.report["result"].dtypes.items()},
            {"cohort_period_rows": "int64", "active_user_period_sum": "int64"},
        )

    def test_baseline_has_two_scan_branches(self) -> None:
        self.assertEqual(self.report["baseline"]["summary"]["scan_operators"], 2)
        self.assertIn(
            "CROSS_PRODUCT",
            self.report["baseline"]["operators"]["operator"].tolist(),
        )

    def test_candidate_has_one_scan_branch(self) -> None:
        self.assertEqual(self.report["candidate"]["summary"]["scan_operators"], 1)
        self.assertEqual(self.report["comparison"]["scan_operators_removed"], 1)

    def test_rows_scanned_are_reported_separately_from_output_rows(self) -> None:
        self.assertEqual(self.report["baseline"]["summary"]["rows_scanned"], 14)
        self.assertEqual(self.report["candidate"]["summary"]["rows_scanned"], 7)
        candidate_scan = self.report["candidate"]["operators"].loc[
            self.report["candidate"]["operators"]["operator"].str.contains("SCAN", regex=False)
        ]
        self.assertEqual(candidate_scan["actual_rows"].tolist(), [7])
        self.assertEqual(candidate_scan["rows_scanned"].tolist(), [7])

    def test_operator_table_has_stable_evidence_columns(self) -> None:
        self.assertEqual(
            self.report["candidate"]["operators"].columns.tolist(),
            PLANS.OPERATOR_COLUMNS,
        )

    def test_plan_is_read_from_root_to_deeper_paths(self) -> None:
        operators = self.report["candidate"]["operators"]
        self.assertEqual(operators.iloc[0]["path"], "0")
        self.assertIn(
            operators.iloc[0]["operator"],
            {"PROJECTION", "UNGROUPED_AGGREGATE"},
        )
        self.assertTrue(operators.iloc[-1]["path"].startswith("0."))
        self.assertIn("SCAN", operators.iloc[-1]["operator"])

    def test_explain_estimate_and_analyze_actual_are_both_present(self) -> None:
        baseline_filters = self.report["baseline"]["operators"].query("operator == 'FILTER'")
        self.assertEqual(baseline_filters["estimated_rows"].tolist(), [1, 1])
        self.assertEqual(baseline_filters["actual_rows"].tolist(), [4, 4])

    def test_analyze_timings_are_observations_not_a_winner(self) -> None:
        timings = self.report["candidate"]["operators"]["timing_seconds"]
        self.assertTrue(timings.ge(0).all())
        self.assertTrue(self.report["comparison"]["timing_is_observation_not_verdict"])
        self.assertNotIn("faster_query", self.report["comparison"])

    def test_raw_plans_are_structured_json(self) -> None:
        self.assertIsInstance(self.report["baseline"]["explain_json"], list)
        self.assertIsInstance(self.report["baseline"]["analyze_json"], dict)

    def test_report_preserves_reproducible_scope(self) -> None:
        scope = self.report["scope"]
        self.assertEqual(scope["engine"], "duckdb")
        self.assertEqual(scope["engine_version"], duckdb.__version__)
        self.assertEqual(scope["relation_name"], "cohort_activity")
        self.assertEqual(scope["input_rows"], 7)
        self.assertEqual(
            self.report["baseline"]["parameters"],
            {"cohort_month": "2026-01-01"},
        )
        self.assertIn("SELECT", self.report["baseline"]["sql"])
        self.assertIn("not a benchmark", scope["claim_boundary"])

    def test_parameter_changes_the_selected_cohort(self) -> None:
        connection = duckdb.connect()
        try:
            report = PLANS.compare_dataframe_queries(
                connection,
                relation_name="cohort_activity",
                frame=self.frame,
                baseline_sql=BASELINE_SQL,
                candidate_sql=CANDIDATE_SQL,
                parameters={"cohort_month": "2026-02-01"},
            )
        finally:
            connection.close()
        self.assertEqual(
            report["result"].to_dict(orient="records"),
            [{"cohort_period_rows": 3, "active_user_period_sum": 6}],
        )

    def test_missing_cohort_preserves_unknown_sum(self) -> None:
        connection = duckdb.connect()
        try:
            report = PLANS.compare_dataframe_queries(
                connection,
                relation_name="cohort_activity",
                frame=self.frame,
                baseline_sql=BASELINE_SQL,
                candidate_sql=CANDIDATE_SQL,
                parameters={"cohort_month": "2030-01-01"},
            )
        finally:
            connection.close()
        record = report["result"].to_dict(orient="records")[0]
        self.assertEqual(record["cohort_period_rows"], 0)
        self.assertTrue(pd.isna(record["active_user_period_sum"]))

    def test_different_result_blocks_plan_comparison(self) -> None:
        broken_candidate = CANDIDATE_SQL.replace(
            "AS active_user_period_sum",
            "+ 1 AS active_user_period_sum",
        )
        connection = duckdb.connect()
        try:
            with self.assertRaisesRegex(
                PLANS.QueryPlanAuditError,
                "result differs",
            ):
                PLANS.compare_dataframe_queries(
                    connection,
                    relation_name="cohort_activity",
                    frame=self.frame,
                    baseline_sql=BASELINE_SQL,
                    candidate_sql=broken_candidate,
                    parameters={"cohort_month": "2026-01-01"},
                )
        finally:
            connection.close()

    def test_temporary_relation_is_removed_after_success(self) -> None:
        connection = duckdb.connect()
        try:
            PLANS.compare_dataframe_queries(
                connection,
                relation_name="cohort_activity",
                frame=self.frame,
                baseline_sql=BASELINE_SQL,
                candidate_sql=CANDIDATE_SQL,
                parameters={"cohort_month": "2026-01-01"},
            )
            with self.assertRaises(duckdb.CatalogException):
                connection.execute("SELECT * FROM cohort_activity")
            self.assertEqual(connection.execute("SELECT 42").fetchone(), (42,))
        finally:
            connection.close()

    def test_temporary_relation_is_removed_after_failure(self) -> None:
        connection = duckdb.connect()
        try:
            with self.assertRaises(duckdb.Error):
                PLANS.compare_dataframe_queries(
                    connection,
                    relation_name="cohort_activity",
                    frame=self.frame,
                    baseline_sql=BASELINE_SQL,
                    candidate_sql="SELECT missing_column FROM cohort_activity",
                    parameters={"cohort_month": "2026-01-01"},
                )
            with self.assertRaises(duckdb.CatalogException):
                connection.execute("SELECT * FROM cohort_activity")
        finally:
            connection.close()

    def test_join_plan_can_be_read_as_two_inputs_and_one_join(self) -> None:
        connection = duckdb.connect()
        connection.register(
            "cohorts",
            pd.DataFrame(
                {"cohort_id": [1, 2], "cohort_size": [4, 3]},
            ),
        )
        connection.register(
            "segments",
            pd.DataFrame(
                {"cohort_id": [1, 2], "segment": ["new", "returning"]},
            ),
        )
        try:
            inspection = PLANS.inspect_reviewed_query(
                connection,
                sql="""
                    SELECT c.cohort_id, c.cohort_size, s.segment
                    FROM cohorts AS c
                    INNER JOIN segments AS s USING (cohort_id)
                    ORDER BY c.cohort_id
                """,
            )
        finally:
            connection.unregister("cohorts")
            connection.unregister("segments")
            connection.close()
        operator_names = inspection["operators"]["operator"].tolist()
        self.assertEqual(sum("SCAN" in name for name in operator_names), 2)
        self.assertIn("HASH_JOIN", operator_names)
        join_row = inspection["operators"].query("operator == 'HASH_JOIN'").iloc[0]
        self.assertEqual(join_row["actual_rows"], 2)

    def test_empty_sql_is_rejected_before_explain(self) -> None:
        connection = duckdb.connect()
        try:
            with self.assertRaisesRegex(PLANS.QueryPlanAuditError, "must not be empty"):
                PLANS.inspect_reviewed_query(connection, sql="  ")
        finally:
            connection.close()

    def test_invalid_relation_name_is_rejected(self) -> None:
        connection = duckdb.connect()
        try:
            with self.assertRaisesRegex(PLANS.QueryPlanAuditError, "relation_name"):
                PLANS.compare_dataframe_queries(
                    connection,
                    relation_name="cohort activity",
                    frame=self.frame,
                    baseline_sql=BASELINE_SQL,
                    candidate_sql=CANDIDATE_SQL,
                )
        finally:
            connection.close()

    def test_non_dataframe_input_is_rejected(self) -> None:
        connection = duckdb.connect()
        try:
            with self.assertRaisesRegex(PLANS.QueryPlanAuditError, "pandas DataFrame"):
                PLANS.compare_dataframe_queries(
                    connection,
                    relation_name="cohort_activity",
                    frame=[{"cohort_month": "2026-01-01"}],
                    baseline_sql=BASELINE_SQL,
                    candidate_sql=CANDIDATE_SQL,
                )
        finally:
            connection.close()

    def test_artifact_has_no_cli_or_text_plan_regex(self) -> None:
        source = ARTIFACT.read_text(encoding="utf-8")
        self.assertNotIn("argparse", source)
        self.assertNotIn("Total Time:", source)
        self.assertIn("FORMAT JSON", source)


if __name__ == "__main__":
    unittest.main()
