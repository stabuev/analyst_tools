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
ARTIFACT = ROOT / "outputs" / "sql_quality_checks.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("sql_quality_checks", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SQL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SQL)


def quality_check(report, check_id: str):
    return next(item for item in report["checks"] if item["id"] == check_id)


def copy_data(target: Path) -> None:
    for name in ("users.csv", "orders.csv", "order_items.csv"):
        (target / name).write_bytes((DATA / name).read_bytes())


class SqlQualityChecksTest(unittest.TestCase):
    def test_valid_baseline_passes_all_sql_checks(self) -> None:
        report = SQL.run_checks(DATA)
        self.assertTrue(report["valid"])
        self.assertEqual(len(report["checks"]), 8)
        self.assertEqual(report["row_counts"]["orders"], 10)

    def test_duplicate_order_is_exposed_with_sample(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory)
            copy_data(target)
            orders = pd.read_csv(target / "orders.csv", dtype=str)
            orders = pd.concat([orders, orders.iloc[[0]]], ignore_index=True)
            orders.to_csv(target / "orders.csv", index=False)
            report = SQL.run_checks(target)
        defect = quality_check(report, "orders.order_id_unique")
        self.assertEqual(defect["violation_count"], 1)
        self.assertEqual(defect["sample"][0]["order_id"], "O001")

    def test_orphan_user_fails_relationship_query(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory)
            copy_data(target)
            orders = pd.read_csv(target / "orders.csv", dtype=str)
            orders.loc[0, "user_id"] = "U999"
            orders.to_csv(target / "orders.csv", index=False)
            report = SQL.run_checks(target)
        self.assertEqual(quality_check(report, "orders.user_fk")["violation_count"], 1)

    def test_item_total_mismatch_fails_reconciliation(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory)
            copy_data(target)
            items = pd.read_csv(target / "order_items.csv", dtype=str)
            items.loc[0, "unit_price_rub"] = "700.01"
            items.to_csv(target / "order_items.csv", index=False)
            report = SQL.run_checks(target)
        mismatch = quality_check(report, "orders.items_reconcile")
        self.assertEqual(mismatch["sample"][0]["order_id"], "O001")

    def test_cli_writes_machine_readable_failure(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory)
            copy_data(target)
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
            self.assertEqual(quality_check(payload, "orders.status_domain")["violation_count"], 1)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
