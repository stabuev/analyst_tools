from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "order_transforms.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("order_transforms", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
TRANSFORMS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRANSFORMS)


class OrderTransformsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.orders = pd.read_csv(DATA / "orders.csv")
        self.items = pd.read_csv(DATA / "order_items.csv")

    def test_status_and_currency_are_normalized(self) -> None:
        result = TRANSFORMS.normalize_orders(self.orders)
        self.assertEqual(set(result["status"]), {"paid", "refunded", "pending", "cancelled"})
        self.assertEqual(set(result["currency"]), {"RUB", "KZT", "USD", "EUR"})

    def test_paid_flag_and_amount_share_one_condition(self) -> None:
        result = TRANSFORMS.normalize_orders(self.orders)
        paid = result.loc[result["is_paid"]]
        self.assertEqual(set(paid["order_id"]), {"O1001", "O1003", "O1005", "O1007"})
        self.assertTrue(paid["paid_amount"].eq(paid["amount"]).all())

    def test_non_paid_amount_is_zero(self) -> None:
        result = TRANSFORMS.normalize_orders(self.orders)
        self.assertTrue(result.loc[~result["is_paid"], "paid_amount"].eq(0).all())

    def test_amount_uses_nullable_float(self) -> None:
        result = TRANSFORMS.normalize_orders(self.orders)
        self.assertEqual(str(result["amount"].dtype), "Float64")
        self.assertTrue(pd.isna(result.loc[result["order_id"] == "O1004", "amount"]).item())

    def test_amount_band_keeps_missing_value(self) -> None:
        result = TRANSFORMS.normalize_orders(self.orders)
        self.assertTrue(pd.isna(result.loc[result["order_id"] == "O1004", "amount_band"]).item())

    def test_line_total_is_vectorized_product(self) -> None:
        result = TRANSFORMS.add_line_totals(self.items)
        order = result.loc[result["order_id"] == "O1001", "line_total"]
        self.assertEqual(order.tolist(), [800.0, 400.0])

    def test_transform_does_not_require_dataframe_apply(self) -> None:
        original = pd.DataFrame.apply
        pd.DataFrame.apply = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("apply must not be used")
        )
        try:
            TRANSFORMS.normalize_orders(self.orders)
        finally:
            pd.DataFrame.apply = original

    def test_cli_returns_aggregate_report(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                DATA / "orders.csv",
                "--items",
                DATA / "order_items.csv",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["paid_orders"], 4)


if __name__ == "__main__":
    unittest.main()
