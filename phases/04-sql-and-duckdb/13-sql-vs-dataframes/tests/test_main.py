from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "sql_mart_builder.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("sql_mart_builder", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class SqlMartBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.result = BUILDER.build_marts(
            DATA / "users.csv",
            DATA / "orders.csv",
            DATA / "order_items.csv",
        )
        self.orders = {row["order_id"]: row for row in self.result["order_mart"]["records"]}
        self.users = {row["user_id"]: row for row in self.result["user_summary"]["records"]}

    def test_order_mart_preserves_order_grain(self) -> None:
        self.assertEqual(self.result["order_mart"]["grain"], ["order_id"])
        self.assertEqual(self.result["checks"]["order_rows"], 12)
        self.assertTrue(self.result["checks"]["order_id_unique"])

    def test_items_are_aggregated_before_join(self) -> None:
        row = self.orders["O1001"]
        self.assertEqual(row["item_rows"], 2)
        self.assertEqual(row["item_total"], 1200.0)
        self.assertEqual(row["categories"], "add_on|subscription")

    def test_unknown_user_is_preserved_and_flagged(self) -> None:
        self.assertFalse(self.orders["O1010"]["user_found"])
        self.assertEqual(self.result["checks"]["unknown_user_orders"], 1)

    def test_amount_reconciliation_is_explicit(self) -> None:
        self.assertEqual(self.result["checks"]["amount_item_mismatches"], 0)
        self.assertEqual(self.result["checks"]["amount_item_unchecked"], 2)

    def test_paid_revenue_matches_phase_controls(self) -> None:
        self.assertEqual(self.result["checks"]["paid_revenue"], 5005.0)
        self.assertTrue(self.result["checks"]["valid"])

    def test_user_summary_has_one_row_per_observed_user(self) -> None:
        self.assertEqual(self.result["user_summary"]["grain"], ["user_id"])
        self.assertEqual(self.result["checks"]["user_summary_rows"], 8)
        self.assertEqual(self.users["U001"]["paid_revenue"], 2700.0)
        self.assertEqual(self.users["U001"]["paid_order_count"], 2)

    def test_boundary_assigns_relational_work_to_sql(self) -> None:
        self.assertIn("joins", self.result["boundary"]["sql"])
        self.assertIn("manifest", self.result["boundary"]["python"])

    def test_export_manifest_matches_artifact_checksum(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = BUILDER.export_marts(
                self.result,
                output,
                {
                    "users": DATA / "users.csv",
                    "orders": DATA / "orders.csv",
                    "order_items": DATA / "order_items.csv",
                },
            )
            digest = hashlib.sha256((output / "order_mart.csv").read_bytes()).hexdigest()
            self.assertEqual(manifest["artifacts"]["order_mart"]["sha256"], digest)
            self.assertTrue((output / "user_summary.csv").is_file())
            self.assertTrue((output / "manifest.json").is_file())

    def test_cli_builds_delivery_directory(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
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
                    "--output-dir",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads(result.stdout)
            self.assertTrue(manifest["checks"]["valid"])
            self.assertEqual(
                set(path.name for path in output.iterdir()),
                {
                    "manifest.json",
                    "order_mart.csv",
                    "user_summary.csv",
                },
            )


if __name__ == "__main__":
    unittest.main()
