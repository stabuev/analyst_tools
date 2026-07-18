from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "vectorization_benchmark.py"
SPEC = importlib.util.spec_from_file_location("vectorization_benchmark", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


class VectorizationBenchmarkTest(unittest.TestCase):
    def test_line_and_total_formulas_match_known_answer(self) -> None:
        prices = np.array([10.0, 20.0, 30.0])
        quantities = np.array([2, 2, 3], dtype=np.int64)
        discounts = np.array([0.0, 0.1, 0.2])
        expected_rows = np.array([20.0, 36.0, 72.0])

        loop_rows = BENCHMARK.python_line_revenue(
            prices.tolist(),
            quantities.tolist(),
            discounts.tolist(),
        )
        vector_rows = BENCHMARK.numpy_line_revenue(
            prices,
            quantities,
            discounts,
        )
        np.testing.assert_allclose(loop_rows, expected_rows)
        np.testing.assert_allclose(vector_rows, expected_rows)
        self.assertAlmostEqual(
            BENCHMARK.python_net_revenue(
                prices.tolist(),
                quantities.tolist(),
                discounts.tolist(),
            ),
            128.0,
        )
        self.assertAlmostEqual(
            BENCHMARK.numpy_net_revenue(prices, quantities, discounts),
            128.0,
        )

    def test_prepare_inputs_normalizes_dtypes_and_layout(self) -> None:
        prices, quantities, discounts = BENCHMARK.prepare_inputs(
            np.array([10, 20], dtype=np.int16),
            np.array([1, 2], dtype=np.int8),
            np.array([0.0, 0.1], dtype=np.float32),
        )
        self.assertEqual(prices.dtype, np.dtype("float64"))
        self.assertEqual(quantities.dtype, np.dtype("int64"))
        self.assertEqual(discounts.dtype, np.dtype("float64"))
        self.assertTrue(prices.flags.c_contiguous)
        self.assertTrue(quantities.flags.c_contiguous)
        self.assertTrue(discounts.flags.c_contiguous)

    def test_mismatched_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(BENCHMARK.BenchmarkError, "equal shapes"):
            BENCHMARK.prepare_inputs([10.0], [1, 2], [0.0])
        with self.assertRaisesRegex(BENCHMARK.BenchmarkError, "equal lengths"):
            BENCHMARK.python_net_revenue([10.0], [1, 2], [0.0])

    def test_non_vector_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(BENCHMARK.BenchmarkError, "one-dimensional"):
            BENCHMARK.prepare_inputs(
                np.array([[10.0]]),
                np.array([[1]]),
                np.array([[0.0]]),
            )

    def test_non_numeric_and_boolean_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(BENCHMARK.BenchmarkError, "numeric"):
            BENCHMARK.prepare_inputs(["ten"], [1], [0.0])
        with self.assertRaisesRegex(BENCHMARK.BenchmarkError, "real numeric"):
            BENCHMARK.prepare_inputs([10.0 + 1.0j], [1], [0.0])
        with self.assertRaisesRegex(BENCHMARK.BenchmarkError, "boolean"):
            BENCHMARK.prepare_inputs([True], [1], [0.0])

    def test_fractional_quantities_are_rejected(self) -> None:
        with self.assertRaisesRegex(BENCHMARK.BenchmarkError, "integer dtype"):
            BENCHMARK.prepare_inputs([10.0], [1.5], [0.0])

    def test_invalid_business_domains_are_rejected(self) -> None:
        invalid_cases = [
            (([-1.0], [1], [0.0]), "prices must be non-negative"),
            (([np.nan], [1], [0.0]), "prices must contain only finite"),
            (([10.0], [-1], [0.0]), "quantities must be non-negative"),
            (([10.0], [1], [-0.1]), "discounts must be between"),
            (([10.0], [1], [1.1]), "discounts must be between"),
            (([10.0], [1], [np.inf]), "discounts must contain only finite"),
        ]
        for arguments, message in invalid_cases:
            with (
                self.subTest(arguments=arguments),
                self.assertRaisesRegex(
                    BENCHMARK.BenchmarkError,
                    message,
                ),
            ):
                BENCHMARK.prepare_inputs(*arguments)

    def test_input_generation_is_reproducible(self) -> None:
        first = BENCHMARK.generate_inputs(10, 42)
        second = BENCHMARK.generate_inputs(10, 42)
        for left, right in zip(first, second, strict=True):
            np.testing.assert_array_equal(left, right)

    def test_different_seed_changes_generated_values(self) -> None:
        first = BENCHMARK.generate_inputs(10, 42)
        second = BENCHMARK.generate_inputs(10, 43)
        self.assertFalse(np.array_equal(first[0], second[0]))

    def test_line_level_gate_catches_compensating_errors(self) -> None:
        prices, quantities, discounts = BENCHMARK.generate_inputs(10, 42)
        price_list = prices.tolist()
        quantity_list = quantities.tolist()
        discount_list = discounts.tolist()
        original = BENCHMARK.numpy_line_revenue

        def reversed_rows(*args: object) -> np.ndarray:
            return original(*args)[::-1]

        with (
            mock.patch.object(
                BENCHMARK,
                "numpy_line_revenue",
                side_effect=reversed_rows,
            ),
            self.assertRaisesRegex(
                BENCHMARK.BenchmarkError,
                "line-level implementations disagree",
            ),
        ):
            BENCHMARK.compare_results(
                price_list,
                quantity_list,
                discount_list,
                prices,
                quantities,
                discounts,
            )

    def test_measurement_returns_positive_runs_and_median(self) -> None:
        median, runs = BENCHMARK.measure_seconds(
            lambda: float(sum(range(100))),
            repeat=5,
        )
        self.assertEqual(len(runs), 5)
        self.assertTrue(all(duration > 0 for duration in runs))
        self.assertEqual(median, sorted(runs)[2])

    def test_invalid_repeat_size_and_seed_are_rejected(self) -> None:
        invalid_calls = [
            lambda: BENCHMARK.benchmark(size=0, repeat=3, seed=42),
            lambda: BENCHMARK.benchmark(size=100, repeat=2, seed=42),
            lambda: BENCHMARK.benchmark(size=100, repeat=102, seed=42),
            lambda: BENCHMARK.benchmark(size=100, repeat=3, seed=-1),
        ]
        for call in invalid_calls:
            with self.subTest(call=call), self.assertRaises(BENCHMARK.BenchmarkError):
                call()

    def test_memory_estimate_has_explicit_boundary(self) -> None:
        report = BENCHMARK.estimate_array_memory(10)
        self.assertEqual(report["input_array_bytes"], 240)
        self.assertEqual(report["one_float64_vector_bytes"], 80)
        self.assertEqual(
            report["straight_expression_estimated_peak_temporary_bytes"],
            240,
        )
        self.assertIn("excludes", report["estimate_boundary"])

    def test_benchmark_report_records_correctness_scope_and_environment(self) -> None:
        report = BENCHMARK.benchmark(size=1_000, repeat=3, seed=42)
        self.assertTrue(report["correctness"]["line_values_close"])
        self.assertTrue(report["correctness"]["totals_close"])
        self.assertEqual(report["correctness"]["line_shape"], [1_000])
        self.assertEqual(report["input_contract"]["axis_names"], ["line_item"])
        self.assertEqual(report["scope"]["name"], "calculation_only")
        self.assertIn("input validation", report["scope"]["excluded"])
        self.assertEqual(report["timing"]["repeat"], 3)
        self.assertGreater(
            report["timing"]["speedup_loop_over_vectorized"],
            0,
        )
        self.assertIn("python_version", report["environment"])
        self.assertIn("numpy_version", report["environment"])
        self.assertIn("not a universal", report["claim_boundary"])

    def test_small_input_does_not_require_a_particular_speedup(self) -> None:
        report = BENCHMARK.benchmark(size=1, repeat=3, seed=42)
        self.assertGreater(
            report["timing"]["speedup_loop_over_vectorized"],
            0,
        )

    def test_cli_writes_the_same_structured_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir) / "report.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--size",
                    "1000",
                    "--repeat",
                    "3",
                    "--output",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["input_generation"]["size"], 1_000)
            self.assertEqual(report["scope"]["name"], "calculation_only")

    def test_cli_invalid_input_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--size", "0"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("size must be between", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
