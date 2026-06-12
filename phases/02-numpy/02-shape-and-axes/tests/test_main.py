from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "shape_contract.py"
SPEC = importlib.util.spec_from_file_location("shape_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SHAPES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHAPES)


class ShapeContractTest(unittest.TestCase):
    def test_negative_axes_are_normalized(self) -> None:
        self.assertEqual(SHAPES.normalize_axes(-1, 3), (2,))
        self.assertEqual(SHAPES.normalize_axes((0, -1), 3), (0, 2))

    def test_reduction_shape_matches_numpy(self) -> None:
        array = np.empty((2, 3, 4))
        for axis in (None, 0, 1, -1, (0, 2)):
            for keepdims in (False, True):
                expected = np.sum(array, axis=axis, keepdims=keepdims).shape
                self.assertEqual(
                    SHAPES.reduction_shape(array.shape, axis, keepdims=keepdims),
                    expected,
                )

    def test_reshape_infers_one_dimension(self) -> None:
        self.assertEqual(SHAPES.reshape_shape((2, 3, 4), (6, -1)), (6, 4))

    def test_reshape_rejects_changed_element_count(self) -> None:
        with self.assertRaisesRegex(SHAPES.ShapeContractError, "element count"):
            SHAPES.reshape_shape((2, 3), (4, 2))

    def test_transpose_and_expand_shapes_match_numpy(self) -> None:
        array = np.empty((2, 3, 4))
        self.assertEqual(
            SHAPES.transpose_shape(array.shape, (2, 0, 1)),
            np.transpose(array, (2, 0, 1)).shape,
        )
        self.assertEqual(
            SHAPES.expand_dims_shape(array.shape, -1),
            np.expand_dims(array, -1).shape,
        )

    def test_assert_shape_reports_contract_name(self) -> None:
        with self.assertRaisesRegex(SHAPES.ShapeContractError, "features"):
            SHAPES.assert_shape(np.zeros((2, 3)), (3, 2), name="features")

    def test_cli_returns_structured_report(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--shape",
                "[2, 3, 4]",
                "--axis",
                "1",
                "--keepdims",
                "--reshape",
                "[6, 4]",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["operations"]["reduction"]["result_shape"], [2, 1, 4])
        self.assertEqual(report["operations"]["reshape"]["result_shape"], [6, 4])

    def test_cli_rejects_invalid_axis_without_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--shape", "[2, 3]", "--axis", "2"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("out of bounds", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
