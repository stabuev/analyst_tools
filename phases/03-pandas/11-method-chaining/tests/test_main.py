from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "order_pipeline.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("order_pipeline", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class OrderPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.orders = pd.read_csv(DATA)

    def test_pipeline_preserves_order_grain_and_sorts_deterministically(self) -> None:
        result = PIPELINE.prepare_orders(self.orders, timezone="Europe/Moscow")

        self.assertEqual(len(result), len(self.orders))
        self.assertTrue(result["order_id"].is_unique)
        self.assertEqual(result["order_id"].tolist(), sorted(self.orders["order_id"]))
        self.assertEqual(result.index.tolist(), list(range(len(result))))

    def test_pipeline_normalizes_text_and_declares_dtypes(self) -> None:
        result = PIPELINE.prepare_orders(self.orders, timezone="Europe/Moscow")

        self.assertEqual(
            result["status"].cat.categories.tolist(),
            PIPELINE.STATUS_CATEGORIES,
        )
        self.assertEqual(str(result["amount"].dtype), "Float64")
        self.assertEqual(str(result["currency"].dtype), "string")
        self.assertEqual(str(result["is_paid"].dtype), "boolean")
        self.assertEqual(
            result.loc[result["order_id"].eq("O1003"), "status"].iloc[0],
            "paid",
        )

    def test_pipeline_adds_utc_local_date_and_paid_metrics(self) -> None:
        result = PIPELINE.prepare_orders(self.orders, timezone="Europe/Moscow")
        order = result.set_index("order_id")

        self.assertEqual(str(order.loc["O1002", "ordered_at_utc"]), "2026-02-01 23:30:00+00:00")
        self.assertEqual(str(order.loc["O1002", "local_order_date"]), "2026-02-02")
        self.assertTrue(order.loc["O1003", "is_paid"])
        self.assertEqual(float(order.loc["O1003", "paid_amount"]), 5500.0)
        self.assertEqual(float(order.loc["O1004", "paid_amount"]), 0.0)

    def test_pipeline_does_not_mutate_input(self) -> None:
        original = self.orders.copy(deep=True)

        PIPELINE.prepare_orders(self.orders, timezone="Europe/Moscow")

        pd.testing.assert_frame_equal(self.orders, original)

    def test_duplicate_order_fails_at_raw_checkpoint(self) -> None:
        broken = pd.concat([self.orders, self.orders.iloc[[0]]], ignore_index=True)

        with self.assertRaisesRegex(
            PIPELINE.PipelineContractError,
            "check_raw_orders.*duplicates",
        ):
            PIPELINE.prepare_orders(broken, timezone="Europe/Moscow")

    def test_blank_order_id_fails_at_raw_checkpoint(self) -> None:
        broken = self.orders.copy()
        broken.loc[0, "order_id"] = "   "

        with self.assertRaisesRegex(
            PIPELINE.PipelineContractError,
            "check_raw_orders.*non-missing and non-blank",
        ):
            PIPELINE.prepare_orders(broken, timezone="Europe/Moscow")

    def test_invalid_amount_does_not_turn_into_missing(self) -> None:
        broken = self.orders.copy()
        broken["amount"] = broken["amount"].astype("object")
        broken.loc[0, "amount"] = "oops"

        with self.assertRaisesRegex(
            PIPELINE.PipelineContractError,
            "normalize_order_fields.*invalid amount.*oops",
        ):
            PIPELINE.prepare_orders(broken, timezone="Europe/Moscow")

    def test_missing_status_fails_before_paid_metrics(self) -> None:
        broken = self.orders.copy()
        broken.loc[0, "status"] = None

        with self.assertRaisesRegex(
            PIPELINE.PipelineContractError,
            "normalize_order_fields.*status must be non-missing",
        ):
            PIPELINE.prepare_orders(broken, timezone="Europe/Moscow")

    def test_unknown_status_fails_before_paid_metrics(self) -> None:
        broken = self.orders.copy()
        broken.loc[0, "status"] = "completed"

        with self.assertRaisesRegex(
            PIPELINE.PipelineContractError,
            "normalize_order_fields.*unknown status.*completed",
        ):
            PIPELINE.prepare_orders(broken, timezone="Europe/Moscow")

    def test_paid_order_with_missing_amount_fails_at_final_checkpoint(self) -> None:
        broken = self.orders.copy()
        broken.loc[0, "amount"] = pd.NA

        with self.assertRaisesRegex(
            PIPELINE.PipelineContractError,
            "check_prepared_orders.*paid orders need amount.*O1001",
        ):
            PIPELINE.prepare_orders(broken, timezone="Europe/Moscow")

    def test_naive_timestamp_is_not_silently_interpreted_as_utc(self) -> None:
        broken = self.orders.copy()
        broken.loc[0, "ordered_at"] = "2026-02-01 10:00:00"

        with self.assertRaisesRegex(
            PIPELINE.PipelineContractError,
            "add_time_columns.*explicit UTC offset",
        ):
            PIPELINE.prepare_orders(broken, timezone="Europe/Moscow")

    def test_invalid_timestamp_fails_at_time_stage(self) -> None:
        broken = self.orders.copy()
        broken.loc[0, "ordered_at"] = "not-a-date"

        with self.assertRaisesRegex(
            PIPELINE.PipelineContractError,
            "add_time_columns.*invalid ordered_at",
        ):
            PIPELINE.prepare_orders(broken, timezone="Europe/Moscow")

    def test_invalid_timezone_fails_at_time_stage(self) -> None:
        with self.assertRaisesRegex(
            PIPELINE.PipelineContractError,
            "add_time_columns.*invalid timezone",
        ):
            PIPELINE.prepare_orders(self.orders, timezone="Mars/Olympus")

    def test_checkpoint_detects_reordered_intermediate_rows(self) -> None:
        normalized = PIPELINE.normalize_order_fields(self.orders)
        reordered = normalized.iloc[::-1]

        with self.assertRaisesRegex(
            PIPELINE.PipelineContractError,
            "check_normalized_orders.*row labels or their order",
        ):
            PIPELINE.check_normalized_orders(
                reordered,
                expected_index=self.orders.index,
            )


if __name__ == "__main__":
    unittest.main()
