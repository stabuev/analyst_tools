from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "mart_builder.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("mart_builder", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class MartBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.users = pd.read_csv(DATA / "users.csv")
        self.orders = pd.read_csv(DATA / "orders.csv")
        self.items = pd.read_csv(DATA / "order_items.csv")

    def build(self):
        return BUILDER.build_order_mart(self.users, self.orders, self.items)

    def test_mart_has_one_row_per_order(self) -> None:
        mart, checks = self.build()
        self.assertEqual(len(mart), len(self.orders))
        self.assertTrue(mart["order_id"].is_unique)
        self.assertTrue(checks["grain_unique"])

    def test_item_detail_is_aggregated_before_join(self) -> None:
        mart, _ = self.build()
        row = mart.loc[mart["order_id"] == "O1001"].iloc[0]
        self.assertEqual(row["item_rows"], 2)
        self.assertEqual(row["item_total"], 1200)

    def test_unknown_user_is_preserved_and_flagged(self) -> None:
        mart, checks = self.build()
        row = mart.loc[mart["order_id"] == "O1005"].iloc[0]
        self.assertFalse(row["user_found"])
        self.assertEqual(checks["unknown_users"], 1)

    def test_text_and_status_are_normalized(self) -> None:
        mart, _ = self.build()
        self.assertIn("KZ", mart["country"].dropna().tolist())
        self.assertNotIn(" paid ", mart["status"].tolist())

    def test_amount_consistency_is_checked(self) -> None:
        mart, checks = self.build()
        self.assertTrue(mart["amount_matches_items"].dropna().all())
        self.assertEqual(checks["amount_item_mismatches"], 0)
        self.assertEqual(checks["amount_item_unchecked"], 1)
        self.assertEqual(checks["missing_amount"], 1)

    def test_sources_are_not_mutated(self) -> None:
        users = self.users.copy(deep=True)
        orders = self.orders.copy(deep=True)
        items = self.items.copy(deep=True)
        self.build()
        pd.testing.assert_frame_equal(self.users, users)
        pd.testing.assert_frame_equal(self.orders, orders)
        pd.testing.assert_frame_equal(self.items, items)

    def test_duplicate_order_is_rejected(self) -> None:
        broken = pd.concat([self.orders, self.orders.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(BUILDER.MartContractError, "not unique"):
            BUILDER.build_order_mart(self.users, broken, self.items)

    def test_orphan_item_order_is_rejected(self) -> None:
        broken = self.items.copy()
        broken.loc[0, "order_id"] = "UNKNOWN"
        with self.assertRaisesRegex(BUILDER.MartContractError, "unknown orders"):
            BUILDER.build_order_mart(self.users, self.orders, broken)

    def test_export_manifest_matches_csv_checksum(self) -> None:
        mart, checks = self.build()
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = BUILDER.export_mart(
                mart,
                checks,
                output,
                {
                    "users": DATA / "users.csv",
                    "orders": DATA / "orders.csv",
                    "order_items": DATA / "order_items.csv",
                },
            )
            digest = hashlib.sha256((output / "order_mart.csv").read_bytes()).hexdigest()
            self.assertEqual(manifest["artifact"]["sha256"], digest)
            self.assertEqual(
                json.loads((output / "manifest.json").read_text())["grain"],
                ["order_id"],
            )

    def test_cli_builds_both_delivery_files(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
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
            self.assertTrue((output / "order_mart.csv").is_file())
            self.assertTrue((output / "manifest.json").is_file())
            self.assertEqual(json.loads(result.stdout)["rows"], 7)


if __name__ == "__main__":
    unittest.main()
