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
MAIN = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("shape_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SHAPES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHAPES)


class ShapeContractTest(unittest.TestCase):
    def test_negative_axes_are_normalized(self) -> None:
        self.assertEqual(SHAPES.normalize_axes(-1, 3), (2,))
        self.assertEqual(SHAPES.normalize_axes((0, -1), 3), (0, 2))

    def test_invalid_axes_are_rejected(self) -> None:
        for axis in (True, 3, -4, (0, -3)):
            with self.subTest(axis=axis), self.assertRaises(SHAPES.ShapeContractError):
                SHAPES.normalize_axes(axis, 3)

    def test_axis_names_must_match_and_be_unique(self) -> None:
        self.assertEqual(
            SHAPES.validate_axis_names(("store", "day", "metric"), 3),
            ("store", "day", "metric"),
        )
        for names in (("store", "day"), ("store", "day", "day"), ("store", "", "metric")):
            with self.subTest(names=names), self.assertRaises(SHAPES.ShapeContractError):
                SHAPES.validate_axis_names(names, 3)

    def test_reduction_shape_matches_numpy(self) -> None:
        array = np.empty((2, 3, 4))
        for axis in (None, 0, 1, -1, (0, 2)):
            for keepdims in (False, True):
                expected = np.sum(array, axis=axis, keepdims=keepdims).shape
                self.assertEqual(
                    SHAPES.reduction_shape(array.shape, axis, keepdims=keepdims),
                    expected,
                )

    def test_reduction_report_preserves_axis_meaning(self) -> None:
        report = SHAPES.build_report(
            (2, 3, 2),
            axis_names=("store", "day", "metric"),
            axis=1,
        )
        reduction = report["operations"]["reduction"]
        self.assertEqual(reduction["operated_axis_names"], ["day"])
        self.assertEqual(reduction["result_shape"], [2, 2])
        self.assertEqual(reduction["result_axis_names"], ["store", "metric"])

        kept = SHAPES.build_report(
            (2, 3, 2),
            axis_names=("store", "day", "metric"),
            axis=1,
            keepdims=True,
        )["operations"]["reduction"]
        self.assertEqual(kept["result_shape"], [2, 1, 2])
        self.assertEqual(kept["result_axis_names"], ["store", "day", "metric"])

    def test_reshape_infers_one_dimension_and_rejects_changed_size(self) -> None:
        self.assertEqual(SHAPES.reshape_shape((2, 3, 4), (6, -1)), (6, 4))
        with self.assertRaisesRegex(SHAPES.ShapeContractError, "element count"):
            SHAPES.reshape_shape((2, 3), (4, 2))

    def test_reshape_requires_a_new_semantic_contract(self) -> None:
        unnamed = SHAPES.build_report(
            (2, 3, 2),
            axis_names=("store", "day", "metric"),
            reshape=(6, 2),
        )["operations"]["reshape"]
        self.assertIsNone(unnamed["result_axis_names"])
        self.assertIn("axis meaning", unnamed["semantic_warning"])

        named = SHAPES.build_report(
            (2, 3, 2),
            axis_names=("store", "day", "metric"),
            reshape=(6, 2),
            reshape_axis_names=("store_day", "metric"),
        )["operations"]["reshape"]
        self.assertEqual(named["result_axis_names"], ["store_day", "metric"])

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

    def test_transpose_and_expand_reports_move_axis_names(self) -> None:
        report = SHAPES.build_report(
            (2, 3, 2),
            axis_names=("store", "day", "metric"),
            transpose=(2, 0, 1),
            expand_axis=-1,
            expand_axis_name="scenario",
        )
        self.assertEqual(
            report["operations"]["transpose"]["result_axis_names"],
            ["metric", "store", "day"],
        )
        self.assertEqual(
            report["operations"]["expand_dims"]["result_axis_names"],
            ["store", "day", "metric", "scenario"],
        )

    def test_assert_shape_reports_role_and_named_expectation(self) -> None:
        with self.assertRaisesRegex(
            SHAPES.ShapeContractError,
            r"store_totals.*store=2, metric=2",
        ):
            SHAPES.assert_shape(
                np.zeros((3, 2)),
                (2, 2),
                name="store_totals",
                axis_names=("store", "metric"),
            )

    def test_cli_returns_structured_semantic_report(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--shape",
                "[2, 3, 2]",
                "--axis-names",
                '["store", "day", "metric"]',
                "--axis",
                "1",
                "--reshape",
                "[6, 2]",
                "--reshape-axis-names",
                '["store_day", "metric"]',
                "--transpose",
                "[2, 0, 1]",
                "--expand-axis",
                "-1",
                "--expand-axis-name",
                "scenario",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["operations"]["reduction"]["result_shape"], [2, 2])
        self.assertEqual(
            report["operations"]["reshape"]["result_axis_names"],
            ["store_day", "metric"],
        )
        self.assertEqual(
            report["operations"]["transpose"]["result_shape"],
            [2, 2, 3],
        )

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

    def test_example_runs_as_a_standalone_program(self) -> None:
        result = subprocess.run(
            [sys.executable, MAIN],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["axis_names"], ["store", "day", "metric"])


if __name__ == "__main__":
    unittest.main()
