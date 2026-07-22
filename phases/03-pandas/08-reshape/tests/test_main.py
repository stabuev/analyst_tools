from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "reshape_contract.py"
SPEC = importlib.util.spec_from_file_location("reshape_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
RESHAPE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RESHAPE)


def typed_wide() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "user_id": ["U1", "U2"],
            "currency": ["RUB", "RUB"],
            "paid": [2, 1],
            "refunded": [0, pd.NA],
            "pending": [1, 0],
        },
        index=["source-a", "source-b"],
    ).astype(
        {
            "user_id": "string",
            "currency": "string",
            "paid": "Int64",
            "refunded": "Int64",
            "pending": "Int64",
        }
    )


def to_status_long(frame: pd.DataFrame | None = None) -> pd.DataFrame:
    return RESHAPE.to_long(
        typed_wide() if frame is None else frame,
        id_vars=["user_id", "currency"],
        value_vars=["paid", "refunded", "pending"],
        variable_name="status",
        value_name="order_count",
    )


class ToLongTest(unittest.TestCase):
    def test_row_count_is_source_rows_times_measured_columns(self) -> None:
        result = to_status_long()
        self.assertEqual(len(result), 2 * 3)

    def test_identifiers_repeat_for_each_measured_column(self) -> None:
        result = to_status_long()
        counts = result.groupby(["user_id", "currency"], observed=True).size()
        self.assertEqual(counts.tolist(), [3, 3])

    def test_measured_column_names_become_values(self) -> None:
        result = to_status_long()
        self.assertEqual(
            result["status"].drop_duplicates().tolist(),
            ["paid", "refunded", "pending"],
        )

    def test_missing_measured_value_is_preserved(self) -> None:
        result = to_status_long()
        row = result.loc[
            result["user_id"].eq("U2") & result["status"].eq("refunded")
        ].iloc[0]
        self.assertTrue(pd.isna(row["order_count"]))
        self.assertEqual(int(result["order_count"].isna().sum()), 1)

    def test_technical_index_is_not_treated_as_identity(self) -> None:
        result = to_status_long()
        self.assertIsInstance(result.index, pd.RangeIndex)
        self.assertEqual(result.index.tolist(), list(range(6)))

    def test_multiple_identifiers_preserve_source_grain(self) -> None:
        frame = typed_wide()
        frame.loc["source-b", "currency"] = "USD"
        result = to_status_long(frame)
        self.assertEqual(
            result.loc[result["user_id"].eq("U2"), "currency"].unique().tolist(),
            ["USD"],
        )

    def test_incomplete_identifier_rejects_ambiguous_wide_rows(self) -> None:
        frame = typed_wide()
        frame.loc["source-b", "user_id"] = "U1"
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "identify one source"):
            RESHAPE.to_long(
                frame,
                id_vars=["user_id"],
                value_vars=["paid", "refunded", "pending"],
            )

    def test_missing_or_blank_identifier_is_rejected(self) -> None:
        for value in (pd.NA, "  "):
            with self.subTest(value=value):
                frame = typed_wide()
                frame.loc["source-a", "user_id"] = value
                with self.assertRaisesRegex(
                    RESHAPE.ReshapeContractError, "identifier column"
                ):
                    to_status_long(frame)

    def test_different_measured_dtypes_are_rejected(self) -> None:
        frame = typed_wide().astype({"pending": "Float64"})
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "one declared dtype"):
            to_status_long(frame)

    def test_missing_columns_and_overlapping_roles_are_rejected(self) -> None:
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "missing columns"):
            RESHAPE.to_long(
                typed_wide(), id_vars=["user_id"], value_vars=["not_here"]
            )
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "must not overlap"):
            RESHAPE.to_long(
                typed_wide(), id_vars=["user_id"], value_vars=["user_id"]
            )

    def test_output_name_collision_is_rejected(self) -> None:
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "collide"):
            RESHAPE.to_long(
                typed_wide(),
                id_vars=["user_id"],
                value_vars=["paid", "refunded"],
                variable_name="currency",
            )

    def test_duplicate_column_labels_are_rejected(self) -> None:
        frame = typed_wide()
        frame.columns = ["user_id", "currency", "paid", "paid", "pending"]
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "column labels"):
            RESHAPE.to_long(
                frame, id_vars=["user_id"], value_vars=["paid", "pending"]
            )

    def test_typed_empty_frame_returns_typed_empty_long_frame(self) -> None:
        result = to_status_long(typed_wide().iloc[:0])
        self.assertTrue(result.empty)
        self.assertEqual(
            result.columns.tolist(),
            ["user_id", "currency", "status", "order_count"],
        )
        self.assertEqual(str(result["order_count"].dtype), "Int64")

    def test_input_is_not_modified(self) -> None:
        frame = typed_wide()
        before = frame.copy(deep=True)
        to_status_long(frame)
        pd.testing.assert_frame_equal(frame, before)


class PivotUniqueTest(unittest.TestCase):
    def test_unique_cell_key_builds_one_row_per_index_key(self) -> None:
        result = RESHAPE.pivot_unique(
            to_status_long(),
            index=["user_id", "currency"],
            columns="status",
            values="order_count",
        )
        self.assertEqual(len(result), 2)
        self.assertFalse(result.duplicated(["user_id", "currency"]).any())

    def test_round_trip_preserves_values_and_missingness(self) -> None:
        source = typed_wide().reset_index(drop=True)
        result = RESHAPE.pivot_unique(
            to_status_long(),
            index=["user_id", "currency"],
            columns="status",
            values="order_count",
        ).loc[:, source.columns]
        pd.testing.assert_frame_equal(result, source, check_names=False)

    def test_ambiguous_cell_key_is_rejected_with_key_example(self) -> None:
        long = to_status_long()
        conflict = long.loc[
            long["user_id"].eq("U1") & long["status"].eq("paid")
        ].assign(order_count=99)
        broken = pd.concat([long, conflict], ignore_index=True)
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "conflicting keys"):
            RESHAPE.pivot_unique(
                broken,
                index=["user_id", "currency"],
                columns="status",
                values="order_count",
            )

    def test_omitted_part_of_cell_key_is_rejected(self) -> None:
        rub = to_status_long()
        usd = rub.assign(currency="USD")
        long = pd.concat([rub, usd], ignore_index=True)
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "cell key"):
            RESHAPE.pivot_unique(
                long,
                index=["user_id"],
                columns="status",
                values="order_count",
            )

    def test_missing_pivot_key_is_rejected_but_missing_value_is_allowed(self) -> None:
        long = to_status_long()
        broken = long.copy()
        broken.loc[0, "status"] = pd.NA
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "pivot key"):
            RESHAPE.pivot_unique(
                broken,
                index=["user_id", "currency"],
                columns="status",
                values="order_count",
            )

        result = RESHAPE.pivot_unique(
            long,
            index=["user_id", "currency"],
            columns="status",
            values="order_count",
        )
        self.assertTrue(pd.isna(result.loc[result["user_id"].eq("U2"), "refunded"]).all())

    def test_absent_combination_remains_missing_not_zero(self) -> None:
        long = to_status_long()
        long = long.loc[
            ~(long["user_id"].eq("U2") & long["status"].eq("pending"))
        ]
        result = RESHAPE.pivot_unique(
            long,
            index=["user_id", "currency"],
            columns="status",
            values="order_count",
        )
        value = result.loc[result["user_id"].eq("U2"), "pending"].iloc[0]
        self.assertTrue(pd.isna(value))

    def test_future_wide_label_collision_is_rejected(self) -> None:
        long = to_status_long()
        long.loc[0, "status"] = "user_id"
        with self.assertRaisesRegex(RESHAPE.ReshapeContractError, "future wide"):
            RESHAPE.pivot_unique(
                long,
                index=["user_id", "currency"],
                columns="status",
                values="order_count",
            )

    def test_typed_empty_long_frame_returns_empty_wide_frame(self) -> None:
        empty = to_status_long(typed_wide().iloc[:0])
        result = RESHAPE.pivot_unique(
            empty,
            index=["user_id", "currency"],
            columns="status",
            values="order_count",
        )
        self.assertTrue(result.empty)
        self.assertEqual(result.columns.tolist(), ["user_id", "currency"])

    def test_input_is_not_modified(self) -> None:
        frame = to_status_long()
        before = frame.copy(deep=True)
        RESHAPE.pivot_unique(
            frame,
            index=["user_id", "currency"],
            columns="status",
            values="order_count",
        )
        pd.testing.assert_frame_equal(frame, before)


if __name__ == "__main__":
    unittest.main()
