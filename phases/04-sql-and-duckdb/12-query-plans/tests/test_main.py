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
ARTIFACT = ROOT / "outputs" / "plan_report.py"
DATA = ROOT.parent / "data" / "tiny" / "events.csv"
SPEC = importlib.util.spec_from_file_location("plan_report", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PLANS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLANS)


class PlanReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = duckdb.connect()
        self.report = PLANS.build_plan_report(self.connection, DATA)
        self.baseline, self.candidate = self.report["variants"]

    def tearDown(self) -> None:
        self.connection.close()

    def test_equivalent_queries_return_same_detailed_result(self) -> None:
        self.assertTrue(self.report["comparison"]["results_equal"])
        self.assertEqual(
            self.baseline["result"],
            {"event_rows": 6, "active_users": 3},
        )
        self.assertEqual(self.candidate["result"], self.baseline["result"])

    def test_static_plan_reveals_two_reads_and_one_read(self) -> None:
        self.assertEqual(self.baseline["explain"]["source_read_nodes"], 2)
        self.assertEqual(self.candidate["explain"]["source_read_nodes"], 1)
        self.assertEqual(self.report["comparison"]["source_reads_removed"], 1)

    def test_analyzed_plan_preserves_the_same_source_read_shape(self) -> None:
        self.assertEqual(
            self.baseline["explain_analyze"]["source_read_nodes"],
            2,
        )
        self.assertEqual(
            self.candidate["explain_analyze"]["source_read_nodes"],
            1,
        )

    def test_explain_contains_estimates_but_no_total_time(self) -> None:
        evidence = self.candidate["explain"]
        self.assertTrue(evidence["estimated_row_markers"])
        self.assertEqual(evidence["actual_row_markers"], [])
        self.assertIsNone(evidence["total_time_seconds"])
        self.assertIn("~", evidence["plan_text"])

    def test_explain_analyze_contains_actual_rows_and_total_time(self) -> None:
        evidence = self.candidate["explain_analyze"]
        self.assertTrue(evidence["actual_row_markers"])
        self.assertEqual(evidence["estimated_row_markers"], [])
        self.assertIsInstance(evidence["total_time_seconds"], float)
        self.assertIn(16, evidence["actual_row_markers"])

    def test_estimate_is_not_treated_as_actual_cardinality(self) -> None:
        estimated = self.candidate["explain"]["estimated_row_markers"]
        actual = self.candidate["explain_analyze"]["actual_row_markers"]
        self.assertNotEqual(estimated, actual)
        self.assertIn(16, actual)

    def test_plan_text_contains_the_operators_used_in_the_lesson(self) -> None:
        plan = self.candidate["explain"]["plan_text"]
        self.assertIn("READ_CSV", plan)
        self.assertIn("PROJECTION", plan)
        self.assertIn("UNGROUPED_AGGREGATE", plan)

    def test_wrong_population_blocks_optimization_conclusion(self) -> None:
        report = PLANS.build_plan_report(
            self.connection,
            DATA,
            candidate_sql=PLANS.WRONG_POPULATION_SQL,
            candidate_label="wrong_population",
        )
        self.assertFalse(report["comparison"]["results_equal"])
        self.assertFalse(report["comparison"]["safe_to_compare_work"])
        self.assertIn("blocked", report["comparison"]["conclusion"])
        self.assertEqual(
            report["variants"][1]["result"],
            {"event_rows": 6, "active_users": 8},
        )

    def test_zero_matching_events_remain_semantically_equivalent(self) -> None:
        report = PLANS.build_plan_report(
            self.connection,
            DATA,
            event_name="not_present",
        )
        self.assertTrue(report["comparison"]["results_equal"])
        self.assertEqual(
            report["variants"][1]["result"],
            {"event_rows": 0, "active_users": 0},
        )

    def test_report_does_not_claim_timing_proves_speedup(self) -> None:
        comparison = self.report["comparison"]
        self.assertFalse(comparison["timing_claim_allowed"])
        self.assertIn("timing remains an observation", comparison["conclusion"])
        self.assertIn("does not guarantee", self.report["scope"]["claim_boundary"])

    def test_report_records_engine_and_input_scope(self) -> None:
        scope = self.report["scope"]
        self.assertEqual(scope["engine"], "duckdb")
        self.assertEqual(scope["engine_version"], duckdb.__version__)
        self.assertEqual(scope["events_path"], str(DATA.resolve()))
        self.assertEqual(scope["event_name"], "order_paid")
        self.assertIn("SELECT", self.baseline["sql"])
        self.assertIn(str(DATA.resolve()), self.baseline["parameters"])

    def test_caller_owned_connection_remains_usable(self) -> None:
        self.assertEqual(self.connection.execute("SELECT 42").fetchone(), (42,))

    def test_missing_events_file_is_rejected(self) -> None:
        with self.assertRaisesRegex(PLANS.PlanAuditError, "does not exist"):
            PLANS.build_plan_report(
                self.connection,
                ROOT / "missing.csv",
            )

    def test_empty_event_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(PLANS.PlanAuditError, "non-empty"):
            PLANS.build_plan_report(self.connection, DATA, "   ")

    def test_untrusted_candidate_sql_is_rejected(self) -> None:
        with self.assertRaisesRegex(PLANS.PlanAuditError, "trusted built-in"):
            PLANS.build_plan_report(
                self.connection,
                DATA,
                candidate_sql="SELECT 1, 2",
            )

    def test_cli_prints_complete_json_report(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--events", DATA],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["comparison"]["source_reads_removed"], 1)
        self.assertIn("plan_text", report["variants"][0]["explain"])

    def test_cli_can_write_standalone_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "plan-audit.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--events",
                    DATA,
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()), output)
            self.assertTrue(
                json.loads(output.read_text(encoding="utf-8"))["comparison"]["results_equal"]
            )

    def test_cli_rejects_missing_input(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--events",
                ROOT / "missing.csv",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not exist", result.stderr)


if __name__ == "__main__":
    unittest.main()
