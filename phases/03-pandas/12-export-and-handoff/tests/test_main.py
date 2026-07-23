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
ARTIFACT = ROOT / "outputs" / "mart_builder.py"
DATA = ROOT.parent / "data" / "tiny"
BUSINESS_TIMEZONE = "Europe/Moscow"
SPEC = importlib.util.spec_from_file_location("mart_builder", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def read_source(name: str) -> pd.DataFrame:
    return pd.read_csv(
        DATA / name,
        dtype="string",
        keep_default_na=False,
        encoding="utf-8",
    )


class MartBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.users = read_source("users.csv")
        self.orders = read_source("orders.csv")
        self.items = read_source("order_items.csv")

    def build(
        self,
        *,
        users: pd.DataFrame | None = None,
        orders: pd.DataFrame | None = None,
        items: pd.DataFrame | None = None,
    ):
        return BUILDER.build_order_mart(
            self.users if users is None else users,
            self.orders if orders is None else orders,
            self.items if items is None else items,
            business_timezone=BUSINESS_TIMEZONE,
        )

    @staticmethod
    def source_paths() -> dict[str, Path]:
        return {
            "users": DATA / "users.csv",
            "orders": DATA / "orders.csv",
            "order_items": DATA / "order_items.csv",
        }

    def export(self, output: Path):
        mart, quality = self.build()
        return BUILDER.export_delivery(
            mart,
            quality,
            output,
            self.source_paths(),
            business_timezone=BUSINESS_TIMEZONE,
        )

    def test_mart_has_declared_grain_columns_and_order(self) -> None:
        mart, quality = self.build()
        self.assertEqual(len(mart), len(self.orders))
        self.assertTrue(mart["order_id"].is_unique)
        self.assertEqual(mart["order_id"].tolist(), sorted(mart["order_id"]))
        self.assertEqual(mart.columns.tolist(), BUILDER.OUTPUT_COLUMNS)
        self.assertEqual(quality["checks"]["grain"]["status"], "pass")

    def test_item_detail_is_aggregated_before_join(self) -> None:
        mart, _ = self.build()
        row = mart.loc[mart["order_id"] == "O1001"].iloc[0]
        self.assertEqual(row["item_rows"], 2)
        self.assertEqual(row["item_total"], 1200)
        self.assertEqual(row["categories"], "add_on")

    def test_unknown_user_is_preserved_and_reported(self) -> None:
        mart, quality = self.build()
        row = mart.loc[mart["order_id"] == "O1005"].iloc[0]
        self.assertFalse(row["user_found"])
        self.assertTrue(pd.isna(row["plan"]))
        check = quality["checks"]["unknown_users"]
        self.assertEqual(check["status"], "warning")
        self.assertEqual(check["count"], 1)
        self.assertEqual(check["examples"], ["U999"])

    def test_types_vocabulary_and_business_date_are_explicit(self) -> None:
        mart, _ = self.build()
        self.assertEqual(str(mart["ordered_at_utc"].dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(mart["amount"].dtype), "Float64")
        self.assertEqual(str(mart["item_rows"].dtype), "Int64")
        self.assertEqual(str(mart["user_found"].dtype), "boolean")
        self.assertEqual(mart["status"].cat.categories.tolist(), BUILDER.STATUS_CATEGORIES)
        self.assertEqual(mart["plan"].cat.categories.tolist(), BUILDER.PLAN_CATEGORIES)
        first = mart.loc[mart["order_id"] == "O1001"].iloc[0]
        self.assertEqual(first["local_order_date"], "2026-02-01")
        self.assertIn("KZ", mart["country"].dropna().tolist())

    def test_reconciliation_distinguishes_mismatch_from_not_checked(self) -> None:
        mart, quality = self.build()
        self.assertTrue(mart["amount_matches_items"].dropna().all())
        check = quality["checks"]["amount_reconciliation"]
        self.assertEqual(check["status"], "warning")
        self.assertEqual(check["mismatches"], 0)
        self.assertEqual(check["unchecked_rows"], 1)
        self.assertEqual(check["examples"], ["O1004"])
        self.assertEqual(quality["publish_status"], "passed_with_warnings")

    def test_sources_are_not_mutated(self) -> None:
        users = self.users.copy(deep=True)
        orders = self.orders.copy(deep=True)
        items = self.items.copy(deep=True)
        self.build()
        pd.testing.assert_frame_equal(self.users, users)
        pd.testing.assert_frame_equal(self.orders, orders)
        pd.testing.assert_frame_equal(self.items, items)

    def test_duplicate_or_blank_order_id_is_blocked(self) -> None:
        duplicate = pd.concat([self.orders, self.orders.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(BUILDER.MartContractError, "not unique"):
            self.build(orders=duplicate)
        blank = self.orders.copy()
        blank.loc[0, "order_id"] = "   "
        with self.assertRaisesRegex(BUILDER.MartContractError, "non-missing"):
            self.build(orders=blank)

    def test_invalid_amount_is_not_silently_converted_to_missing(self) -> None:
        broken = self.orders.copy()
        broken.loc[0, "amount"] = "oops"
        with self.assertRaisesRegex(BUILDER.MartContractError, "invalid numeric"):
            self.build(orders=broken)

    def test_unknown_or_missing_status_is_blocked(self) -> None:
        unknown = self.orders.copy()
        unknown.loc[0, "status"] = "delivered"
        with self.assertRaisesRegex(BUILDER.MartContractError, "unknown categories"):
            self.build(orders=unknown)
        missing = self.orders.copy()
        missing.loc[0, "status"] = ""
        with self.assertRaisesRegex(BUILDER.MartContractError, "non-missing"):
            self.build(orders=missing)

    def test_naive_or_invalid_timestamp_is_blocked(self) -> None:
        naive = self.orders.copy()
        naive.loc[0, "ordered_at"] = "2024-01-15 10:00:00"
        with self.assertRaisesRegex(BUILDER.MartContractError, "explicit UTC offset"):
            self.build(orders=naive)
        invalid = self.orders.copy()
        invalid.loc[0, "ordered_at"] = "not-a-date"
        with self.assertRaisesRegex(BUILDER.MartContractError, "invalid timestamps"):
            self.build(orders=invalid)

    def test_paid_order_without_amount_is_blocked(self) -> None:
        broken = self.orders.copy()
        broken.loc[0, "amount"] = ""
        with self.assertRaisesRegex(BUILDER.MartContractError, "paid orders need amount"):
            self.build(orders=broken)

    def test_orphan_item_and_order_without_items_are_blocked(self) -> None:
        orphan = self.items.copy()
        orphan.loc[0, "order_id"] = "UNKNOWN"
        with self.assertRaisesRegex(BUILDER.MartContractError, "unknown orders"):
            self.build(items=orphan)
        missing = self.items.loc[self.items["order_id"] != "O1007"].copy()
        with self.assertRaisesRegex(BUILDER.MartContractError, "no item rows"):
            self.build(items=missing)

    def test_known_amount_mismatch_is_a_publish_blocker(self) -> None:
        broken = self.items.copy()
        broken.loc[broken["order_id"] == "O1001", "unit_price"] = "1"
        with self.assertRaisesRegex(BUILDER.MartContractError, "differs from item total"):
            self.build(items=broken)

    def test_manifest_versions_parameters_quality_and_sources_are_declared(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = self.export(output)
            stored = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest, stored)
            self.assertEqual(manifest["manifest_version"], 1)
            self.assertEqual(manifest["dataset_schema_version"], "order_mart/v1")
            self.assertEqual(manifest["parameters"]["business_timezone"], BUSINESS_TIMEZONE)
            self.assertEqual(manifest["publish_status"], "passed_with_warnings")
            self.assertEqual(manifest["dataset"]["grain"], ["order_id"])
            self.assertEqual(manifest["dataset"]["rows"], 7)
            self.assertEqual(set(manifest["sources"]), set(BUILDER.SOURCE_NAMES))
            self.assertEqual(
                manifest["artifact"]["sha256"],
                BUILDER.sha256(output / "order_mart.csv"),
            )

    def test_export_is_deterministic_for_same_inputs(self) -> None:
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            first_manifest = self.export(Path(first))
            second_manifest = self.export(Path(second))
            self.assertEqual(
                (Path(first) / "order_mart.csv").read_bytes(),
                (Path(second) / "order_mart.csv").read_bytes(),
            )
            self.assertEqual(first_manifest, second_manifest)

    def test_recipient_verifier_accepts_untouched_package(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            manifest = self.export(output)
            report = BUILDER.verify_delivery(output)
            self.assertTrue(report["valid"])
            self.assertEqual(report["rows"], 7)
            self.assertEqual(report["artifact_sha256"], manifest["artifact"]["sha256"])

    def test_recipient_verifier_rejects_changed_csv(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            self.export(output)
            with (output / "order_mart.csv").open("a", encoding="utf-8") as stream:
                stream.write("changed\n")
            with self.assertRaisesRegex(BUILDER.MartContractError, "checksum mismatch"):
                BUILDER.verify_delivery(output)

    def test_recipient_verifier_rejects_manifest_with_wrong_rows(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            self.export(output)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dataset"]["rows"] = 999
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(BUILDER.MartContractError, "row count"):
                BUILDER.verify_delivery(output)

    def test_recipient_verifier_rejects_changed_grain_or_schema(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            self.export(output)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dataset"]["grain"] = ["user_id"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(BUILDER.MartContractError, "grain"):
                BUILDER.verify_delivery(output)

        with TemporaryDirectory() as directory:
            output = Path(directory)
            self.export(output)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dataset"]["schema"][0]["logical_type"] = "integer"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(BUILDER.MartContractError, "schema"):
                BUILDER.verify_delivery(output)

    def test_export_rejects_quality_report_for_another_mart(self) -> None:
        mart, quality = self.build()
        quality["checks"]["grain"]["rows"] = 999
        with (
            TemporaryDirectory() as directory,
            self.assertRaisesRegex(BUILDER.MartContractError, "grain check"),
        ):
            BUILDER.export_delivery(
                mart,
                quality,
                Path(directory),
                self.source_paths(),
                business_timezone=BUSINESS_TIMEZONE,
            )

    def test_cli_build_and_verify_the_same_delivery(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory)
            build = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "build",
                    "--users",
                    str(DATA / "users.csv"),
                    "--orders",
                    str(DATA / "orders.csv"),
                    "--items",
                    str(DATA / "order_items.csv"),
                    "--output-dir",
                    str(output),
                    "--business-timezone",
                    BUSINESS_TIMEZONE,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertEqual(json.loads(build.stdout)["rows"], 7)
            verify = subprocess.run(
                [
                    sys.executable,
                    str(ARTIFACT),
                    "verify",
                    "--output-dir",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertTrue(json.loads(verify.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
