from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "duckdb_runner.py"
SQL = ROOT / "outputs" / "paid_orders.sql"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("duckdb_runner", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class DuckDBRunnerTest(unittest.TestCase):
    def test_query_returns_dataframe_and_metadata(self) -> None:
        frame, metadata = RUNNER.execute_query(
            SQL.read_text(encoding="utf-8"),
            [str(DATA), 500],
        )
        self.assertIsInstance(frame, pd.DataFrame)
        self.assertEqual(metadata["rows"], 5)
        self.assertEqual(metadata["columns"], ["order_id", "user_id", "currency", "amount"])

    def test_parameter_changes_result_without_changing_sql(self) -> None:
        sql = SQL.read_text(encoding="utf-8")
        low, _ = RUNNER.execute_query(sql, [str(DATA), 500])
        high, _ = RUNNER.execute_query(sql, [str(DATA), 1000])
        self.assertEqual(len(low), 5)
        self.assertEqual(len(high), 2)

    def test_parameter_is_not_executed_as_sql(self) -> None:
        frame, _ = RUNNER.execute_query(
            "SELECT ?::VARCHAR AS value",
            ["x'; DROP TABLE orders; --"],
            expected_columns=["value"],
        )
        self.assertEqual(frame.iloc[0]["value"], "x'; DROP TABLE orders; --")

    def test_expected_columns_are_enforced(self) -> None:
        with self.assertRaisesRegex(RUNNER.QueryContractError, "differ"):
            RUNNER.execute_query("SELECT 1 AS actual", expected_columns=["expected"])

    def test_non_read_only_statement_is_rejected(self) -> None:
        with self.assertRaisesRegex(RUNNER.QueryContractError, "read-only"):
            RUNNER.execute_query("CREATE TABLE example(value INTEGER)")

    def test_caller_owned_connection_remains_open(self) -> None:
        connection = duckdb.connect()
        try:
            _, metadata = RUNNER.execute_query("SELECT 1 AS value", connection=connection)
            self.assertFalse(metadata["connection_owned_by_runner"])
            self.assertEqual(connection.execute("SELECT 2").fetchone(), (2,))
        finally:
            connection.close()

    def test_runner_owned_connection_is_reported(self) -> None:
        _, metadata = RUNNER.execute_query("SELECT 1 AS value")
        self.assertTrue(metadata["connection_owned_by_runner"])

    def test_cli_prints_records(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--sql-file",
                SQL,
                "--params-json",
                json.dumps([str(DATA), 1000]),
                "--expected-columns",
                "order_id,user_id,currency,amount",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["metadata"]["rows"], 2)


if __name__ == "__main__":
    unittest.main()
