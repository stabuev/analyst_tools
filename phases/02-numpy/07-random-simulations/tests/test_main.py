from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "reproducible_event_simulator.py"
SPEC = importlib.util.spec_from_file_location("reproducible_event_simulator", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SIMULATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SIMULATION)


def report(**overrides: object) -> dict[str, object]:
    parameters: dict[str, object] = {
        "probabilities": [0.1, 0.4],
        "group_names": ["web", "partner"],
        "scenario_count": 20,
        "observations_per_group": 10,
        "seed": 42,
    }
    parameters.update(overrides)
    return SIMULATION.simulation_report(**parameters)


class ReproducibleEventSimulatorTest(unittest.TestCase):
    def test_same_contract_reproduces_every_draw(self) -> None:
        first = report()
        second = report()
        self.assertEqual(
            first["arrays"]["draws"]["sha256"],
            second["arrays"]["draws"]["sha256"],
        )
        self.assertEqual(first["summary"], second["summary"])

    def test_different_seed_changes_draw_stream(self) -> None:
        first = report(seed=42)
        second = report(seed=43)
        self.assertNotEqual(
            first["arrays"]["draws"]["sha256"],
            second["arrays"]["draws"]["sha256"],
        )

    def test_one_generator_advances_between_calls(self) -> None:
        rng = np.random.default_rng(7)
        first, _ = SIMULATION.simulate_binary_events(
            probabilities=[0.5],
            scenario_count=2,
            observations_per_group=3,
            rng=rng,
        )
        second, _ = SIMULATION.simulate_binary_events(
            probabilities=[0.5],
            scenario_count=2,
            observations_per_group=3,
            rng=rng,
        )
        self.assertFalse(np.array_equal(first, second))

    def test_fresh_generators_with_same_seed_start_the_same_stream(self) -> None:
        first, _ = SIMULATION.simulate_binary_events(
            probabilities=[0.5],
            scenario_count=2,
            observations_per_group=3,
            rng=np.random.default_rng(7),
        )
        second, _ = SIMULATION.simulate_binary_events(
            probabilities=[0.5],
            scenario_count=2,
            observations_per_group=3,
            rng=np.random.default_rng(7),
        )
        np.testing.assert_array_equal(first, second)

    def test_size_contract_creates_named_axes_and_expected_dtypes(self) -> None:
        result = report(scenario_count=4, observations_per_group=5)
        self.assertEqual(result["arrays"]["draws"]["shape"], [4, 5, 2])
        self.assertEqual(
            result["arrays"]["draws"]["axis_names"],
            ["scenario", "observation", "group"],
        )
        self.assertEqual(result["arrays"]["draws"]["dtype"], "float64")
        self.assertEqual(result["arrays"]["events"]["dtype"], "bool")

    def test_draws_stay_in_half_open_unit_interval(self) -> None:
        result = report()
        self.assertGreaterEqual(result["arrays"]["draws"]["minimum"], 0.0)
        self.assertLess(result["arrays"]["draws"]["maximum"], 1.0)

    def test_broadcast_probability_is_applied_on_group_axis(self) -> None:
        result = report(
            probabilities=[0.0, 1.0],
            group_names=["never", "always"],
        )
        self.assertEqual(result["summary"]["event_count_by_group"]["never"], 0)
        expected = 20 * 10
        self.assertEqual(
            result["summary"]["event_count_by_group"]["always"],
            expected,
        )

    def test_manifest_records_generator_seed_and_call_contract(self) -> None:
        result = report()
        self.assertEqual(result["manifest"]["generator"], "Generator")
        self.assertEqual(result["manifest"]["bit_generator"], "PCG64")
        self.assertEqual(result["manifest"]["seed"], 42)
        self.assertEqual(
            result["manifest"]["call_contract"]["size"],
            [20, 10, 2],
        )

    def test_memory_contract_counts_float_and_boolean_arrays(self) -> None:
        result = report(scenario_count=2, observations_per_group=3)
        self.assertEqual(result["memory"]["element_count"], 12)
        self.assertEqual(result["memory"]["draws_nbytes"], 96)
        self.assertEqual(result["memory"]["events_nbytes"], 12)
        self.assertEqual(result["memory"]["estimated_working_nbytes"], 108)

    def test_memory_limit_rejects_before_large_allocation(self) -> None:
        with self.assertRaisesRegex(SIMULATION.SimulationError, "above limit"):
            report(
                scenario_count=1_000_000,
                observations_per_group=1_000_000,
                memory_limit_mb=1,
            )

    def test_invalid_probabilities_are_rejected(self) -> None:
        invalid_values = ([], [-0.1], [1.1], [float("nan")], [True], ["0.5"])
        for probabilities in invalid_values:
            with (
                self.subTest(probabilities=probabilities),
                self.assertRaises(SIMULATION.SimulationError),
            ):
                report(probabilities=probabilities, group_names=["group"])

    def test_invalid_counts_and_seed_are_rejected(self) -> None:
        invalid_parameters = (
            {"scenario_count": 0},
            {"observations_per_group": -1},
            {"seed": -1},
            {"seed": True},
        )
        for parameters in invalid_parameters:
            with (
                self.subTest(parameters=parameters),
                self.assertRaises(SIMULATION.SimulationError),
            ):
                report(**parameters)

    def test_group_names_must_match_probability_axis(self) -> None:
        with self.assertRaisesRegex(SIMULATION.SimulationError, "expected 2"):
            report(group_names=["only_one"])
        with self.assertRaisesRegex(SIMULATION.SimulationError, "unique"):
            report(group_names=["same", "same"])

    def test_rng_dependency_must_be_generator(self) -> None:
        with self.assertRaisesRegex(SIMULATION.SimulationError, "Generator"):
            SIMULATION.simulate_binary_events(
                probabilities=[0.5],
                scenario_count=2,
                observations_per_group=3,
                rng=object(),
            )

    def test_cli_returns_a_reproducibility_manifest(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--probabilities",
                "[0, 1]",
                "--group-names",
                '["never", "always"]',
                "--scenarios",
                "3",
                "--observations-per-group",
                "4",
                "--seed",
                "7",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["manifest"]["seed"], 7)
        self.assertEqual(payload["arrays"]["events"]["shape"], [3, 4, 2])

    def test_cli_can_write_the_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            result = subprocess.run(
                [sys.executable, ARTIFACT, "--output", output],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["manifest"]["seed"], 42)

    def test_cli_failure_has_no_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--probabilities", "[1.5]"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
