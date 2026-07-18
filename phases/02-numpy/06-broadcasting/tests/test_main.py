from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "broadcast_contract.py"
SPEC = importlib.util.spec_from_file_location("broadcast_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BROADCAST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROADCAST)


def operand(
    name: str,
    shape: list[int],
    axis_names: list[str],
    dtype: str = "float64",
) -> dict[str, object]:
    return {
        "name": name,
        "shape": shape,
        "axis_names": axis_names,
        "dtype": dtype,
    }


class BroadcastContractTest(unittest.TestCase):
    def test_manual_predictor_matches_numpy_for_core_cases(self) -> None:
        cases = [
            ((3, 4), (3, 4)),
            ((3, 4), ()),
            ((3, 4), (4,)),
            ((5, 1), (1, 6)),
            ((8, 1, 6, 1), (7, 1, 5)),
        ]
        for left, right in cases:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    BROADCAST.broadcast_shape(left, right),
                    np.broadcast_shapes(left, right),
                )

    def test_predictor_supports_more_than_two_shapes(self) -> None:
        shapes = ((2, 3, 4), (3, 1), (4,))
        self.assertEqual(
            BROADCAST.broadcast_shape(*shapes),
            np.broadcast_shapes(*shapes),
        )

    def test_zero_length_axis_follows_numpy_instead_of_max_rule(self) -> None:
        self.assertEqual(BROADCAST.broadcast_shape((0,), (1,)), (0,))
        self.assertEqual(
            BROADCAST.broadcast_shape((2, 0, 3), (1, 3)),
            np.broadcast_shapes((2, 0, 3), (1, 3)),
        )

    def test_incompatible_shapes_are_rejected(self) -> None:
        with self.assertRaisesRegex(BROADCAST.BroadcastingError, "incompatible"):
            BROADCAST.broadcast_shape((4, 3), (4,))

    def test_one_dimensional_transpose_does_not_create_column(self) -> None:
        vector = np.array([1, 2, 3])
        self.assertEqual(vector.T.shape, (3,))
        self.assertEqual(vector[np.newaxis, :].shape, (1, 3))
        self.assertEqual(vector[:, np.newaxis].shape, (3, 1))

    def test_named_alignment_explains_implicit_and_singleton_axes(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("values", [2, 3, 2], ["store", "day", "metric"]),
                operand("center", [2], ["metric"]),
            ]
        )
        self.assertEqual(report["result"]["shape"], [2, 3, 2])
        self.assertEqual(report["result"]["axis_names"], ["store", "day", "metric"])
        self.assertTrue(report["alignment"][0]["operands"][1]["implicit_leading_axis"])
        self.assertTrue(report["alignment"][1]["operands"][1]["expands"])
        self.assertEqual(report["operands"][1]["logical_expansion_factor"], 6)

    def test_keepdims_names_match_the_original_semantic_axes(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("values", [2, 3, 2], ["store", "day", "metric"]),
                operand(
                    "center",
                    [1, 1, 2],
                    ["summarized_store", "summarized_day", "metric"],
                ),
            ]
        )
        self.assertFalse(
            any(warning["code"] == "axis_name_conflict" for warning in report["warnings"])
        )

    def test_equal_lengths_with_different_meanings_produce_warning(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("values", [2, 3, 2], ["store", "day", "metric"]),
                operand("wrong_parameter", [2], ["store"]),
            ]
        )
        conflicts = [
            warning for warning in report["warnings"] if warning["code"] == "axis_name_conflict"
        ]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["output_axis"], 2)

    def test_integer_and_float_addition_resolves_float_dtype(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("integers", [3], ["row"], "int32"),
                operand("floats", [], [], "float32"),
            ],
            operation="add",
        )
        self.assertEqual(report["result"]["common_input_dtype"], "float64")
        self.assertEqual(report["result"]["operation_dtype"], "float64")

    def test_true_divide_of_integers_returns_float(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("left", [3], ["row"], "int32"),
                operand("right", [], [], "int32"),
            ],
            operation="true_divide",
        )
        self.assertEqual(report["result"]["common_input_dtype"], "int32")
        self.assertEqual(report["result"]["operation_dtype"], "float64")

    def test_comparison_result_is_boolean(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("values", [2, 3], ["row", "feature"], "float32"),
                operand("threshold", [3], ["feature"], "float32"),
            ],
            operation="less",
        )
        self.assertEqual(report["operation"]["category"], "comparison")
        self.assertEqual(report["result"]["operation_dtype"], "bool")

    def test_datetime_subtraction_returns_timedelta(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("event_date", [3], ["event"], "datetime64[D]"),
                operand("start_date", [], [], "datetime64[D]"),
            ],
            operation="subtract",
        )
        self.assertEqual(report["result"]["operation_dtype"], "timedelta64[D]")

    def test_undefined_operation_is_reported_without_execution(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("labels", [3], ["row"], "<U5"),
                operand("offset", [], [], "int64"),
            ],
            operation="subtract",
        )
        self.assertFalse(report["operation"]["defined_for_dtypes"])
        self.assertIsNone(report["result"]["operation_dtype"])
        self.assertTrue(
            any(warning["code"] == "operation_not_defined" for warning in report["warnings"])
        )

    def test_boolean_arithmetic_is_visible_as_semantic_warning(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("left_mask", [3], ["row"], "bool"),
                operand("right_mask", [3], ["row"], "bool"),
            ],
            operation="add",
        )
        self.assertEqual(report["result"]["operation_dtype"], "bool")
        self.assertTrue(
            any(warning["code"] == "boolean_arithmetic" for warning in report["warnings"])
        )

    def test_in_place_contract_checks_shape_and_dtype_separately(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("integers", [2, 3], ["row", "feature"], "int32"),
                operand("fraction", [], [], "float32"),
            ],
            operation="add",
        )
        self.assertTrue(report["in_place_on_left"]["shape_can_store_result"])
        self.assertFalse(report["in_place_on_left"]["dtype_can_store_result_with_same_kind"])
        self.assertFalse(report["in_place_on_left"]["allowed_by_shape_and_dtype"])

    def test_large_logical_result_is_estimated_without_allocation(self) -> None:
        report = BROADCAST.analyze_broadcast(
            [
                operand("left", [50_000, 1, 100], ["left", "pair", "feature"]),
                operand("right", [1, 50_000, 100], ["pair", "right", "feature"]),
            ],
            operation="subtract",
            memory_limit_mb=128,
        )
        self.assertEqual(report["result"]["shape"], [50_000, 50_000, 100])
        self.assertEqual(report["result"]["estimated_nbytes"], 2_000_000_000_000)
        self.assertTrue(
            any(warning["code"] == "output_exceeds_memory_limit" for warning in report["warnings"])
        )

    def test_invalid_axis_contract_is_rejected(self) -> None:
        with self.assertRaisesRegex(BROADCAST.BroadcastingError, "axis names"):
            BROADCAST.analyze_broadcast(
                [
                    operand("left", [2, 3], ["row", "row"]),
                    operand("right", [3], ["feature"]),
                ]
            )

    def test_cli_returns_explainable_contract(self) -> None:
        payload = json.dumps(
            [
                operand("values", [2, 3, 2], ["store", "day", "metric"]),
                operand("center", [2], ["metric"]),
            ]
        )
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--operands",
                payload,
                "--operation",
                "subtract",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["result"]["shape"], [2, 3, 2])
        self.assertEqual(report["result"]["operation_dtype"], "float64")

    def test_cli_failure_has_no_traceback(self) -> None:
        payload = json.dumps(
            [
                operand("left", [4, 3], ["row", "feature"]),
                operand("right", [4], ["feature"]),
            ]
        )
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--operands", payload],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
