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
ARTIFACT = ROOT / "outputs" / "dataframe_contract.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("dataframe_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


def check(report, check_id: str):
    return next(item for item in report["checks"] if item["id"] == check_id)


class DataFrameContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.frames = CONTRACT.load_frames(DATA)

    def test_valid_baseline_passes_versioned_contract(self) -> None:
        report = CONTRACT.validate_frames(self.frames)
        self.assertTrue(report["valid"])
        self.assertEqual(report["contract_version"], "1.0.0")
        self.assertEqual(report["row_counts"], {"users": 6, "orders": 10, "order_items": 12})

    def test_lazy_validation_collects_multiple_order_failures(self) -> None:
        self.frames["orders"].loc[0, "status"] = "complete"
        self.frames["orders"].loc[1, "amount_rub"] = "-1.001"
        report = CONTRACT.validate_frames(self.frames)
        failures = check(report, "schema.orders")["failure_cases"]
        self.assertFalse(report["valid"])
        self.assertGreaterEqual(len(failures), 2)
        self.assertEqual({item["column"] for item in failures}, {"status", "amount_rub"})

    def test_strict_schema_rejects_missing_and_extra_columns(self) -> None:
        self.frames["orders"] = self.frames["orders"].drop(columns=["currency"]).assign(extra="x")
        report = CONTRACT.validate_frames(self.frames)
        failures = check(report, "schema.orders")["failure_cases"]
        observed = {item["failure_case"] for item in failures}
        self.assertIn("currency", observed)
        self.assertIn("extra", observed)

    def test_relationship_check_rejects_orphan_user(self) -> None:
        self.frames["orders"].loc[0, "user_id"] = "U999"
        report = CONTRACT.validate_frames(self.frames)
        relation = check(report, "orders.user_fk")
        self.assertFalse(relation["passed"])
        self.assertEqual(relation["failure_cases"], ["U999"])

    def test_reconciliation_is_separate_from_dataframe_shape(self) -> None:
        self.frames["order_items"].loc[0, "unit_price_rub"] = "700.01"
        report = CONTRACT.validate_frames(self.frames)
        self.assertTrue(check(report, "schema.order_items")["passed"])
        self.assertEqual(check(report, "orders.items_reconcile")["failure_cases"], ["O001"])

    def test_cli_returns_nonzero_and_full_report(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory)
            for name, frame in self.frames.items():
                frame.to_csv(target / f"{name}.csv", index=False)
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
            self.assertFalse(json.loads(result.stdout)["valid"])
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
