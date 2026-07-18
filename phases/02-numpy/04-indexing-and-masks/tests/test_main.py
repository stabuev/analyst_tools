from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "selection_contract.py"
EXAMPLE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("selection_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SELECTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTION)


class SelectionContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.orders = np.array(
            [
                [101, 1, 1200, 2],
                [102, 3, 4500, 7],
                [103, 2, np.nan, 4],
                [104, 2, 3200, 3],
                [105, 5, 8000, 1],
            ],
            dtype=np.float64,
        )

    def test_range_mask_respects_boundaries_and_rejects_non_finite(self) -> None:
        values = np.array([5.0, 10.0, 15.0, 20.0, np.nan, np.inf, -np.inf])
        np.testing.assert_array_equal(
            SELECTION.build_range_mask(values, lower=10, upper=20),
            [False, True, True, True, False, False, False],
        )
        np.testing.assert_array_equal(
            SELECTION.build_range_mask(
                values,
                lower=10,
                upper=20,
                inclusive="neither",
            ),
            [False, False, True, False, False, False, False],
        )

    def test_range_mask_supports_one_sided_bounds(self) -> None:
        values = np.array([1, 2, 3, 4])
        np.testing.assert_array_equal(
            SELECTION.build_range_mask(values, lower=3),
            [False, False, True, True],
        )
        np.testing.assert_array_equal(
            SELECTION.build_range_mask(values, upper=2, inclusive="neither"),
            [True, False, False, False],
        )

    def test_range_mask_rejects_invalid_contract(self) -> None:
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "cannot exceed"):
            SELECTION.build_range_mask([1, 2, 3], lower=5, upper=2)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "must be finite"):
            SELECTION.build_range_mask([1, 2, 3], lower=np.nan)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "1-dimensional"):
            SELECTION.build_range_mask([[1, 2], [3, 4]], lower=1)

    def test_select_rows_preserves_order_shape_and_requested_columns(self) -> None:
        mask = np.array([True, False, False, True, False])
        selected = SELECTION.select_rows(
            self.orders,
            mask,
            columns=[0, 2, 3],
        )
        self.assertEqual(selected.shape, (2, 3))
        np.testing.assert_array_equal(
            selected,
            [[101, 1200, 2], [104, 3200, 3]],
        )

    def test_select_rows_accepts_negative_column_indices(self) -> None:
        selected = SELECTION.select_rows(
            self.orders,
            [True, False, False, False, True],
            columns=[0, -1],
        )
        np.testing.assert_array_equal(selected, [[101, 2], [105, 1]])

    def test_selected_result_is_independent_from_source(self) -> None:
        source = self.orders.copy()
        selected = SELECTION.select_rows(
            source,
            [True, False, False, True, False],
        )
        self.assertFalse(np.shares_memory(source, selected))
        selected[0, 0] = 999
        self.assertEqual(source[0, 0], 101)

    def test_select_rows_requires_one_boolean_decision_per_row(self) -> None:
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "bool dtype"):
            SELECTION.select_rows(self.orders, [1, 0, 0, 1, 0])
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "row mask shape"):
            SELECTION.select_rows(self.orders, [[True], [False], [False], [True], [False]])

    def test_select_rows_rejects_duplicate_or_out_of_range_columns(self) -> None:
        mask = [True, False, False, True, False]
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "duplicates"):
            SELECTION.select_rows(self.orders, mask, columns=[0, -4])
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "out of bounds"):
            SELECTION.select_rows(self.orders, mask, columns=[4])

    def test_replace_where_copies_by_default(self) -> None:
        source = np.array([[1, 2], [3, 4]], dtype=np.int16)
        mask = np.array([[False, True], [True, False]])
        result = SELECTION.replace_where(source, mask, 0.0)
        np.testing.assert_array_equal(source, [[1, 2], [3, 4]])
        np.testing.assert_array_equal(result, [[1, 0], [0, 4]])
        self.assertFalse(np.shares_memory(source, result))

    def test_replace_where_can_change_source_explicitly(self) -> None:
        source = np.array([1.0, 2.0, 3.0])
        result = SELECTION.replace_where(
            source,
            source > 1,
            np.nan,
            in_place=True,
        )
        self.assertIs(result, source)
        np.testing.assert_array_equal(source, [1.0, np.nan, np.nan])

    def test_replace_where_checks_mask_and_replacement_contracts(self) -> None:
        source = np.array([1, 2, 3], dtype=np.int16)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "bool dtype"):
            SELECTION.replace_where(source, [0, 1, 0], 0)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "mask shape"):
            SELECTION.replace_where(source, [True], 0)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "cannot be stored"):
            SELECTION.replace_where(source, [False, True, False], 1.5)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "requires a NumPy"):
            SELECTION.replace_where([1, 2, 3], [False, True, False], 0, in_place=True)

    def test_memory_report_exposes_shape_and_buffer_differences(self) -> None:
        report = SELECTION.memory_report(self.orders)
        self.assertEqual(report["source_shape"], [5, 4])
        self.assertEqual(report["basic_slice_shape"], [2, 4])
        self.assertTrue(report["basic_slice_shares_memory"])
        self.assertEqual(report["advanced_selection_shape"], [2, 4])
        self.assertFalse(report["advanced_selection_shares_memory"])
        self.assertEqual(report["column_vector_shape"], [5])
        self.assertEqual(report["column_matrix_shape"], [5, 1])

    def test_selection_report_connects_mask_shape_and_memory_contracts(self) -> None:
        report = SELECTION.build_selection_report(
            self.orders,
            filter_column=2,
            lower=1000,
            upper=5000,
            columns=[0, 2, 3],
        )
        self.assertEqual(report["axis_contract"], ["observation", "feature"])
        self.assertEqual(report["mask_shape"], [5])
        self.assertEqual(report["selected_count"], 3)
        self.assertEqual(report["excluded_non_finite"], 1)
        self.assertEqual(report["selected_shape"], [3, 3])
        self.assertFalse(report["shares_memory"])
        self.assertEqual(report["selected"][0], [101, 1200, 2])

    def test_json_null_is_treated_as_missing_numeric_value(self) -> None:
        matrix = [[1, 10], [2, None], [3, 30]]
        report = SELECTION.build_selection_report(
            matrix,
            filter_column=1,
            lower=0,
            upper=100,
        )
        self.assertEqual(report["source_dtype"], "float64")
        self.assertEqual(report["mask"], [True, False, True])
        self.assertEqual(report["excluded_non_finite"], 1)

    def test_cli_emits_auditable_report(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--lower",
                "1000",
                "--upper",
                "5000",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["source_shape"], [5, 4])
        self.assertEqual(report["selected_shape"], [3, 3])
        self.assertEqual(report["excluded_non_finite"], 1)
        self.assertFalse(report["shares_memory"])

    def test_cli_rejects_invalid_selection_without_traceback(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--filter-column",
                "8",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("out of bounds", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_main_example_runs(self) -> None:
        result = subprocess.run(
            [sys.executable, EXAMPLE],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("selected shape: (2, 3)", result.stdout)
        self.assertIn("shares memory: False", result.stdout)


if __name__ == "__main__":
    unittest.main()
