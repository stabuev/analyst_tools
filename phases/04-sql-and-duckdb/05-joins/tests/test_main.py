from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "safe_join.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("safe_join", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
JOIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(JOIN)


class SafeJoinTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = JOIN.audit_join(
            DATA / "users.csv",
            DATA / "orders.csv",
            DATA / "order_items.csv",
        )
        self.metrics = self.report["metrics"]

    def test_cardinality_contract_is_declared(self) -> None:
        self.assertEqual(
            self.report["expected_cardinality"]["orders_to_items"],
            "one-to-many",
        )

    def test_naive_join_expands_rows(self) -> None:
        self.assertEqual(self.metrics["order_rows"], 12)
        self.assertEqual(self.metrics["naive_rows"], 14)
        self.assertTrue(self.report["checks"]["fanout_detected"])

    def test_naive_join_inflates_revenue(self) -> None:
        self.assertEqual(self.metrics["naive_paid_revenue"], 7705.0)
        self.assertEqual(self.metrics["fanout_extra_revenue"], 2700.0)

    def test_preaggregation_preserves_order_grain(self) -> None:
        self.assertEqual(self.metrics["safe_rows"], 12)
        self.assertTrue(self.report["checks"]["safe_grain_preserved"])

    def test_safe_paid_revenue_matches_source_grain(self) -> None:
        self.assertEqual(self.metrics["safe_paid_revenue"], 5005.0)
        self.assertTrue(self.report["checks"]["safe_revenue"])

    def test_unknown_user_is_preserved(self) -> None:
        self.assertEqual(self.metrics["unmatched_user_orders"], 1)

    def test_item_totals_match_known_order_amounts(self) -> None:
        self.assertEqual(self.metrics["amount_item_mismatches"], 0)
        self.assertEqual(self.metrics["multi_item_orders"], 2)

    def test_cli_prints_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--users",
                DATA / "users.csv",
                "--orders",
                DATA / "orders.csv",
                "--items",
                DATA / "order_items.csv",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["checks"]["fanout_detected"])


if __name__ == "__main__":
    unittest.main()
