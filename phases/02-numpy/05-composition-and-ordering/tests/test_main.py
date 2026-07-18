from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "array_structure_auditor.py"
SPEC = importlib.util.spec_from_file_location("array_structure_auditor", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


class ArrayStructureAuditorTest(unittest.TestCase):
    def test_manual_permutation_is_stable_for_equal_keys(self) -> None:
        self.assertEqual(
            AUDITOR.manual_stable_permutation([120, 80, 120, 95]),
            [1, 3, 0, 2],
        )
        self.assertEqual(
            AUDITOR.manual_stable_permutation([120, 80, 120, 95], direction="descending"),
            [0, 2, 3, 1],
        )

    def test_concatenate_uses_an_existing_axis(self) -> None:
        report = AUDITOR.combine_report(
            [np.array([[1, 10], [2, 20]]), np.array([[3, 30]])],
            mode="concatenate",
            axis=0,
            axis_names=("order", "metric"),
        )
        self.assertEqual(report["axis_role"], "existing")
        self.assertEqual(report["output"]["shape"], [3, 2])
        self.assertEqual(report["output"]["axis_names"], ["order", "metric"])
        self.assertEqual(report["output"]["value"][-1], [3, 30])

    def test_concatenate_can_extend_a_nonzero_axis(self) -> None:
        report = AUDITOR.combine_report(
            [np.ones((2, 1)), np.zeros((2, 2))],
            mode="concatenate",
            axis=1,
            axis_names=("order", "metric"),
        )
        self.assertEqual(report["output"]["shape"], [2, 3])

    def test_stack_inserts_a_named_axis(self) -> None:
        report = AUDITOR.combine_report(
            [np.array([10, 20]), np.array([12, 18])],
            mode="stack",
            axis=0,
            axis_names=("day",),
            new_axis_name="scenario",
        )
        self.assertEqual(report["axis_role"], "new")
        self.assertEqual(report["output"]["shape"], [2, 2])
        self.assertEqual(report["output"]["axis_names"], ["scenario", "day"])

    def test_concatenate_rejects_mismatch_on_untouched_axis(self) -> None:
        with self.assertRaisesRegex(AUDITOR.StructureError, "non-concatenated"):
            AUDITOR.combine_report(
                [np.ones((2, 2)), np.ones((1, 3))],
                mode="concatenate",
                axis=0,
                axis_names=("order", "metric"),
            )

    def test_stack_requires_exactly_equal_shapes(self) -> None:
        with self.assertRaisesRegex(AUDITOR.StructureError, "exactly equal"):
            AUDITOR.combine_report(
                [np.ones((2, 2)), np.ones((1, 2))],
                mode="stack",
                axis=0,
                axis_names=("order", "metric"),
                new_axis_name="scenario",
            )

    def test_stack_requires_a_new_unique_axis_name(self) -> None:
        with self.assertRaisesRegex(AUDITOR.StructureError, "new_axis_name"):
            AUDITOR.combine_report(
                [np.ones(2), np.ones(2)],
                mode="stack",
                axis=0,
                axis_names=("order",),
            )
        with self.assertRaisesRegex(AUDITOR.StructureError, "duplicate"):
            AUDITOR.combine_report(
                [np.ones(2), np.ones(2)],
                mode="stack",
                axis=0,
                axis_names=("order",),
                new_axis_name="order",
            )

    def test_dtype_promotion_must_be_explicit(self) -> None:
        with self.assertRaisesRegex(AUDITOR.StructureError, "dtypes differ"):
            AUDITOR.combine_report(
                [np.array([1], dtype=np.int32), np.array([2.5])],
                mode="concatenate",
                axis=0,
                axis_names=("order",),
            )
        report = AUDITOR.combine_report(
            [np.array([1], dtype=np.int32), np.array([2.5])],
            mode="concatenate",
            axis=0,
            axis_names=("order",),
            allow_dtype_promotion=True,
        )
        self.assertEqual(report["output"]["dtype"], "float64")

    def test_combination_reports_independent_output_memory(self) -> None:
        report = AUDITOR.combine_report(
            [np.arange(2), np.arange(2, 4)],
            mode="concatenate",
            axis=0,
            axis_names=("order",),
        )
        self.assertEqual(report["output"]["shares_memory_with_input"], [False, False])

    def test_one_permutation_keeps_payloads_aligned(self) -> None:
        report = AUDITOR.aligned_order_report(
            [120, 80, 120, 95],
            {"order_id": [101, 102, 103, 104], "segment": ["A", "B", "C", "A"]},
        )
        self.assertEqual(report["permutation"], [1, 3, 0, 2])
        self.assertEqual(report["sorted_keys"], [80, 95, 120, 120])
        self.assertEqual(report["sorted_payloads"]["order_id"], [102, 104, 101, 103])
        self.assertEqual(report["sorted_payloads"]["segment"], ["B", "A", "A", "C"])
        self.assertTrue(report["restoration_check"])

    def test_descending_order_keeps_ties_stable(self) -> None:
        report = AUDITOR.aligned_order_report(
            [120, 80, 120, 95],
            {"order_id": [101, 102, 103, 104]},
            direction="descending",
        )
        self.assertEqual(report["permutation"], [0, 2, 3, 1])
        self.assertEqual(report["sorted_payloads"]["order_id"][:2], [101, 103])

    def test_order_rejects_misaligned_payload(self) -> None:
        with self.assertRaisesRegex(AUDITOR.StructureError, "same length"):
            AUDITOR.aligned_order_report([2, 1], {"order_id": [101]})

    def test_nan_policy_is_explicit_and_places_nan_last(self) -> None:
        with self.assertRaisesRegex(AUDITOR.StructureError, "NaN keys"):
            AUDITOR.aligned_order_report([2.0, np.nan, 1.0], {"id": [1, 2, 3]})
        report = AUDITOR.aligned_order_report(
            [2.0, np.nan, 1.0],
            {"id": [1, 2, 3]},
            nan_policy="last",
        )
        self.assertEqual(report["permutation"], [2, 0, 1])
        self.assertTrue(report["restoration_check"])

    def test_argmin_and_argmax_report_first_tied_position(self) -> None:
        report = AUDITOR.aligned_order_report(
            [5, 2, 5, 2],
            {"id": [10, 11, 12, 13]},
        )
        self.assertEqual(report["argmin_first"], 1)
        self.assertEqual(report["argmax_first"], 0)

    def test_unique_reports_counts_inverse_and_first_seen_order(self) -> None:
        report = AUDITOR.unique_report(["B", "A", "B", "C", "A"])
        self.assertEqual(report["sorted_unique_values"], ["A", "B", "C"])
        self.assertEqual(report["counts"], [2, 2, 1])
        self.assertEqual(report["values_in_first_seen_order"], ["B", "A", "C"])
        self.assertEqual(report["duplicate_count"], 2)
        self.assertTrue(report["reconstruction_check"])

    def test_unique_rejects_implicit_flattening(self) -> None:
        with self.assertRaisesRegex(AUDITOR.StructureError, "one-dimensional"):
            AUDITOR.unique_report([[1, 2], [1, 3]])

    def test_cli_order_returns_json_report(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "order",
                "--keys",
                "[120, 80, 120]",
                "--payloads",
                '{"order_id": [101, 102, 103]}',
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["permutation"], [1, 0, 2])

    def test_cli_rejects_invalid_structure_without_traceback(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "combine",
                "--arrays",
                "[[[1, 2]], [[3]]]",
                "--mode",
                "stack",
                "--axis",
                "0",
                "--axis-names",
                "order",
                "metric",
                "--new-axis-name",
                "batch",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
