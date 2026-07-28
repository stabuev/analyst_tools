from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

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
        self.report = PLANS.compare_plans(DATA)
        self.two_scans, self.one_scan = self.report["queries"]

    def test_equivalent_queries_return_same_result(self) -> None:
        self.assertTrue(self.report["checks"]["results_equal"])
        self.assertEqual(self.one_scan["result"], {"event_rows": 6, "active_users": 3})

    def test_inefficient_query_reads_source_twice(self) -> None:
        self.assertEqual(self.two_scans["scan_nodes"], 2)

    def test_optimized_query_reads_source_once(self) -> None:
        self.assertEqual(self.one_scan["scan_nodes"], 1)
        self.assertTrue(self.report["checks"]["optimized_has_one_scan"])

    def test_report_counts_removed_scan(self) -> None:
        self.assertEqual(self.report["checks"]["scan_nodes_removed"], 1)

    def test_explain_analyze_contains_actual_rows(self) -> None:
        self.assertIn("rows", self.one_scan["plan"])
        self.assertIn("Total Time:", self.one_scan["plan"])

    def test_total_time_is_parsed_but_not_asserted_as_speedup(self) -> None:
        self.assertIsInstance(self.one_scan["total_time_seconds"], float)
        self.assertIn("not a guarantee", self.report["interpretation"])

    def test_other_event_parameter_is_supported(self) -> None:
        report = PLANS.compare_plans(DATA, "trial_started")
        self.assertEqual(report["queries"][1]["result"], {"event_rows": 2, "active_users": 2})

    def test_cli_prints_json(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--events", DATA],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["checks"]["scan_nodes_removed"], 1)


if __name__ == "__main__":
    unittest.main()
