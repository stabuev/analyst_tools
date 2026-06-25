from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "duckdb_out_of_core_report.py"
SPEC = importlib.util.spec_from_file_location("duckdb_out_of_core_report", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DUCKDB_REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DUCKDB_REPORT)


class DuckDBOutOfCoreReportTest(unittest.TestCase):
    def test_workload_generation_is_reproducible_and_has_expected_columns(self) -> None:
        orders_a, users_a = DUCKDB_REPORT.generate_customer_revenue_workload(rows=512, users=64, seed=42)
        orders_b, users_b = DUCKDB_REPORT.generate_customer_revenue_workload(rows=512, users=64, seed=42)
        self.assertTrue(orders_a.equals(orders_b))
        self.assertTrue(users_a.equals(users_b))
        self.assertEqual(len(orders_a), 512)
        self.assertEqual(len(users_a), 64)
        self.assertIn("net_revenue_cents", orders_a.columns)
        self.assertIn("segment", users_a.columns)

    def test_invalid_workload_size_raises_lesson_error(self) -> None:
        with self.assertRaises(DUCKDB_REPORT.DuckDBOutOfCoreError):
            DUCKDB_REPORT.generate_customer_revenue_workload(rows=64, users=16, seed=42)
        with self.assertRaises(DUCKDB_REPORT.DuckDBOutOfCoreError):
            DUCKDB_REPORT.generate_customer_revenue_workload(rows=256, users=512, seed=42)

    def test_write_workload_files_creates_readable_parquet_sources(self) -> None:
        orders, users = DUCKDB_REPORT.generate_customer_revenue_workload(rows=512, users=64, seed=42)
        with tempfile.TemporaryDirectory() as tmp:
            paths = DUCKDB_REPORT.write_workload_files(orders, users, tmp)
            self.assertTrue(Path(paths["orders"]).is_file())
            self.assertTrue(Path(paths["users"]).is_file())
            connection = duckdb.connect(":memory:")
            try:
                order_count = connection.execute(
                    f"SELECT count(*) FROM read_parquet('{paths['orders']}')"
                ).fetchone()[0]
                user_count = connection.execute(
                    f"SELECT count(*) FROM read_parquet('{paths['users']}')"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(order_count, 512)
            self.assertEqual(user_count, 64)

    def test_configure_connection_sets_memory_temp_and_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            connection = duckdb.connect(":memory:")
            try:
                settings = DUCKDB_REPORT.configure_connection(
                    connection,
                    temp_directory=Path(tmp) / "spill",
                    memory_limit="64MB",
                    threads=1,
                    max_temp_directory_size="256MB",
                )
            finally:
                connection.close()
        self.assertEqual(settings["threads"], 1)
        self.assertIn("MiB", settings["memory_limit"])
        self.assertTrue(settings["temp_directory"].endswith("spill"))
        self.assertIn("MiB", settings["max_temp_directory_size"])

    def test_invalid_threads_raise_lesson_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            connection = duckdb.connect(":memory:")
            try:
                with self.assertRaises(DUCKDB_REPORT.DuckDBOutOfCoreError):
                    DUCKDB_REPORT.configure_connection(
                        connection,
                        temp_directory=tmp,
                        memory_limit="64MB",
                        threads=0,
                    )
            finally:
                connection.close()

    def test_plan_detection_finds_scans_and_blocking_operators(self) -> None:
        orders, users = DUCKDB_REPORT.generate_customer_revenue_workload(rows=960, users=120, seed=2026)
        with tempfile.TemporaryDirectory() as tmp:
            paths = DUCKDB_REPORT.write_workload_files(orders, users, tmp)
            connection = duckdb.connect(":memory:")
            try:
                DUCKDB_REPORT.configure_connection(
                    connection,
                    temp_directory=Path(tmp) / "spill",
                    memory_limit="64MB",
                    threads=1,
                )
                query = DUCKDB_REPORT.build_workload_query(paths)
                plan = DUCKDB_REPORT.explain_query(connection, query)
            finally:
                connection.close()
        operators = DUCKDB_REPORT.detect_plan_operators(plan)
        self.assertTrue(operators["PARQUET_SCAN"])
        self.assertTrue(operators["HASH_JOIN"])
        self.assertTrue(operators["HASH_GROUP_BY"])
        self.assertTrue(operators["WINDOW"])
        self.assertTrue(operators["ORDER_BY"])
        self.assertGreaterEqual(len(DUCKDB_REPORT.classify_blocking_operators(plan)), 3)

    def test_pandas_control_matches_duckdb_result(self) -> None:
        report = DUCKDB_REPORT.build_duckdb_out_of_core_report(
            rows=960,
            users=120,
            seed=2026,
            memory_limit="64MB",
            threads=1,
        )
        self.assertTrue(report["equivalence"]["matches_control"])
        self.assertGreater(report["equivalence"]["duckdb_rows"], 0)
        self.assertEqual(report["equivalence"]["diff_preview"], [])

    def test_profile_contains_runtime_evidence_and_result_contract(self) -> None:
        report = DUCKDB_REPORT.build_duckdb_out_of_core_report(
            rows=960,
            users=120,
            seed=42,
            memory_limit="64MB",
            threads=1,
        )
        self.assertTrue(report["profile"]["has_runtime_evidence"])
        self.assertIn("Total Time", report["profile"]["text"])
        self.assertTrue(report["interpretation"]["checks"]["profile_has_runtime_evidence"])
        self.assertTrue(report["interpretation"]["checks"]["result_matches_control"])

    def test_report_is_spill_ready_without_requiring_spill_observation(self) -> None:
        report = DUCKDB_REPORT.build_duckdb_out_of_core_report(
            rows=960,
            users=120,
            seed=7,
            memory_limit="64MB",
            threads=1,
        )
        self.assertTrue(report["interpretation"]["spill_ready"])
        self.assertIn("spill_observed", report["interpretation"])
        self.assertTrue(report["interpretation"]["safe_to_ship"])
        if not report["interpretation"]["spill_observed"]:
            self.assertTrue(report["interpretation"]["does_not_claim_spill"])

    def test_temp_directory_state_records_before_and_after_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = DUCKDB_REPORT.build_duckdb_out_of_core_report(
                rows=960,
                users=120,
                seed=42,
                output_dir=tmp,
            )
        self.assertTrue(report["temp_directory"]["before"]["exists"])
        self.assertTrue(report["temp_directory"]["after"]["exists"])
        self.assertIn("file_count", report["temp_directory"]["after"])

    def test_cli_writes_report_plan_profile_and_runbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "package"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "--rows",
                    "512",
                    "--users",
                    "64",
                    "--seed",
                    "42",
                    "--output-dir",
                    str(output_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stdout_report = json.loads(result.stdout)
            file_report = json.loads((output_dir / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(stdout_report["scenario"]["scenario_id"], file_report["scenario"]["scenario_id"])
            self.assertTrue((output_dir / "query-plan.txt").is_file())
            self.assertTrue((output_dir / "query-profile.txt").is_file())
            self.assertTrue((output_dir / "runbook.md").is_file())
            self.assertTrue((output_dir / "data" / "orders.parquet").is_file())

    def test_runbook_names_settings_operators_and_limitations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            DUCKDB_REPORT.build_duckdb_out_of_core_report(
                rows=512,
                users=64,
                seed=42,
                output_dir=tmp,
            )
            runbook = (Path(tmp) / "runbook.md").read_text(encoding="utf-8")
        self.assertIn("memory_limit", runbook)
        self.assertIn("temp_directory", runbook)
        self.assertIn("threads", runbook)
        self.assertIn("HASH_GROUP_BY", runbook)
        self.assertIn("Actual spill is environment-dependent", runbook)

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ARTIFACT), "--rows", "64"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("duckdb out-of-core error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
