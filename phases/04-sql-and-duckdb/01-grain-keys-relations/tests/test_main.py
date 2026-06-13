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
ARTIFACT = ROOT / "outputs" / "grain_key_audit.py"
DATA_ROOT = ROOT.parent / "data"
TINY = DATA_ROOT / "tiny"
CONTRACT = DATA_ROOT / "contract.json"
SPEC = importlib.util.spec_from_file_location("grain_key_audit", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class GrainKeyAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = AUDITOR.audit_dataset(TINY, CONTRACT)

    def test_unique_users_key_passes(self) -> None:
        key = self.report["tables"]["users"]["primary_key"]
        self.assertTrue(key["valid"])
        self.assertEqual(key["null_key_rows"], 0)
        self.assertEqual(key["duplicate_groups"], 0)

    def test_duplicate_event_delivery_is_visible(self) -> None:
        key = self.report["tables"]["events"]["primary_key"]
        self.assertFalse(key["valid"])
        self.assertEqual(key["duplicate_groups"], 1)
        self.assertEqual(key["duplicate_key_rows"], 2)
        self.assertEqual(key["sample_duplicates"][0]["event_id"], "E0005")

    def test_composite_order_item_key_passes(self) -> None:
        key = self.report["tables"]["order_items"]["primary_key"]
        self.assertEqual(key["columns"], ["order_id", "product_id"])
        self.assertTrue(key["valid"])

    def test_unknown_order_user_is_reported_as_orphan(self) -> None:
        relationship = next(
            item for item in self.report["relationships"] if item["child_table"] == "orders"
        )
        self.assertFalse(relationship["valid"])
        self.assertEqual(relationship["orphan_keys"], 1)
        self.assertEqual(relationship["orphan_rows"], 1)
        self.assertEqual(relationship["sample_orphans"][0]["user_id"], "U999")

    def test_order_items_to_orders_relationship_passes(self) -> None:
        relationship = next(
            item for item in self.report["relationships"] if item["child_table"] == "order_items"
        )
        self.assertTrue(relationship["valid"])
        self.assertEqual(relationship["orphan_rows"], 0)

    def test_null_primary_key_is_invalid(self) -> None:
        with TemporaryDirectory() as directory:
            data_root = Path(directory)
            write_csv(data_root / "things.csv", [{"thing_id": ""}, {"thing_id": "T2"}])
            contract = {
                "tables": {
                    "things": {
                        "file": "things.csv",
                        "grain": "one thing",
                        "primary_key": ["thing_id"],
                        "foreign_keys": [],
                        "columns": {"thing_id": {}},
                    }
                }
            }
            contract_path = data_root / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            report = AUDITOR.audit_dataset(data_root, contract_path)

        self.assertEqual(report["tables"]["things"]["primary_key"]["null_key_rows"], 1)
        self.assertFalse(report["summary"]["valid"])

    def test_missing_declared_column_fails_without_sql_error(self) -> None:
        with TemporaryDirectory() as directory:
            data_root = Path(directory)
            write_csv(data_root / "things.csv", [{"thing_id": "T1"}])
            contract = {
                "tables": {
                    "things": {
                        "file": "things.csv",
                        "grain": "one thing",
                        "primary_key": ["thing_id", "version"],
                        "foreign_keys": [],
                        "columns": {"thing_id": {}, "version": {}},
                    }
                }
            }
            contract_path = data_root / "contract.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")

            report = AUDITOR.audit_dataset(data_root, contract_path)

        table = report["tables"]["things"]
        self.assertEqual(table["columns"]["missing"], ["version"])
        self.assertFalse(table["primary_key"]["checked"])
        self.assertFalse(table["valid"])

    def test_cli_is_a_quality_gate_by_default(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--data-dir",
                TINY,
                "--contract",
                CONTRACT,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["failed_checks"], 2)

    def test_cli_can_print_known_failures_for_learning(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--data-dir",
                TINY,
                "--contract",
                CONTRACT,
                "--allow-failures",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(json.loads(result.stdout)["summary"]["valid"])


if __name__ == "__main__":
    unittest.main()
