from __future__ import annotations

import csv
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


class SqlMartBuilderTest(unittest.TestCase):
    def build_tiny(self, output: Path) -> dict:
        return BUILDER.build_package(
            DATA / "users.csv",
            DATA / "orders.csv",
            DATA / "order_items.csv",
            output,
        )

    def test_tiny_controls_and_exact_decimal_reconciliation(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            manifest = self.build_tiny(output)
            quality = manifest["quality"]
            self.assertTrue(quality["valid"])
            self.assertEqual(quality["marts"]["order_rows"], 12)
            expected = {
                "EUR": "1625.00",
                "KZT": "500.00",
                "RUB": "2700.00",
                "USD": "180.00",
            }
            self.assertEqual(
                quality["marts"]["order_paid_revenue_by_currency"],
                expected,
            )
            self.assertEqual(
                quality["marts"]["summary_paid_revenue_by_currency"],
                expected,
            )
            self.assertTrue(quality["marts"]["paid_revenue_reconciled_by_currency"])

    def test_order_mart_preserves_orders_and_preaggregates_items(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            manifest = self.build_tiny(output)
            orders = {row["order_id"]: row for row in read_csv(output / "order_mart.csv")}
            self.assertEqual(len(orders), 12)
            self.assertEqual(orders["O1001"]["item_rows"], "2")
            self.assertEqual(orders["O1001"]["item_total"], "1200.00")
            self.assertEqual(
                orders["O1001"]["categories"],
                "add_on|subscription",
            )
            self.assertEqual(
                manifest["quality"]["source"]["order_items_rows"],
                14,
            )

    def test_allowed_incompleteness_is_visible_as_warnings(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            manifest = self.build_tiny(output)
            orders = {row["order_id"]: row for row in read_csv(output / "order_mart.csv")}
            self.assertEqual(orders["O1010"]["user_found"], "false")
            self.assertEqual(
                manifest["quality"]["warnings"],
                [
                    "unknown_user_orders=1",
                    "missing_business_dates=1",
                    "amount_item_unchecked=2",
                ],
            )

    def test_user_summary_has_one_row_per_user_and_currency(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            manifest = self.build_tiny(output)
            users = {
                (row["user_id"], row["currency"]): row
                for row in read_csv(output / "user_summary.csv")
            }
            self.assertEqual(manifest["quality"]["marts"]["user_summary_rows"], 9)
            self.assertEqual(users[("U001", "RUB")]["paid_revenue"], "2700.00")
            self.assertEqual(users[("U001", "RUB")]["paid_order_count"], "2")

    def test_validity_depends_on_invariants_not_tiny_control_values(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            orders = read_csv(DATA / "orders.csv")[:3]
            kept_order_ids = {row["order_id"] for row in orders}
            items = [
                row
                for row in read_csv(DATA / "order_items.csv")
                if row["order_id"] in kept_order_ids
            ]
            orders_path = root / "orders.csv"
            items_path = root / "items.csv"
            write_csv(orders_path, orders)
            write_csv(items_path, items)
            output = root / "delivery"

            manifest = BUILDER.build_package(
                DATA / "users.csv",
                orders_path,
                items_path,
                output,
            )

            self.assertTrue(manifest["quality"]["valid"])
            self.assertEqual(manifest["quality"]["marts"]["order_rows"], 3)
            self.assertNotEqual(
                manifest["quality"]["marts"]["order_paid_revenue_by_currency"],
                {
                    "EUR": "1625.00",
                    "KZT": "500.00",
                    "RUB": "2700.00",
                    "USD": "180.00",
                },
            )

    def test_duplicate_order_key_blocks_publication(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rows = read_csv(DATA / "orders.csv")
            rows.append(rows[0])
            orders_path = root / "orders.csv"
            write_csv(orders_path, rows)
            output = root / "delivery"

            with self.assertRaisesRegex(
                BUILDER.ContractError,
                "duplicate_order_ids=1",
            ):
                BUILDER.build_package(
                    DATA / "users.csv",
                    orders_path,
                    DATA / "order_items.csv",
                    output,
                )
            self.assertFalse(output.exists())

    def test_orphan_item_blocks_publication(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rows = read_csv(DATA / "order_items.csv")
            orphan = rows[0].copy()
            orphan.update({"order_id": "MISSING", "product_id": "P999"})
            rows.append(orphan)
            items_path = root / "items.csv"
            write_csv(items_path, rows)

            with self.assertRaisesRegex(
                BUILDER.ContractError,
                "orphan_item_order_ids=1",
            ):
                BUILDER.build_package(
                    DATA / "users.csv",
                    DATA / "orders.csv",
                    items_path,
                    root / "delivery",
                )

    def test_amount_mismatch_blocks_publication(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rows = read_csv(DATA / "order_items.csv")
            rows[0]["unit_price"] = "1.00"
            items_path = root / "items.csv"
            write_csv(items_path, rows)

            with self.assertRaisesRegex(
                BUILDER.ContractError,
                "amount_item_mismatches=1",
            ):
                BUILDER.build_package(
                    DATA / "users.csv",
                    DATA / "orders.csv",
                    items_path,
                    root / "delivery",
                )

    def test_paid_order_without_amount_blocks_publication(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rows = read_csv(DATA / "orders.csv")
            rows[0]["amount"] = ""
            orders_path = root / "orders.csv"
            write_csv(orders_path, rows)

            with self.assertRaisesRegex(
                BUILDER.ContractError,
                "paid_orders_missing_amount=1",
            ):
                BUILDER.build_package(
                    DATA / "users.csv",
                    orders_path,
                    DATA / "order_items.csv",
                    root / "delivery",
                )

    def test_package_contains_sql_decision_and_portable_provenance(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            manifest = self.build_tiny(output)
            decision = json.loads((output / "boundary_decision.json").read_text(encoding="utf-8"))
            self.assertEqual(
                set(
                    path.relative_to(output).as_posix()
                    for path in output.rglob("*")
                    if path.is_file()
                ),
                set(BUILDER.PACKAGE_ARTIFACTS) | {"manifest.json"},
            )
            self.assertEqual(
                decision["evidence"]["dataframes_materialized_during_build"],
                0,
            )
            self.assertEqual(
                decision["evidence"]["handoff_grain"],
                ["user_id", "currency"],
            )
            encoded = json.dumps(manifest, ensure_ascii=False)
            self.assertNotIn(str(DATA.resolve()), encoded)
            self.assertEqual(manifest["sources"]["orders"]["name"], "orders.csv")

    def test_package_is_deterministic_and_verifies_from_receiver_side(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            self.build_tiny(first)
            self.build_tiny(second)
            for relative_path in (*BUILDER.PACKAGE_ARTIFACTS, "manifest.json"):
                self.assertEqual(
                    (first / relative_path).read_bytes(),
                    (second / relative_path).read_bytes(),
                )
            self.assertEqual(
                BUILDER.verify_package(first),
                {"valid": True, "errors": [], "verified_artifacts": 5},
            )

    def test_verifier_detects_tampered_csv(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            self.build_tiny(output)
            with (output / "order_mart.csv").open("a", encoding="utf-8") as target:
                target.write("tampered\n")

            result = BUILDER.verify_package(output)

            self.assertFalse(result["valid"])
            self.assertIn("checksum mismatch: order_mart.csv", result["errors"])

    def test_verifier_rejects_manifest_path_traversal(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            self.build_tiny(output)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifacts"][0]["path"] = "../outside.txt"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = BUILDER.verify_package(output)

            self.assertFalse(result["valid"])
            self.assertIn("unsafe artifact path: ../outside.txt", result["errors"])

    def test_verifier_rejects_undeclared_file(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            self.build_tiny(output)
            (output / "stale.csv").write_text("old\n", encoding="utf-8")

            result = BUILDER.verify_package(output)

            self.assertFalse(result["valid"])
            self.assertIn(
                "package files do not match the declared inventory",
                result["errors"],
            )

    def test_existing_output_directory_is_not_reused(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            output.mkdir()
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                self.build_tiny(output)

    def test_cli_build_and_verify(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "delivery"
            build = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "build",
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
            verify = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "verify",
                    "--package-dir",
                    output,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(build.returncode, 0, build.stderr)
            self.assertTrue(json.loads(build.stdout)["quality"]["valid"])
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertTrue(json.loads(verify.stdout)["valid"])

    def test_cli_reports_missing_source_without_traceback(self) -> None:
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "build",
                    "--users",
                    Path(directory) / "missing.csv",
                    "--orders",
                    DATA / "orders.csv",
                    "--items",
                    DATA / "order_items.csv",
                    "--output-dir",
                    Path(directory) / "delivery",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("users source is not a file", result.stderr)
            self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
