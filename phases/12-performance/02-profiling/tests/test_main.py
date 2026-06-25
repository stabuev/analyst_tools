from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "profiling_report.py"
SPEC = importlib.util.spec_from_file_location("profiling_report", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PROFILING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILING)


class ProfilingReportTest(unittest.TestCase):
    def test_generation_is_reproducible(self) -> None:
        first = PROFILING.generate_order_lines(rows=30, seed=42)
        second = PROFILING.generate_order_lines(rows=30, seed=42)
        self.assertEqual(first, second)

    def test_pipeline_output_has_unique_grain_and_metrics(self) -> None:
        result = PROFILING.profiled_pipeline(PROFILING.generate_order_lines(rows=240, seed=7))
        grain = {(row["week_start"], row["platform"]) for row in result}
        self.assertEqual(len(grain), len(result))
        self.assertEqual(len(result), 24)
        self.assertTrue(all(row["active_users"] > 0 for row in result))
        self.assertTrue(any(row["net_revenue_cents"] != 0 for row in result))

    def test_duplicate_order_line_is_rejected(self) -> None:
        lines = PROFILING.generate_order_lines(rows=10, seed=1)
        lines.append(dict(lines[0]))
        with self.assertRaisesRegex(PROFILING.ProfilingError, "duplicate order line grain"):
            PROFILING.profiled_pipeline(lines)

    def test_profile_report_contains_cpu_memory_and_timings(self) -> None:
        report = PROFILING.profile_pipeline(
            rows=1_000,
            seed=42,
            top_n=5,
            memory_budget_mb=8.0,
        )
        self.assertEqual(report["scenario"]["scenario_id"], "weekly-revenue-profile")
        self.assertIn("input generation excluded", report["scenario"]["timing_scope"])
        self.assertGreater(report["timings"]["wall_seconds"], 0)
        self.assertGreaterEqual(report["timings"]["process_seconds"], 0)
        self.assertEqual(report["cpu_profile"]["profiler"], "cProfile")
        self.assertLessEqual(len(report["cpu_profile"]["top_functions"]), 5)
        self.assertEqual(report["memory_profile"]["profiler"], "tracemalloc")
        self.assertGreater(report["memory_profile"]["peak_bytes"], 0)
        self.assertTrue(report["findings"])
        cpu_finding = next(row for row in report["findings"] if row["id"] == "top_cpu_function")
        self.assertNotEqual(cpu_finding["evidence"]["function"], "run_once")

    def test_profile_is_not_a_benchmark_claim(self) -> None:
        report = PROFILING.profile_pipeline(
            rows=500,
            seed=42,
            top_n=3,
            memory_budget_mb=8.0,
        )
        self.assertFalse(report["interpretation"]["profile_is_benchmark"])
        self.assertTrue(
            any("12/01" in note for note in report["interpretation"]["notes"]),
            report["interpretation"]["notes"],
        )

    def test_memory_budget_classification_can_block(self) -> None:
        report = PROFILING.profile_pipeline(
            rows=800,
            seed=42,
            top_n=3,
            memory_budget_mb=0.000001,
        )
        budget = next(row for row in report["findings"] if row["id"] == "memory_budget")
        self.assertEqual(budget["severity"], "block")

    def test_custom_pipeline_result_contract_is_validated(self) -> None:
        def broken_pipeline(lines: list[dict[str, object]]) -> list[dict[str, object]]:
            return [{"week_start": "2026-W01", "platform": "web"}]

        with self.assertRaisesRegex(PROFILING.ProfilingError, "result misses columns"):
            PROFILING.profile_pipeline(
                rows=20,
                seed=1,
                top_n=3,
                memory_budget_mb=8.0,
                pipeline=broken_pipeline,
            )

    def test_cli_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "profile.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--rows",
                    "1000",
                    "--seed",
                    "42",
                    "--top-n",
                    "5",
                    "--memory-budget-mb",
                    "8",
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stdout_report = json.loads(result.stdout)
            file_report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(stdout_report["scenario"], file_report["scenario"])
            self.assertEqual(file_report["result_contract"]["grain"], "week_start, platform")

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--rows", "0"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("profiling error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
