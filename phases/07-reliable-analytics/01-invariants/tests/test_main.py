from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "invariant_gate.py"
TINY = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("invariant_gate", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def load_tiny() -> tuple[list[dict[str, str]], list[str]]:
    with TINY.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class InvariantGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rows, self.fieldnames = load_tiny()

    def test_valid_batch_passes_and_reconciles_independent_control(self) -> None:
        report = GATE.evaluate_orders(self.rows, self.fieldnames)
        self.assertTrue(report["valid"])
        self.assertEqual(report["summary"]["order_count"], 10)
        self.assertEqual(report["summary"]["paid_order_count"], 7)
        self.assertEqual(report["summary"]["paid_revenue_rub"], "9150.50")
        self.assertEqual(report["summary"], report["control_summary"])

    def test_duplicate_order_id_breaks_grain(self) -> None:
        rows = deepcopy(self.rows)
        rows.append(deepcopy(rows[0]))
        report = GATE.evaluate_orders(rows, self.fieldnames)
        check = next(item for item in report["checks"] if item["id"] == "order_id_unique")
        self.assertFalse(check["valid"])
        self.assertEqual(check["sample"], ["O001"])
        self.assertIsNone(report["summary"])

    def test_blank_business_key_is_rejected(self) -> None:
        rows = deepcopy(self.rows)
        rows[0]["user_id"] = ""
        report = GATE.evaluate_orders(rows, self.fieldnames)
        check = next(item for item in report["checks"] if item["id"] == "keys_not_blank")
        self.assertFalse(check["valid"])
        self.assertEqual(check["sample"], [2])

    def test_unknown_status_is_not_silently_excluded_from_revenue(self) -> None:
        rows = deepcopy(self.rows)
        rows[0]["status"] = "complete"
        report = GATE.evaluate_orders(rows, self.fieldnames)
        check = next(item for item in report["checks"] if item["id"] == "status_domain")
        self.assertFalse(check["valid"])
        self.assertEqual(check["sample"][0]["value"], "complete")

    def test_amount_requires_non_negative_money_precision(self) -> None:
        for value, reason in [("-1.00", "negative"), ("1.001", "fractional")]:
            with self.subTest(value=value):
                rows = deepcopy(self.rows)
                rows[0]["amount_rub"] = value
                report = GATE.evaluate_orders(rows, self.fieldnames)
                check = next(item for item in report["checks"] if item["id"] == "amount_domain")
                self.assertFalse(check["valid"])
                self.assertIn(reason, check["sample"][0]["reason"])

    def test_naive_timestamp_is_rejected(self) -> None:
        rows = deepcopy(self.rows)
        rows[0]["ordered_at"] = "2026-06-08T09:10:00"
        report = GATE.evaluate_orders(rows, self.fieldnames)
        check = next(item for item in report["checks"] if item["id"] == "timestamp_timezone")
        self.assertFalse(check["valid"])
        self.assertIn("timezone", check["sample"][0]["reason"])

    def test_missing_column_stops_before_summary(self) -> None:
        rows = [
            {key: value for key, value in row.items() if key != "currency"} for row in self.rows
        ]
        fieldnames = [name for name in self.fieldnames if name != "currency"]
        report = GATE.evaluate_orders(rows, fieldnames)
        self.assertFalse(report["valid"])
        self.assertEqual(report["checks"][0]["sample"], ["currency"])
        self.assertIsNone(report["summary"])

    def test_summary_checks_expose_algebraic_mismatch(self) -> None:
        primary = {
            "order_count": 2,
            "paid_order_count": 1,
            "total_amount_kopecks": 200,
            "paid_revenue_kopecks": 150,
            "status_counts": {"paid": 1, "pending": 1},
        }
        control = {**primary, "paid_revenue_kopecks": 100}
        checks = GATE.summary_checks(primary, control)
        revenue = next(item for item in checks if item["id"] == "paid_revenue_reconciles")
        self.assertFalse(revenue["valid"])
        self.assertEqual(revenue["expected"], 100)
        self.assertEqual(revenue["observed"], 150)

    def test_cli_writes_report_and_blocks_invalid_batch(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = deepcopy(self.rows)
            invalid.append(deepcopy(invalid[0]))
            input_path = root / "orders.csv"
            output_path = root / "report.json"
            write_csv(input_path, invalid, self.fieldnames)
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--input",
                    input_path,
                    "--output",
                    output_path,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(json.loads(result.stdout)["valid"])
            self.assertEqual(json.loads(result.stdout), json.loads(output_path.read_text()))


if __name__ == "__main__":
    unittest.main()
