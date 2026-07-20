from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "safe_selection.py"
EXAMPLE = ROOT / "code" / "main.py"
SPEC = importlib.util.spec_from_file_location("safe_selection", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SELECTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTION)


class SafeSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.orders = pd.DataFrame(
            {
                "order_id": pd.array(
                    ["O1001", "O1002", "O1003", "O1004", "O1005"],
                    dtype="string",
                ),
                "status": pd.array(
                    ["paid", "paid", "refunded", pd.NA, "refunded"],
                    dtype="string",
                ),
                "currency": pd.array(
                    ["RUB", "RUB", "USD", "USD", pd.NA],
                    dtype="string",
                ),
                "amount": pd.array(
                    [120.0, pd.NA, 80.0, 100.0, pd.NA],
                    dtype="Float64",
                ),
            },
            index=["row-a", "row-b", "row-c", "row-d", "row-e"],
        )

    def test_combined_mask_preserves_true_false_and_unknown(self) -> None:
        mask = SELECTION.build_order_mask(
            self.orders,
            statuses={"paid"},
            min_amount=70,
        )

        self.assertEqual(str(mask.dtype), "boolean")
        values = mask.tolist()
        self.assertIs(values[0], True)
        self.assertTrue(pd.isna(values[1]))
        self.assertIs(values[2], False)
        self.assertTrue(pd.isna(values[3]))
        self.assertIs(values[4], False)

    def test_native_nullable_masks_preserve_or_not_and_membership_policy(self) -> None:
        is_paid = self.orders["status"].eq("paid")
        amount_is_large = self.orders["amount"].ge(70)

        self.assertTrue(str(is_paid.dtype).startswith("bool["))
        validated = SELECTION.validate_mask(self.orders, is_paid)
        self.assertEqual(str(validated.dtype), "boolean")

        paid_or_large = is_paid | amount_is_large
        self.assertEqual(paid_or_large.iloc[:4].tolist(), [True, True, True, True])
        self.assertTrue(pd.isna(paid_or_large.iloc[4]))

        not_paid = ~is_paid
        self.assertEqual(not_paid.iloc[:3].tolist(), [False, False, True])
        self.assertTrue(pd.isna(not_paid.iloc[3]))
        self.assertIs(not_paid.iloc[4], True)

        raw_membership = self.orders["status"].isin({"paid"})
        restored = SELECTION.build_order_mask(self.orders, statuses={"paid"})
        self.assertFalse(raw_membership.iloc[3])
        self.assertTrue(pd.isna(restored.iloc[3]))

    def test_false_and_unknown_is_definitively_false(self) -> None:
        mask = SELECTION.build_order_mask(
            self.orders,
            statuses={"refunded"},
            min_amount=70,
        )

        values = mask.tolist()
        self.assertIs(values[0], False)
        self.assertIs(values[1], False)
        self.assertIs(values[2], True)
        self.assertTrue(pd.isna(values[3]))
        self.assertTrue(pd.isna(values[4]))

        currency_mask = SELECTION.build_order_mask(
            self.orders,
            currencies={"RUB"},
        )
        self.assertEqual(
            currency_mask.fillna(False).tolist(),
            [True, True, False, False, False],
        )
        self.assertTrue(pd.isna(currency_mask.iloc[4]))

    def test_only_columns_used_by_criteria_are_required(self) -> None:
        status_only = pd.DataFrame(
            {"status": pd.array(["paid", "refunded"], dtype="string")}
        )

        mask = SELECTION.build_order_mask(status_only, statuses={"paid"})

        self.assertEqual(mask.tolist(), [True, False])

    def test_at_least_one_non_empty_criterion_is_required(self) -> None:
        with self.assertRaisesRegex(
            SELECTION.SelectionContractError,
            "at least one",
        ):
            SELECTION.build_order_mask(self.orders)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "must not be empty"):
            SELECTION.build_order_mask(self.orders, statuses=set())

    def test_string_criteria_are_exact_and_not_normalized_silently(self) -> None:
        upper = SELECTION.build_order_mask(self.orders, statuses={"PAID"})
        self.assertEqual(upper.fillna(False).tolist(), [False] * 5)

        with self.assertRaisesRegex(SELECTION.SelectionContractError, "normalized"):
            SELECTION.build_order_mask(self.orders, statuses={" paid "})
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "collection"):
            SELECTION.build_order_mask(self.orders, statuses="paid")

        object_status = self.orders.copy()
        object_status["status"] = object_status["status"].astype(object)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "string dtype"):
            SELECTION.build_order_mask(object_status, statuses={"paid"})

    def test_numeric_boundaries_are_inclusive(self) -> None:
        mask = SELECTION.build_order_mask(
            self.orders,
            min_amount=80,
            max_amount=120,
        )

        values = mask.tolist()
        self.assertIs(values[0], True)
        self.assertTrue(pd.isna(values[1]))
        self.assertIs(values[2], True)
        self.assertIs(values[3], True)

        precise = pd.DataFrame(
            {
                "amount": pd.array(
                    [9_007_199_254_740_992, 9_007_199_254_740_993],
                    dtype="Int64",
                )
            }
        )
        precise_mask = SELECTION.build_order_mask(
            precise,
            min_amount=9_007_199_254_740_993,
        )
        self.assertEqual(precise_mask.tolist(), [False, True])

    def test_invalid_bounds_are_rejected(self) -> None:
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "cannot exceed"):
            SELECTION.build_order_mask(self.orders, min_amount=121, max_amount=120)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "finite"):
            SELECTION.build_order_mask(self.orders, min_amount=float("inf"))
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "not bool"):
            SELECTION.build_order_mask(self.orders, min_amount=True)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "already parsed"):
            SELECTION.build_order_mask(self.orders, min_amount="70")

    def test_amount_must_be_validated_before_selection(self) -> None:
        text_amount = self.orders.assign(amount=self.orders["amount"].astype("string"))
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "dtype audit"):
            SELECTION.build_order_mask(text_amount, min_amount=0)

        bool_amount = self.orders.assign(amount=pd.array([True] * 5, dtype="boolean"))
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "dtype audit"):
            SELECTION.build_order_mask(bool_amount, min_amount=0)

        infinite = self.orders.copy()
        infinite.loc["row-a", "amount"] = float("inf")
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "finite"):
            SELECTION.build_order_mask(infinite, min_amount=0)

    def test_mask_report_keeps_unknown_evidence(self) -> None:
        mask = SELECTION.build_order_mask(
            self.orders,
            statuses={"paid"},
            min_amount=70,
        )

        report = SELECTION.mask_report(self.orders, mask)

        self.assertEqual(report["selected_rows"], 1)
        self.assertEqual(report["excluded_rows"], 2)
        self.assertEqual(report["unknown_rows"], 2)
        self.assertEqual(report["selected_index_examples"], ["row-a"])
        self.assertEqual(
            report["unknown_index_examples"],
            ["row-b", "row-d"],
        )

    def test_exclude_policy_resolves_unknown_but_retains_report(self) -> None:
        mask = SELECTION.build_order_mask(
            self.orders,
            statuses={"paid"},
            min_amount=70,
        )

        resolved, report = SELECTION.resolve_mask(
            self.orders,
            mask,
            missing="exclude",
        )

        self.assertEqual(str(resolved.dtype), "bool")
        self.assertEqual(resolved.tolist(), [True, False, False, False, False])
        self.assertEqual(report["unknown_rows"], 2)
        self.assertEqual(report["missing_policy"], "exclude")

    def test_error_policy_rejects_unknown_truth_values(self) -> None:
        mask = SELECTION.build_order_mask(
            self.orders,
            statuses={"paid"},
            min_amount=70,
        )

        with self.assertRaisesRegex(SELECTION.SelectionContractError, "row-b"):
            SELECTION.resolve_mask(self.orders, mask, missing="error")
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "one of"):
            SELECTION.resolve_mask(self.orders, mask, missing="drop")

    def test_integer_and_unlabeled_masks_are_rejected(self) -> None:
        integer_mask = pd.Series([1, 0, 0, 1, 0], index=self.orders.index)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "boolean dtype"):
            SELECTION.validate_mask(self.orders, integer_mask)
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "pandas Series"):
            SELECTION.validate_mask(self.orders, [True, False, False, True, False])

    def test_reordered_or_foreign_mask_index_is_rejected(self) -> None:
        reordered = pd.Series(
            [True, False, False, False, False],
            index=list(reversed(self.orders.index)),
            dtype="boolean",
        )
        foreign = pd.Series(
            [True, False, False, False, False],
            index=["x", "y", "z", "w", "v"],
            dtype="boolean",
        )

        for mask in (reordered, foreign):
            with self.assertRaisesRegex(SELECTION.SelectionContractError, "exactly match"):
                SELECTION.validate_mask(self.orders, mask)

    def test_duplicate_index_is_rejected_by_strict_contract(self) -> None:
        duplicated = self.orders.copy()
        duplicated.index = ["row-a", "row-a", "row-c", "row-d", "row-e"]
        mask = pd.Series(True, index=duplicated.index, dtype="boolean")

        with self.assertRaisesRegex(SELECTION.SelectionContractError, "must be unique"):
            SELECTION.validate_mask(duplicated, mask)

    def test_select_rows_preserves_column_order_and_source(self) -> None:
        mask = SELECTION.build_order_mask(self.orders, min_amount=80, max_amount=120)
        selected, report = SELECTION.select_rows(
            self.orders,
            mask,
            columns=["amount", "order_id"],
            missing="exclude",
        )

        self.assertIsInstance(selected, pd.DataFrame)
        self.assertEqual(selected.columns.tolist(), ["amount", "order_id"])
        self.assertEqual(selected.index.tolist(), ["row-a", "row-c", "row-d"])
        self.assertEqual(report["output_shape"], [3, 2])

        selected.loc["row-a", "amount"] = 999
        self.assertEqual(self.orders.loc["row-a", "amount"], 120)

    def test_column_contract_rejects_missing_or_duplicate_names(self) -> None:
        mask = SELECTION.build_order_mask(self.orders, statuses={"paid"})
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "duplicates"):
            SELECTION.select_rows(
                self.orders,
                mask,
                columns=["order_id", "order_id"],
            )
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "missing selected"):
            SELECTION.select_rows(self.orders, mask, columns=["unknown"])

    def test_label_rows_changes_only_selected_rows_on_copy(self) -> None:
        mask = SELECTION.build_order_mask(
            self.orders,
            statuses={"paid"},
            min_amount=70,
        )
        labeled, report = SELECTION.label_rows(
            self.orders,
            mask,
            missing="exclude",
        )

        self.assertNotIn("review_status", self.orders.columns)
        self.assertEqual(labeled.loc["row-a", "review_status"], "review")
        self.assertTrue(labeled.loc[labeled.index != "row-a", "review_status"].isna().all())
        self.assertEqual(report["labeled_rows"], 1)

    def test_main_example_runs_and_reports_unknown_rows(self) -> None:
        result = subprocess.run(
            [sys.executable, EXAMPLE],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Unresolved nullable mask", result.stdout)
        self.assertIn('"unknown_rows": 2', result.stdout)
        self.assertIn("O1001", result.stdout)


if __name__ == "__main__":
    unittest.main()
