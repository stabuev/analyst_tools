from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "safe_merge.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("safe_merge", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
MERGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MERGE)


class SafeMergeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.orders = pd.read_csv(DATA / "orders.csv")
        self.items = pd.read_csv(DATA / "order_items.csv")

    def test_unique_key_accepts_orders(self) -> None:
        MERGE.assert_unique_key(self.orders, ["order_id"], "orders")

    def test_duplicate_unique_key_is_rejected(self) -> None:
        broken = pd.concat([self.orders, self.orders.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(MERGE.MergeContractError, "not unique"):
            MERGE.assert_unique_key(broken, ["order_id"], "orders")

    def test_validate_rejects_wrong_cardinality(self) -> None:
        with self.assertRaises(MERGE.MergeContractError):
            MERGE.safe_merge(
                self.orders,
                self.items,
                on=["order_id"],
                how="left",
                validate="one_to_one",
            )

    def test_preaggregation_preserves_order_grain(self) -> None:
        result, report = MERGE.attach_item_totals(self.orders, self.items)
        self.assertEqual(len(result), len(self.orders))
        self.assertTrue(result["order_id"].is_unique)
        self.assertTrue(report["grain_preserved"])

    def test_two_item_order_has_correct_total(self) -> None:
        result, _ = MERGE.attach_item_totals(self.orders, self.items)
        row = result.loc[result["order_id"] == "O1001"].iloc[0]
        self.assertEqual(row["item_rows"], 2)
        self.assertEqual(row["item_total"], 1200)

    def test_naive_join_inflates_order_amount(self) -> None:
        naive = self.orders.merge(self.items, on="order_id", how="left")
        original = pd.to_numeric(self.orders["amount"], errors="coerce").sum()
        inflated = pd.to_numeric(naive["amount"], errors="coerce").sum()
        self.assertGreater(inflated, original)

    def test_report_counts_matches_and_unmatched(self) -> None:
        _, report = MERGE.attach_item_totals(self.orders, self.items)
        self.assertEqual(report["matched"], 7)
        self.assertEqual(report["left_only"], 0)

    def test_orphan_item_order_is_rejected(self) -> None:
        broken = self.items.copy()
        broken.loc[0, "order_id"] = "UNKNOWN"
        with self.assertRaisesRegex(MERGE.MergeContractError, "unknown orders"):
            MERGE.attach_item_totals(self.orders, broken)

    def test_cli_reports_multiple_item_orders(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, DATA / "orders.csv", DATA / "order_items.csv"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["orders_with_multiple_items"], 1)


if __name__ == "__main__":
    unittest.main()
