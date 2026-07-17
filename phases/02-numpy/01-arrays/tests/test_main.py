from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "array_contract.py"
SPEC = importlib.util.spec_from_file_location("array_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


class ArrayContractTest(unittest.TestCase):
    def test_describes_numeric_values_with_semantic_axes(self) -> None:
        report = CONTRACT.describe_array(
            [[12, 15, 9], [10, 11, 14]],
            axes=("store", "day"),
        )

        self.assertEqual(report["ndim"], 2)
        self.assertEqual(report["shape"], (2, 3))
        self.assertEqual(report["size"], 6)
        self.assertEqual(report["axes"], {"store": 2, "day": 3})
        self.assertTrue(report["is_numeric"])

    def test_accepts_an_existing_ndarray(self) -> None:
        values = np.array([3, 5, 8])

        report = CONTRACT.describe_array(values, axes=("observation",))
        checked = CONTRACT.require_numeric_array(values, axes=("observation",))

        self.assertTrue(report["input_is_ndarray"])
        self.assertEqual(report["shape"], (3,))
        self.assertIs(checked, values)

    def test_distinguishes_python_scalar_from_zero_dimensional_array(self) -> None:
        report = CONTRACT.describe_array(7)

        self.assertEqual(report["source_type"], "int")
        self.assertEqual(report["ndim"], 0)
        self.assertEqual(report["shape"], ())
        self.assertEqual(report["size"], 1)
        self.assertEqual(report["axes"], {})

    def test_axis_names_must_match_ndim(self) -> None:
        with self.assertRaisesRegex(CONTRACT.ArrayContractError, "2 axis names"):
            CONTRACT.describe_array([[1, 2], [3, 4]], axes=("row",))

    def test_ragged_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(CONTRACT.ArrayContractError, "rectangular"):
            CONTRACT.describe_array([[1, 2], [3]])

    def test_string_coercion_is_visible_and_numeric_contract_rejects_it(self) -> None:
        report = CONTRACT.describe_array([1, "2", 3], axes=("observation",))

        self.assertFalse(report["is_numeric"])
        self.assertEqual(np.dtype(report["dtype"]).kind, "U")
        with self.assertRaisesRegex(CONTRACT.ArrayContractError, "expected numeric"):
            CONTRACT.require_numeric_array([1, "2", 3])

    def test_integer_and_float_values_receive_one_floating_dtype(self) -> None:
        array = CONTRACT.require_numeric_array([1, 2.5])

        self.assertTrue(np.issubdtype(array.dtype, np.floating))
        np.testing.assert_array_equal(array, np.array([1.0, 2.5]))

    def test_list_and_ndarray_multiplication_have_different_meaning(self) -> None:
        python_values = [1, 2, 3]
        array = CONTRACT.require_numeric_array(python_values)

        self.assertEqual(python_values * 2, [1, 2, 3, 1, 2, 3])
        np.testing.assert_array_equal(array * 2, np.array([2, 4, 6]))

    def test_artifact_runs_as_a_standalone_passport(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("shape: (2, 3)", result.stdout)
        self.assertIn("- store: 2", result.stdout)
        self.assertIn("- day: 3", result.stdout)


if __name__ == "__main__":
    unittest.main()
