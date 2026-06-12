from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "safe_selection.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("safe_selection", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SELECTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTION)


class SafeSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.orders = pd.read_csv(DATA)

    def test_status_is_normalized_before_filtering(self) -> None:
        result = SELECTION.select_orders(self.orders, statuses={"paid"})
        self.assertEqual(set(result["order_id"]), {"O1001", "O1003", "O1005", "O1007"})

    def test_currency_filter_is_case_insensitive(self) -> None:
        result = SELECTION.select_orders(self.orders, currencies={"usd"})
        self.assertEqual(set(result["order_id"]), {"O1005", "O1006"})

    def test_numeric_boundaries_are_inclusive(self) -> None:
        result = SELECTION.select_orders(
            self.orders,
            min_amount=75.5,
            max_amount=75.5,
        )
        self.assertEqual(result["order_id"].tolist(), ["O1007"])

    def test_missing_amount_is_excluded(self) -> None:
        result = SELECTION.select_orders(self.orders, min_amount=0)
        self.assertNotIn("O1004", result["order_id"].tolist())

    def test_reversed_bounds_are_rejected(self) -> None:
        with self.assertRaisesRegex(SELECTION.SelectionContractError, "exceed"):
            SELECTION.build_order_mask(self.orders, min_amount=10, max_amount=5)

    def test_selection_returns_independent_frame(self) -> None:
        result = SELECTION.select_orders(self.orders, statuses={"paid"})
        result.loc[:, "status"] = "changed"
        self.assertNotIn("changed", self.orders["status"].tolist())

    def test_label_selected_uses_matching_index(self) -> None:
        mask = SELECTION.build_order_mask(self.orders, statuses={"refunded"})
        labeled = SELECTION.label_selected(self.orders, mask)
        self.assertEqual(
            labeled.loc[
                labeled["order_id"] == "O1002",
                "review_status",
            ].item(),
            "review",
        )

    def test_cli_reports_selected_ids(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, DATA, "--status", "paid", "--min-amount", "70"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["selected_rows"], 3)


if __name__ == "__main__":
    unittest.main()
