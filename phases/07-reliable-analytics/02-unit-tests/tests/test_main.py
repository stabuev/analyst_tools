from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "order_stage_contracts.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("order_stage_contracts", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CONTRACTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACTS)


class StageContractsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.users, self.orders, self.items = CONTRACTS.load_frames(DATA)

    def assert_contract_error(self, check_id: str, action) -> None:
        with self.assertRaises(CONTRACTS.StageContractError) as caught:
            action()
        self.assertEqual(caught.exception.check_id, check_id)

    def test_baseline_passes_all_boundary_contracts(self) -> None:
        report = CONTRACTS.run_contract_suite(DATA)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["order_count"], 10)
        self.assertEqual(report["summary"]["paid_revenue_kopecks"], 915050)
        self.assertEqual(report["summary"]["metric_days"], 3)

    def test_normalization_rejects_duplicate_grain(self) -> None:
        orders = pd.concat([self.orders, self.orders.iloc[[0]]], ignore_index=True)
        self.assert_contract_error(
            "orders.order_id_unique", lambda: CONTRACTS.normalize_orders(orders)
        )

    def test_normalization_rejects_unknown_status(self) -> None:
        orders = self.orders.copy()
        orders.loc[0, "status"] = "complete"
        self.assert_contract_error(
            "orders.status_domain", lambda: CONTRACTS.normalize_orders(orders)
        )

    def test_mart_rejects_orphan_user(self) -> None:
        orders = self.orders.copy()
        orders.loc[0, "user_id"] = "U999"
        self.assert_contract_error(
            "orders.user_fk",
            lambda: CONTRACTS.build_order_mart(self.users, orders, self.items),
        )

    def test_mart_rejects_total_that_disagrees_with_items(self) -> None:
        orders = self.orders.copy()
        orders.loc[0, "amount_rub"] = "1200.01"
        self.assert_contract_error(
            "orders.items_reconcile",
            lambda: CONTRACTS.build_order_mart(self.users, orders, self.items),
        )

    def test_daily_metrics_preserve_order_partition(self) -> None:
        mart = CONTRACTS.build_order_mart(self.users, self.orders, self.items)
        metrics = CONTRACTS.build_daily_metrics(mart)
        self.assertEqual(int(metrics["order_count"].sum()), len(mart))
        self.assertEqual(int(metrics["paid_order_count"].sum()), 7)

    def test_cli_returns_machine_readable_failure(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ("users.csv", "orders.csv", "order_items.csv"):
                (target / name).write_bytes((DATA / name).read_bytes())
            orders = pd.read_csv(target / "orders.csv", dtype=str)
            orders.loc[0, "status"] = "complete"
            orders.to_csv(target / "orders.csv", index=False)
            result = subprocess.run(
                [sys.executable, ARTIFACT, "--data-dir", target],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["error"]["check_id"], "orders.status_domain")
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
