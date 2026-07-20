from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "order_transforms.py"
SPEC = importlib.util.spec_from_file_location("order_transforms", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
TRANSFORMS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSFORMS)


def make_items() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["O1001", "O1001", "O1002", "O1003", "O1004"],
            "product_id": ["P01", "P02", "P03", "P04", "P05"],
            "quantity": [2, 1, 3, 1, 1],
            "unit_price": [400.0, 800.0, pd.NA, 75.5, 0.0],
        },
        index=pd.Index(
            ["item-a", "item-b", "item-c", "item-d", "item-e"],
            name="row_label",
        ),
    ).astype(
        {
            "order_id": "string",
            "product_id": "string",
            "quantity": "Int64",
            "unit_price": "Float64",
        }
    )


class LineItemFeaturesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.items = make_items()

    def transform(self) -> pd.DataFrame:
        return TRANSFORMS.add_line_item_features(
            self.items,
            review_threshold=800.0,
        )

    def test_line_total_matches_manual_row_calculation(self) -> None:
        result = self.transform()
        expected = pd.Series(
            [800.0, 800.0, pd.NA, 75.5, 0.0],
            index=self.items.index,
            dtype="Float64",
            name="line_total",
        )
        pd.testing.assert_series_equal(result["line_total"], expected)

    def test_threshold_is_inclusive(self) -> None:
        result = self.transform()
        self.assertEqual(result.loc["item-a", "requires_review"], True)
        self.assertEqual(result.loc["item-b", "requires_review"], True)
        self.assertEqual(result.loc["item-d", "requires_review"], False)

    def test_unknown_condition_remains_unknown(self) -> None:
        result = self.transform()
        self.assertTrue(pd.isna(result.loc["item-c", "requires_review"]))
        self.assertTrue(pd.isna(result.loc["item-c", "review_amount"]))

    def test_known_false_condition_becomes_zero(self) -> None:
        result = self.transform()
        self.assertEqual(result.loc["item-d", "review_amount"], 0.0)
        self.assertEqual(result.loc["item-e", "review_amount"], 0.0)

    def test_known_true_condition_keeps_line_total(self) -> None:
        result = self.transform()
        self.assertEqual(result.loc["item-a", "review_amount"], 800.0)
        self.assertEqual(result.loc["item-b", "review_amount"], 800.0)

    def test_output_preserves_row_count_index_and_existing_columns(self) -> None:
        result = self.transform()
        self.assertEqual(len(result), len(self.items))
        self.assertTrue(result.index.equals(self.items.index))
        pd.testing.assert_frame_equal(result[self.items.columns], self.items)

    def test_input_frame_is_not_modified(self) -> None:
        before = self.items.copy()
        self.transform()
        pd.testing.assert_frame_equal(self.items, before)

    def test_derived_columns_use_nullable_dtypes(self) -> None:
        result = self.transform()
        self.assertEqual(str(result["line_total"].dtype), "Float64")
        self.assertEqual(str(result["requires_review"].dtype), "boolean")
        self.assertEqual(str(result["review_amount"].dtype), "Float64")

    def test_missing_required_column_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            TRANSFORMS.TransformContractError,
            "missing columns.*unit_price",
        ):
            TRANSFORMS.add_line_item_features(
                self.items.drop(columns="unit_price"),
                review_threshold=800.0,
            )

    def test_raw_string_numbers_are_not_silently_parsed(self) -> None:
        raw = self.items.astype({"quantity": "string", "unit_price": "string"})
        with self.assertRaisesRegex(
            TRANSFORMS.TransformContractError,
            "dtype contract",
        ):
            TRANSFORMS.add_line_item_features(raw, review_threshold=800.0)

    def test_existing_output_column_is_not_silently_overwritten(self) -> None:
        conflicting = self.items.copy()
        conflicting["line_total"] = pd.Series(
            [1.0, 2.0, 3.0, 4.0, 5.0],
            index=conflicting.index,
            dtype="Float64",
        )
        with self.assertRaisesRegex(
            TRANSFORMS.TransformContractError,
            "output columns already exist.*line_total",
        ):
            TRANSFORMS.add_line_item_features(
                conflicting,
                review_threshold=800.0,
            )

    def test_non_positive_quantity_is_rejected(self) -> None:
        invalid = self.items.copy()
        invalid.loc["item-a", "quantity"] = 0
        with self.assertRaisesRegex(
            TRANSFORMS.TransformContractError,
            "quantity must be positive.*item-a",
        ):
            TRANSFORMS.add_line_item_features(invalid, review_threshold=800.0)

    def test_negative_price_is_rejected(self) -> None:
        invalid = self.items.copy()
        invalid.loc["item-b", "unit_price"] = -1.0
        with self.assertRaisesRegex(
            TRANSFORMS.TransformContractError,
            "unit_price must be non-negative.*item-b",
        ):
            TRANSFORMS.add_line_item_features(invalid, review_threshold=800.0)

    def test_invalid_review_threshold_is_rejected(self) -> None:
        for threshold in (-1, float("inf"), float("nan"), True, "800"):
            with self.subTest(threshold=threshold), self.assertRaisesRegex(
                TRANSFORMS.TransformContractError,
                "finite non-negative number",
            ):
                TRANSFORMS.add_line_item_features(
                    self.items,
                    review_threshold=threshold,
                )

    def test_transform_does_not_require_row_wise_apply(self) -> None:
        original = pd.DataFrame.apply
        pd.DataFrame.apply = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("DataFrame.apply must not be used")
        )
        try:
            self.transform()
        finally:
            pd.DataFrame.apply = original


if __name__ == "__main__":
    unittest.main()
