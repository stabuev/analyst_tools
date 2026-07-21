from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "safe_merge.py"
SPEC = importlib.util.spec_from_file_location("safe_merge", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
MERGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MERGE)


def typed_orders(order_ids: list[str] | None = None) -> pd.DataFrame:
    ids = order_ids or ["O1", "O2", "O3"]
    amounts = [100.0, pd.NA, 0.0][: len(ids)]
    return pd.DataFrame({"order_id": ids, "amount": amounts}).astype(
        {"order_id": "string", "amount": "Float64"}
    )


def typed_rollup(order_ids: list[str] | None = None) -> pd.DataFrame:
    ids = order_ids or ["O1", "O2"]
    size = len(ids)
    return pd.DataFrame(
        {
            "order_id": ids,
            "line_count": [1] * size,
            "known_amount_lines": [1] * size,
            "missing_amount_lines": [0] * size,
            "known_amount_total": [100.0] * size,
            "order_amount": [100.0] * size,
        }
    ).astype(
        {
            "order_id": "string",
            "line_count": "Int64",
            "known_amount_lines": "Int64",
            "missing_amount_lines": "Int64",
            "known_amount_total": "Float64",
            "order_amount": "Float64",
        }
    )


def typed_line_items() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": ["O1", "O1", "O2"],
            "product_id": ["P1", "P2", "P3"],
        }
    ).astype({"order_id": "string", "product_id": "string"})


class MergeWithContractTest(unittest.TestCase):
    def test_one_to_one_merge_reports_keys_and_rows(self) -> None:
        result, report = MERGE.merge_with_contract(
            typed_orders(["O1", "O2"]),
            typed_rollup(["O1", "O2"]),
            on=["order_id"],
            how="inner",
            validate="one_to_one",
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(report["matched_key_count"], 2)
        self.assertEqual(report["predicted_result_rows"], 2)
        self.assertEqual(report["result_rows"], 2)

    def test_one_to_many_direction_means_unique_left_key(self) -> None:
        result, report = MERGE.merge_with_contract(
            typed_orders(["O1", "O2"]),
            typed_line_items(),
            on=["order_id"],
            how="left",
            validate="one_to_many",
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(report["predicted_result_rows"], 3)

    def test_many_to_one_direction_means_unique_right_key(self) -> None:
        result, _ = MERGE.merge_with_contract(
            typed_line_items(),
            typed_orders(["O1", "O2"]),
            on=["order_id"],
            how="left",
            validate="many_to_one",
        )
        self.assertEqual(len(result), 3)

    def test_composite_key_uses_all_declared_columns(self) -> None:
        left = typed_line_items()
        right = pd.DataFrame(
            {
                "order_id": ["O1", "O1", "O2"],
                "product_id": ["P1", "P2", "P3"],
                "product_cost": [40.0, 50.0, 20.0],
            }
        ).astype(
            {
                "order_id": "string",
                "product_id": "string",
                "product_cost": "Float64",
            }
        )
        result, report = MERGE.merge_with_contract(
            left,
            right,
            on=["order_id", "product_id"],
            how="left",
            validate="one_to_one",
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(report["matched_key_count"], 3)

    def test_wrong_cardinality_is_rejected_before_merge(self) -> None:
        duplicate_right = pd.concat(
            [typed_rollup(["O1", "O2"]), typed_rollup(["O1"])],
            ignore_index=True,
        )
        with self.assertRaisesRegex(MERGE.MergeContractError, "right key must be unique"):
            MERGE.merge_with_contract(
                typed_orders(["O1", "O2"]),
                duplicate_right,
                on=["order_id"],
                how="left",
                validate="one_to_one",
            )

    def test_many_to_many_declaration_is_rejected_as_unchecked(self) -> None:
        with self.assertRaisesRegex(MERGE.MergeContractError, "performs no uniqueness"):
            MERGE.merge_with_contract(
                typed_line_items(),
                typed_line_items().rename(columns={"product_id": "sku_id"}),
                on=["order_id"],
                how="inner",
                validate="many_to_many",
            )

    def test_join_type_controls_which_keys_survive(self) -> None:
        left = typed_orders(["O1", "O2"])
        right = typed_rollup(["O2", "O3"])
        expected = {"inner": 1, "left": 2, "right": 2, "outer": 3}

        for how, expected_rows in expected.items():
            with self.subTest(how=how):
                result, report = MERGE.merge_with_contract(
                    left,
                    right,
                    on=["order_id"],
                    how=how,
                    validate="one_to_one",
                )
                self.assertEqual(len(result), expected_rows)
                self.assertEqual(report["predicted_result_rows"], expected_rows)

    def test_left_join_still_reports_right_only_unique_keys(self) -> None:
        _, report = MERGE.merge_with_contract(
            typed_orders(["O1", "O2"]),
            typed_rollup(["O2", "O3"]),
            on=["order_id"],
            how="left",
            validate="one_to_one",
        )
        self.assertEqual(report["left_only_key_count"], 1)
        self.assertEqual(report["right_only_key_count"], 1)
        self.assertEqual(report["left_only_key_examples"], [{"order_id": "O1"}])
        self.assertEqual(report["right_only_key_examples"], [{"order_id": "O3"}])

    def test_unmatched_report_counts_keys_not_repeated_rows(self) -> None:
        left = typed_line_items().loc[lambda frame: frame["order_id"].eq("O1")]
        right = typed_orders(["O2"])
        result, report = MERGE.merge_with_contract(
            left,
            right,
            on=["order_id"],
            how="left",
            validate="many_to_one",
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(report["left_only_key_count"], 1)

    def test_missing_or_blank_business_key_is_rejected(self) -> None:
        for value in (pd.NA, "  "):
            with self.subTest(value=value):
                broken = typed_orders(["O1", "O2"])
                broken.loc[0, "order_id"] = value
                with self.assertRaisesRegex(MERGE.MergeContractError, "merge key"):
                    MERGE.merge_with_contract(
                        broken,
                        typed_rollup(["O1", "O2"]),
                        on=["order_id"],
                        how="left",
                        validate="one_to_one",
                    )

    def test_key_dtype_mismatch_is_rejected(self) -> None:
        right = typed_rollup(["O1", "O2"]).astype({"order_id": "object"})
        with self.assertRaisesRegex(MERGE.MergeContractError, "dtypes must match"):
            MERGE.merge_with_contract(
                typed_orders(["O1", "O2"]),
                right,
                on=["order_id"],
                how="left",
                validate="one_to_one",
            )

    def test_overlapping_payload_columns_are_rejected(self) -> None:
        right = typed_rollup(["O1", "O2"]).rename(
            columns={"order_amount": "amount"}
        )
        with self.assertRaisesRegex(MERGE.MergeContractError, "non-key columns overlap"):
            MERGE.merge_with_contract(
                typed_orders(["O1", "O2"]),
                right,
                on=["order_id"],
                how="left",
                validate="one_to_one",
            )

    def test_duplicate_column_labels_are_rejected(self) -> None:
        broken = typed_orders(["O1", "O2"])
        broken.columns = ["order_id", "order_id"]
        with self.assertRaisesRegex(MERGE.MergeContractError, "column labels"):
            MERGE.merge_with_contract(
                broken,
                typed_rollup(["O1", "O2"]),
                on=["order_id"],
                how="left",
                validate="one_to_one",
            )

    def test_input_frames_are_not_modified(self) -> None:
        left = typed_orders(["O1", "O2"])
        right = typed_rollup(["O1", "O2"])
        left_before = left.copy(deep=True)
        right_before = right.copy(deep=True)
        MERGE.merge_with_contract(
            left,
            right,
            on=["order_id"],
            how="left",
            validate="one_to_one",
        )
        pd.testing.assert_frame_equal(left, left_before)
        pd.testing.assert_frame_equal(right, right_before)


class AttachOrderRollupTest(unittest.TestCase):
    def test_preserves_order_grain_and_left_values(self) -> None:
        orders = typed_orders()
        result, report = MERGE.attach_order_rollup(orders, typed_rollup())
        self.assertEqual(len(result), len(orders))
        self.assertTrue(result["order_id"].is_unique)
        self.assertTrue(report["grain_preserved"])
        self.assertTrue(report["left_values_preserved"])
        self.assertEqual(
            result["amount"].sum(min_count=1),
            orders["amount"].sum(min_count=1),
        )

    def test_order_without_items_is_preserved_and_reported(self) -> None:
        result, report = MERGE.attach_order_rollup(typed_orders(), typed_rollup())
        row = result.loc[result["order_id"].eq("O3")].iloc[0]
        self.assertEqual(row["items_match"], "left_only")
        self.assertTrue(pd.isna(row["line_count"]))
        self.assertEqual(report["left_only_key_count"], 1)

    def test_rollup_for_unknown_order_is_rejected(self) -> None:
        with self.assertRaisesRegex(MERGE.MergeContractError, "unknown orders"):
            MERGE.attach_order_rollup(
                typed_orders(["O1", "O2"]),
                typed_rollup(["O1", "O3"]),
            )

    def test_strict_unknown_order_amount_survives_merge(self) -> None:
        rollup = typed_rollup(["O1", "O2"])
        rollup.loc[1, "known_amount_lines"] = 0
        rollup.loc[1, "missing_amount_lines"] = 1
        rollup.loc[1, ["known_amount_total", "order_amount"]] = pd.NA
        result, _ = MERGE.attach_order_rollup(
            typed_orders(["O1", "O2"]),
            rollup,
        )
        self.assertTrue(pd.isna(result.loc[1, "order_amount"]))
        self.assertEqual(str(result["order_amount"].dtype), "Float64")

    def test_wrong_rollup_dtype_is_rejected_instead_of_reparsed(self) -> None:
        broken = typed_rollup().astype({"order_amount": "float64"})
        with self.assertRaisesRegex(MERGE.MergeContractError, "03/05 dtype contract"):
            MERGE.attach_order_rollup(typed_orders(), broken)

    def test_duplicate_order_key_is_rejected(self) -> None:
        duplicate = pd.concat(
            [typed_orders(["O1", "O2"]), typed_orders(["O1"])],
            ignore_index=True,
        )
        with self.assertRaisesRegex(MERGE.MergeContractError, "left key must be unique"):
            MERGE.attach_order_rollup(duplicate, typed_rollup(["O1", "O2"]))

    def test_empty_typed_inputs_return_empty_typed_result(self) -> None:
        orders = typed_orders(["O1"]).iloc[:0]
        rollup = typed_rollup(["O1"]).iloc[:0]
        result, report = MERGE.attach_order_rollup(orders, rollup)
        self.assertTrue(result.empty)
        self.assertEqual(str(result["order_amount"].dtype), "Float64")
        self.assertEqual(report["result_rows"], 0)


if __name__ == "__main__":
    unittest.main()
