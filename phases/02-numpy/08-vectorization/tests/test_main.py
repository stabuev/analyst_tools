from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "vectorization_benchmark.py"
SPEC = importlib.util.spec_from_file_location("vectorization_benchmark", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


class VectorizationBenchmarkTest(unittest.TestCase):
    def test_loop_and_vectorized_formulas_match(self) -> None:
        prices = [10.0, 20.0, 30.0]
        quantities = [1, 2, 3]
        discounts = [0.0, 0.1, 0.2]
        loop = BENCHMARK.python_net_revenue(prices, quantities, discounts)
        vector = BENCHMARK.numpy_net_revenue(
            np.array(prices),
            np.array(quantities),
            np.array(discounts),
        )
        self.assertAlmostEqual(loop, vector)

    def test_mismatched_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(BENCHMARK.BenchmarkError, "equal lengths"):
            BENCHMARK.python_net_revenue([1.0], [1, 2], [0.0])

    def test_input_generation_is_reproducible(self) -> None:
        first = BENCHMARK.generate_inputs(10, 42)
        second = BENCHMARK.generate_inputs(10, 42)
        for left, right in zip(first, second, strict=True):
            np.testing.assert_array_equal(left, right)

    def test_measurement_returns_all_positive_runs(self) -> None:
        median, runs = BENCHMARK.measure_seconds(lambda: sum(range(100)), repeat=3)
        self.assertGreaterEqual(median, 0)
        self.assertEqual(len(runs), 3)
        self.assertTrue(all(duration >= 0 for duration in runs))

    def test_benchmark_checks_results_before_timing(self) -> None:
        report = BENCHMARK.benchmark(size=1_000, repeat=3, seed=42)
        self.assertTrue(report["results_close"])
        self.assertGreater(report["loop_seconds"]["median"], 0)
        self.assertGreater(report["vectorized_seconds"]["median"], 0)
        self.assertGreater(report["speedup"], 0)

    def test_repeat_below_three_is_rejected(self) -> None:
        with self.assertRaisesRegex(BENCHMARK.BenchmarkError, "at least 3"):
            BENCHMARK.benchmark(size=100, repeat=2, seed=42)

    def test_cli_returns_benchmark_metadata(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--size", "1000", "--repeat", "3"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["size"], 1000)
        self.assertIn("input conversion excluded", report["timing_scope"])

    def test_cli_invalid_size_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--size", "0"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
