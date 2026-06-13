from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "aggregate_model.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("aggregate_model", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AGG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AGG)


class AggregateModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = AGG.build_aggregates(DATA)
        self.rows = {row["currency"]: row for row in self.report["rows"]}

    def test_result_grain_is_one_row_per_currency(self) -> None:
        self.assertEqual(self.report["grain"], ["currency"])
        self.assertTrue(self.report["checks"]["grain_unique"])
        self.assertEqual(set(self.rows), {"EUR", "KZT", "RUB", "USD"})

    def test_rub_control_aggregate(self) -> None:
        self.assertEqual(self.rows["RUB"]["paid_orders"], 2)
        self.assertEqual(self.rows["RUB"]["paid_revenue"], 2700.0)

    def test_eur_control_aggregate(self) -> None:
        self.assertEqual(self.rows["EUR"]["paid_orders"], 3)
        self.assertEqual(self.rows["EUR"]["paid_revenue"], 1625.0)

    def test_total_paid_revenue_matches_manual_sum(self) -> None:
        self.assertEqual(self.report["checks"]["paid_revenue_total"], 5005.0)

    def test_group_rows_reconcile_to_source(self) -> None:
        self.assertEqual(self.report["checks"]["source_rows"], 12)

    def test_count_expression_excludes_null_amount(self) -> None:
        self.assertEqual(self.report["checks"]["known_amount_rows"], 10)
        self.assertEqual(self.rows["USD"]["order_rows"], 4)
        self.assertEqual(self.rows["USD"]["known_amount_rows"], 3)

    def test_average_uses_paid_non_null_amounts(self) -> None:
        self.assertAlmostEqual(self.rows["USD"]["average_paid_amount"], 60.0)

    def test_cli_prints_json(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--orders", DATA],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["checks"]["paid_revenue_total"], 5005.0)


if __name__ == "__main__":
    unittest.main()
