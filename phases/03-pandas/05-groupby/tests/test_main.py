from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "order_item_rollup.py"
SPEC = importlib.util.spec_from_file_location("order_item_rollup", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
ROLLUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ROLLUP)


def typed_items() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["O1001", "O1001", "O1002", "O1003", "O1004"],
            "product_id": ["P01", "P02", "P03", "P04", "P05"],
            "line_total": [800.0, 800.0, pd.NA, 75.5, 0.0],
        },
        index=["item-a", "item-b", "item-c", "item-d", "item-e"],
    ).astype(
        {
            "order_id": "string",
            "product_id": "string",
            "line_total": "Float64",
        }
    )


class OrderItemRollupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = typed_items()

    def test_repeated_order_id_is_valid_at_line_item_grain(self) -> None:
        result = ROLLUP.aggregate_order_items(self.items)
        self.assertEqual(result["order_id"].tolist(), ["O1001", "O1002", "O1003", "O1004"])

    def test_result_has_one_row_per_order(self) -> None:
        result = ROLLUP.aggregate_order_items(self.items)
        self.assertFalse(result["order_id"].duplicated().any())
        self.assertEqual(len(result), self.items["order_id"].nunique())

    def test_complete_order_gets_strict_total(self) -> None:
        result = ROLLUP.aggregate_order_items(self.items).set_index("order_id")
        self.assertEqual(result.loc["O1001", "line_count"], 2)
        self.assertEqual(result.loc["O1001", "known_amount_lines"], 2)
        self.assertEqual(result.loc["O1001", "missing_amount_lines"], 0)
        self.assertEqual(result.loc["O1001", "known_amount_total"], 1600.0)
        self.assertEqual(result.loc["O1001", "order_amount"], 1600.0)

    def test_all_missing_amounts_do_not_become_zero(self) -> None:
        result = ROLLUP.aggregate_order_items(self.items).set_index("order_id")
        self.assertEqual(result.loc["O1002", "line_count"], 1)
        self.assertEqual(result.loc["O1002", "known_amount_lines"], 0)
        self.assertEqual(result.loc["O1002", "missing_amount_lines"], 1)
        self.assertTrue(pd.isna(result.loc["O1002", "known_amount_total"]))
        self.assertTrue(pd.isna(result.loc["O1002", "order_amount"]))

    def test_partial_known_sum_is_visible_but_order_total_is_unknown(self) -> None:
        partial = pd.DataFrame(
            {
                "order_id": pd.Series(["O1", "O1"], dtype="string"),
                "product_id": pd.Series(["P1", "P2"], dtype="string"),
                "line_total": pd.Series([100.0, pd.NA], dtype="Float64"),
            }
        )
        row = ROLLUP.aggregate_order_items(partial).iloc[0]
        self.assertEqual(row["known_amount_total"], 100.0)
        self.assertEqual(row["missing_amount_lines"], 1)
        self.assertTrue(pd.isna(row["order_amount"]))

    def test_zero_is_known_amount_not_missing_value(self) -> None:
        result = ROLLUP.aggregate_order_items(self.items).set_index("order_id")
        self.assertEqual(result.loc["O1004", "known_amount_lines"], 1)
        self.assertEqual(result.loc["O1004", "order_amount"], 0.0)

    def test_manual_control_matches_pandas_values(self) -> None:
        manual = ROLLUP.manual_order_rollup(self.items.to_dict("records"))
        pandas_result = ROLLUP.aggregate_order_items(self.items).to_dict("records")
        self.assertEqual(
            [row["order_id"] for row in manual],
            [row["order_id"] for row in pandas_result],
        )
        for expected, actual in zip(manual, pandas_result, strict=True):
            self.assertEqual(expected["line_count"], actual["line_count"])
            self.assertEqual(expected["known_amount_lines"], actual["known_amount_lines"])
            self.assertEqual(expected["missing_amount_lines"], actual["missing_amount_lines"])
            for column in ("known_amount_total", "order_amount"):
                if expected[column] is None:
                    self.assertTrue(pd.isna(actual[column]))
                else:
                    self.assertEqual(expected[column], actual[column])

    def test_counts_reconcile_with_source_rows(self) -> None:
        result = ROLLUP.aggregate_order_items(self.items)
        self.assertEqual(int(result["line_count"].sum()), len(self.items))
        self.assertEqual(
            int(result["known_amount_lines"].sum()),
            int(self.items["line_total"].notna().sum()),
        )
        self.assertEqual(
            int(result["missing_amount_lines"].sum()),
            int(self.items["line_total"].isna().sum()),
        )

    def test_output_dtypes_are_explicit(self) -> None:
        result = ROLLUP.aggregate_order_items(self.items)
        self.assertEqual(str(result["order_id"].dtype), "string")
        self.assertEqual(str(result["line_count"].dtype), "Int64")
        self.assertEqual(str(result["known_amount_lines"].dtype), "Int64")
        self.assertEqual(str(result["missing_amount_lines"].dtype), "Int64")
        self.assertEqual(str(result["known_amount_total"].dtype), "Float64")
        self.assertEqual(str(result["order_amount"].dtype), "Float64")

    def test_input_is_not_modified(self) -> None:
        before = self.items.copy(deep=True)
        ROLLUP.aggregate_order_items(self.items)
        pd.testing.assert_frame_equal(self.items, before)

    def test_duplicate_line_item_key_is_rejected(self) -> None:
        duplicate = pd.concat([self.items, self.items.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ROLLUP.AggregationContractError, "one row per"):
            ROLLUP.aggregate_order_items(duplicate)

    def test_missing_or_blank_business_key_is_rejected(self) -> None:
        for column, value in (("order_id", pd.NA), ("product_id", "  ")):
            with self.subTest(column=column, value=value):
                broken = self.items.copy()
                broken.loc["item-a", column] = value
                with self.assertRaisesRegex(ROLLUP.AggregationContractError, column):
                    ROLLUP.aggregate_order_items(broken)

    def test_wrong_dtype_is_rejected_instead_of_reparsed(self) -> None:
        broken = self.items.astype({"line_total": "float64"})
        with self.assertRaisesRegex(ROLLUP.AggregationContractError, "dtype contract"):
            ROLLUP.aggregate_order_items(broken)

    def test_missing_column_is_rejected(self) -> None:
        with self.assertRaisesRegex(ROLLUP.AggregationContractError, "missing columns"):
            ROLLUP.aggregate_order_items(self.items.drop(columns="product_id"))

    def test_empty_typed_input_returns_empty_typed_result(self) -> None:
        result = ROLLUP.aggregate_order_items(self.items.iloc[:0])
        self.assertEqual(result.columns.tolist(), ROLLUP.OUTPUT_COLUMNS)
        self.assertTrue(result.empty)
        self.assertEqual(str(result["order_amount"].dtype), "Float64")


if __name__ == "__main__":
    unittest.main()
