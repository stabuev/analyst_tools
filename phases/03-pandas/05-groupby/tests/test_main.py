from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "segment_metrics.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("segment_metrics", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
METRICS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(METRICS)


class SegmentMetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.orders = pd.read_csv(DATA)

    def test_manual_group_sum_builds_control_result(self) -> None:
        rows = [{"currency": "RUB", "amount": 10}, {"currency": "RUB", "amount": 5}]
        self.assertEqual(
            METRICS.manual_group_sum(rows, key="currency", value="amount"),
            {"RUB": 15.0},
        )

    def test_currency_grain_has_one_row_per_currency(self) -> None:
        result = METRICS.aggregate_paid_orders(self.orders, ["currency"])
        self.assertFalse(result.duplicated(["currency"]).any())
        self.assertEqual(set(result["currency"]), {"RUB", "KZT", "USD", "EUR"})

    def test_only_paid_orders_contribute(self) -> None:
        result = METRICS.aggregate_paid_orders(self.orders, ["currency"]).set_index("currency")
        self.assertEqual(result.loc["RUB", "paid_orders"], 1)
        self.assertEqual(result.loc["RUB", "paid_amount"], 1200)

    def test_manual_control_matches_groupby(self) -> None:
        normalized = self.orders.assign(
            status=self.orders["status"].str.strip().str.lower(),
            amount=pd.to_numeric(self.orders["amount"], errors="coerce"),
        )
        paid = normalized.loc[normalized["status"].eq("paid")]
        manual = METRICS.manual_group_sum(
            paid.to_dict("records"),
            key="currency",
            value="amount",
        )
        result = METRICS.aggregate_paid_orders(self.orders, ["currency"]).set_index("currency")
        self.assertEqual(manual["KZT"], result.loc["KZT", "paid_amount"])

    def test_duplicate_source_grain_is_rejected(self) -> None:
        broken = pd.concat([self.orders, self.orders.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(METRICS.AggregationContractError, "one row"):
            METRICS.aggregate_paid_orders(broken, ["currency"])

    def test_empty_group_list_is_rejected(self) -> None:
        with self.assertRaisesRegex(METRICS.AggregationContractError, "group_by"):
            METRICS.aggregate_paid_orders(self.orders, [])

    def test_multiple_group_columns_define_result_grain(self) -> None:
        result = METRICS.aggregate_paid_orders(self.orders, ["currency", "user_id"])
        self.assertFalse(result.duplicated(["currency", "user_id"]).any())

    def test_cli_exposes_grain_and_records(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, DATA, "--group-by", "currency"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["grain"], ["currency"])
        self.assertEqual(payload["rows"], 4)


if __name__ == "__main__":
    unittest.main()
