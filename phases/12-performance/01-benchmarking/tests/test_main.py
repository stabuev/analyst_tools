from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "benchmark_harness.py"
SPEC = importlib.util.spec_from_file_location("benchmark_harness", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


class BenchmarkHarnessTest(unittest.TestCase):
    def test_generation_is_reproducible_and_hashable(self) -> None:
        first = HARNESS.generate_order_lines(rows=20, seed=42)
        second = HARNESS.generate_order_lines(rows=20, seed=42)
        self.assertEqual(first, second)
        self.assertEqual(HARNESS.stable_json_hash(first), HARNESS.stable_json_hash(second))

    def test_reference_and_candidate_outputs_match(self) -> None:
        lines = HARNESS.generate_order_lines(rows=120, seed=7)
        comparison = HARNESS.compare_outputs(
            HARNESS.reference_weekly_revenue(lines),
            HARNESS.candidate_weekly_revenue(lines),
        )
        self.assertTrue(comparison["passed"], comparison)
        self.assertEqual(comparison["row_count"], 4)
        self.assertEqual(comparison["reference_checksum"], comparison["candidate_checksum"])

    def test_duplicate_grain_is_rejected_by_reference_pipeline(self) -> None:
        lines = HARNESS.generate_order_lines(rows=5, seed=1)
        lines.append(dict(lines[0]))
        with self.assertRaisesRegex(HARNESS.BenchmarkError, "duplicate order line grain"):
            HARNESS.reference_weekly_revenue(lines)

    def test_scenario_requires_equivalence_and_repeats(self) -> None:
        scenario = HARNESS.default_scenario(rows=100, repeat=3)
        scenario["equivalence_checks"] = []
        with self.assertRaisesRegex(HARNESS.BenchmarkError, "equivalence"):
            HARNESS.validate_scenario(scenario)

        scenario = HARNESS.default_scenario(rows=100, repeat=2)
        with self.assertRaisesRegex(HARNESS.BenchmarkError, "at least 3"):
            HARNESS.validate_scenario(scenario)

    def test_benchmark_checks_equivalence_before_timing(self) -> None:
        def broken_candidate(lines: list[dict[str, object]]) -> list[dict[str, object]]:
            result = HARNESS.candidate_weekly_revenue(lines)
            result[0]["net_revenue_cents"] += 1
            return result

        with self.assertRaisesRegex(HARNESS.BenchmarkError, "equivalence gate failed"):
            HARNESS.run_benchmark(rows=200, repeat=3, seed=42, candidate=broken_candidate)

    def test_benchmark_report_contains_raw_runs_summary_and_environment(self) -> None:
        report = HARNESS.run_benchmark(rows=1_000, repeat=3, seed=42)
        self.assertTrue(report["equivalence"]["passed"])
        self.assertTrue(report["input"]["generation_excluded_from_timing"])
        self.assertEqual(len(report["measurements"]["raw_runs"]), 6)
        self.assertEqual(
            {row["implementation"] for row in report["measurements"]["summary"]},
            {"python_reference", "python_candidate"},
        )
        self.assertIn("python_version", report["environment"])
        self.assertTrue(report["decision"]["usable_for_engine_decision"])

    def test_measurement_is_not_single_run_and_uses_warmup(self) -> None:
        calls = {"count": 0}

        def function() -> list[dict[str, object]]:
            calls["count"] += 1
            return []

        runs = HARNESS.measure_seconds(
            function,
            implementation="demo",
            repeat=3,
            warmup=2,
        )
        self.assertEqual(calls["count"], 5)
        self.assertEqual(len(runs), 3)
        self.assertTrue(all(run["seconds"] >= 0 for run in runs))

    def test_cli_writes_reusable_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "benchmark-package"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--rows",
                    "1000",
                    "--repeat",
                    "3",
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
            report = json.loads(result.stdout)
            self.assertEqual(report["scenario"]["scale_rows"], 1000)
            self.assertTrue((output_dir / "benchmark-plan.json").is_file())
            self.assertTrue((output_dir / "measurements" / "environment.json").is_file())
            self.assertTrue((output_dir / "equivalence" / "output-checks.json").is_file())
            with (output_dir / "measurements" / "raw-runs.csv").open(encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 6)

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--rows", "0"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("benchmark error", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
