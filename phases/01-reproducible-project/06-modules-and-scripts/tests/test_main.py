from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


PROJECT = (
    Path(__file__).resolve().parents[1] / "outputs" / "order_metrics_project"
)
SRC = PROJECT / "src"
sys.path.insert(0, str(SRC))

from order_metrics import (  # noqa: E402
    DataContractError,
    Order,
    load_orders,
    summarize_orders,
)
from order_metrics.core import parse_orders  # noqa: E402


class OrderMetricsTest(unittest.TestCase):
    def test_parse_and_summarize_valid_orders(self) -> None:
        rows = csv.DictReader(io.StringIO("order_id,amount\nA,10.20\nB,20.30\n"))

        summary = summarize_orders(parse_orders(rows))

        self.assertEqual(summary["orders"], 2)
        self.assertEqual(summary["revenue"], Decimal("30.50"))
        self.assertEqual(summary["average_order_value"], Decimal("15.25"))

    def test_duplicate_order_id_is_rejected(self) -> None:
        rows = [
            {"order_id": "A", "amount": "10"},
            {"order_id": "A", "amount": "20"},
        ]

        with self.assertRaisesRegex(DataContractError, "duplicate order_id A"):
            parse_orders(rows)

    def test_invalid_or_negative_amount_is_rejected(self) -> None:
        for amount in ("not-a-number", "-0.01", "NaN"):
            with self.subTest(amount=amount):
                with self.assertRaises(DataContractError):
                    parse_orders([{"order_id": "A", "amount": amount}])

    def test_empty_input_is_rejected(self) -> None:
        with self.assertRaisesRegex(DataContractError, "no orders"):
            parse_orders([])

    def test_missing_csv_columns_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "orders.csv"
            source.write_text("id,value\nA,10\n", encoding="utf-8")

            with self.assertRaisesRegex(DataContractError, "missing CSV columns"):
                load_orders(source)

    def test_core_function_accepts_objects_without_file_io(self) -> None:
        summary = summarize_orders(
            [
                Order("A", Decimal("1.10")),
                Order("B", Decimal("2.20")),
            ]
        )

        self.assertEqual(summary["revenue"], Decimal("3.30"))

    def test_module_cli_prints_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "order_metrics",
                str(PROJECT / "data" / "orders.csv"),
            ],
            check=False,
            capture_output=True,
            text=True,
            env=os.environ | {"PYTHONPATH": str(SRC)},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["average_order_value"], "100.00")

    def test_module_cli_returns_nonzero_for_bad_input(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "order_metrics", "/missing/orders.csv"],
            check=False,
            capture_output=True,
            text=True,
            env=os.environ | {"PYTHONPATH": str(SRC)},
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("does not exist", result.stderr)


if __name__ == "__main__":
    unittest.main()
