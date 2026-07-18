from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "axis_aggregates.py"
SPEC = importlib.util.spec_from_file_location("axis_aggregates", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AGGREGATES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGGREGATES)


class AxisAggregatesTest(unittest.TestCase):
    def test_manual_sum_exposes_groups_on_both_matrix_axes(self) -> None:
        values = [[10, 12, 8], [7, 9, 11]]
        self.assertEqual(AGGREGATES.manual_sum_2d(values, axis=0), [17, 21, 19])
        self.assertEqual(AGGREGATES.manual_sum_2d(values, axis=1), [30, 27])

    def test_manual_sum_rejects_ragged_matrix(self) -> None:
        with self.assertRaisesRegex(AGGREGATES.AggregationError, "rectangular"):
            AGGREGATES.manual_sum_2d([[1, 2], [3]], axis=0)

    def test_contract_names_reduced_and_remaining_axes(self) -> None:
        contract = AGGREGATES.aggregation_contract(
            (2, 3, 2),
            axis=1,
            axis_names=("store", "day", "metric"),
        )
        self.assertEqual(contract["reduced_axes"], [1])
        self.assertEqual(contract["reduced_axis_names"], ["day"])
        self.assertEqual(contract["output_shape"], [2, 2])
        self.assertEqual(contract["output_axis_names"], ["store", "metric"])

    def test_single_axis_aggregation_preserves_subject_grain(self) -> None:
        report = AGGREGATES.aggregate(
            [
                [[10, 1000], [12, 1440], [8, 880]],
                [[7, 840], [9, 990], [11, 1320]],
            ],
            axis=1,
            axis_names=("store", "day", "metric"),
        )
        self.assertEqual(report["reduction"]["axis_names"], ["day"])
        self.assertEqual(report["reduction"]["output_axis_names"], ["store", "metric"])
        self.assertEqual(report["aggregates"]["sum"]["value"], [[30, 3320], [27, 3150]])
        self.assertEqual(report["aggregates"]["sum"]["shape"], [2, 2])
        self.assertEqual(report["aggregates"]["group_size"]["value"], [[3, 3], [3, 3]])

    def test_multiple_axes_leave_only_metric_grain(self) -> None:
        report = AGGREGATES.aggregate(
            [
                [[10, 1000], [12, 1440], [8, 880]],
                [[7, 840], [9, 990], [11, 1320]],
            ],
            axis=(0, 1),
            axis_names=("store", "day", "metric"),
        )
        self.assertEqual(report["reduction"]["axes"], [0, 1])
        self.assertEqual(report["reduction"]["output_axis_names"], ["metric"])
        self.assertEqual(report["reduction"]["output_shape"], [2])
        np.testing.assert_allclose(
            report["aggregates"]["mean"]["value"],
            [9.5, 1078.3333333333333],
        )

    def test_axis_none_reduces_all_axes_to_scalar(self) -> None:
        report = AGGREGATES.aggregate(
            [[1, 2], [3, 4]],
            axis=None,
            axis_names=("store", "day"),
        )
        self.assertEqual(report["reduction"]["axes"], [0, 1])
        self.assertEqual(report["reduction"]["output_axis_names"], [])
        self.assertEqual(report["aggregates"]["sum"]["shape"], [])
        self.assertEqual(report["aggregates"]["sum"]["value"], 10)

    def test_keepdims_preserves_summarized_axis_positions(self) -> None:
        report = AGGREGATES.aggregate(
            np.ones((2, 3, 2)),
            axis=(0, 1),
            axis_names=("store", "day", "metric"),
            keepdims=True,
        )
        self.assertEqual(report["reduction"]["output_shape"], [1, 1, 2])
        self.assertEqual(
            report["reduction"]["output_axis_names"],
            ["summarized_store", "summarized_day", "metric"],
        )
        self.assertEqual(report["aggregates"]["mean"]["shape"], [1, 1, 2])

    def test_negative_axis_is_normalized(self) -> None:
        report = AGGREGATES.aggregate(
            [[1, 2], [3, 4]],
            axis=-1,
            axis_names=("store", "day"),
        )
        self.assertEqual(report["reduction"]["axes"], [1])
        self.assertEqual(report["reduction"]["axis_names"], ["day"])

    def test_repeated_axis_and_wrong_axis_names_are_rejected(self) -> None:
        with self.assertRaisesRegex(AGGREGATES.AggregationError, "repeated"):
            AGGREGATES.aggregate([[1, 2]], axis=(1, -1))
        with self.assertRaisesRegex(AGGREGATES.AggregationError, "axis names"):
            AGGREGATES.aggregate([[1, 2]], axis=1, axis_names=("only_one",))

    def test_error_policy_rejects_missing_values(self) -> None:
        with self.assertRaisesRegex(AGGREGATES.AggregationError, "missing values"):
            AGGREGATES.aggregate(
                [[10, None, 8], [7, 9, 11]],
                axis=1,
                axis_names=("store", "day"),
            )

    def test_omit_policy_reports_group_valid_and_missing_counts(self) -> None:
        report = AGGREGATES.aggregate(
            [[10, None, 8], [7, 9, 11]],
            axis=1,
            axis_names=("store", "day"),
            missing_policy="omit",
        )
        self.assertEqual(report["aggregates"]["group_size"]["value"], [3, 3])
        self.assertEqual(report["aggregates"]["valid_count"]["value"], [2, 3])
        self.assertEqual(report["aggregates"]["missing_count"]["value"], [1, 0])
        np.testing.assert_allclose(report["aggregates"]["mean"]["value"], [9, 9])

    def test_all_missing_group_is_rejected_instead_of_becoming_zero(self) -> None:
        with self.assertRaisesRegex(AGGREGATES.AggregationError, "no valid observations"):
            AGGREGATES.aggregate(
                [[None, None], [7, 9]],
                axis=1,
                missing_policy="omit",
            )

    def test_ddof_is_validated_against_each_groups_valid_count(self) -> None:
        with self.assertRaisesRegex(AGGREGATES.AggregationError, "ddof"):
            AGGREGATES.aggregate(
                [[10, None], [7, 9]],
                axis=1,
                missing_policy="omit",
                ddof=1,
            )

    def test_input_and_result_dtypes_are_observable(self) -> None:
        report = AGGREGATES.aggregate(
            np.array([[1, 2], [3, 4]], dtype=np.int32),
            axis=1,
            axis_names=("store", "day"),
        )
        self.assertEqual(report["input"]["dtype"], "int32")
        self.assertEqual(report["aggregates"]["mean"]["dtype"], "float64")
        self.assertEqual(report["aggregates"]["valid_count"]["dtype"], "int64")

    def test_cli_supports_named_multiple_axes(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--values",
                "[[[1, 10], [2, 20]], [[3, 30], [4, 40]]]",
                "--axis-names",
                "store",
                "day",
                "metric",
                "--axis",
                "0",
                "1",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["reduction"]["axis_names"], ["store", "day"])
        self.assertEqual(report["aggregates"]["sum"]["value"], [10, 100])

    def test_cli_rejects_invalid_axis_without_traceback(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--values", "[[1, 2]]", "--axis", "2"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
