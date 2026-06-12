from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "sampling_distribution.py"
SPEC = importlib.util.spec_from_file_location("sampling_distribution", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SIMULATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIMULATION)


class SamplingDistributionTest(unittest.TestCase):
    def test_same_seed_reproduces_sample_means(self) -> None:
        parameters = {
            "population_mean": 10,
            "population_std": 2,
            "sample_size": 5,
            "repetitions": 100,
            "seed": 7,
        }
        first = SIMULATION.simulate_sample_means(**parameters)
        second = SIMULATION.simulate_sample_means(**parameters)
        np.testing.assert_array_equal(first, second)

    def test_different_seed_changes_stream(self) -> None:
        common = {
            "population_mean": 10,
            "population_std": 2,
            "sample_size": 5,
            "repetitions": 100,
        }
        first = SIMULATION.simulate_sample_means(**common, seed=7)
        second = SIMULATION.simulate_sample_means(**common, seed=8)
        self.assertFalse(np.array_equal(first, second))

    def test_empirical_moments_match_theory(self) -> None:
        report = SIMULATION.simulation_report(
            population_mean=100,
            population_std=15,
            sample_size=25,
            repetitions=20_000,
            seed=42,
        )
        self.assertAlmostEqual(report["empirical_mean"], 100, delta=0.1)
        self.assertAlmostEqual(
            report["empirical_standard_error"],
            report["theoretical_standard_error"],
            delta=0.05,
        )

    def test_larger_sample_has_smaller_standard_error(self) -> None:
        small = SIMULATION.simulation_report(
            population_mean=0,
            population_std=10,
            sample_size=4,
            repetitions=100,
            seed=1,
        )
        large = SIMULATION.simulation_report(
            population_mean=0,
            population_std=10,
            sample_size=100,
            repetitions=100,
            seed=1,
        )
        self.assertLess(
            large["theoretical_standard_error"],
            small["theoretical_standard_error"],
        )

    def test_invalid_parameters_are_rejected(self) -> None:
        with self.assertRaisesRegex(SIMULATION.SimulationError, "positive"):
            SIMULATION.simulate_sample_means(
                population_mean=0,
                population_std=1,
                sample_size=0,
                repetitions=100,
                seed=1,
            )

    def test_excessive_allocation_is_rejected(self) -> None:
        with self.assertRaisesRegex(SIMULATION.SimulationError, "limit"):
            SIMULATION.simulate_sample_means(
                population_mean=0,
                population_std=1,
                sample_size=100_000,
                repetitions=1_000,
                seed=1,
            )

    def test_cli_returns_reproducibility_metadata(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--sample-size",
                "25",
                "--repetitions",
                "1000",
                "--seed",
                "42",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["seed"], 42)
        self.assertEqual(report["generator"], "numpy.random.Generator")

    def test_cli_error_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--sample-size", "0"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
