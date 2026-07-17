from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

LESSON_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = LESSON_ROOT / "outputs" / "revenue_summary.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("revenue_summary_test", ARTIFACT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the lesson artifact")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RevenueSummaryTest(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = load_artifact()

    def write_sample(self, directory: str, content: str) -> Path:
        path = Path(directory) / "orders.csv"
        path.write_text(content, encoding="utf-8")
        return path

    def test_course_sample_has_expected_paid_revenue(self) -> None:
        with TemporaryDirectory() as directory:
            sample = self.write_sample(
                directory,
                "order_id,order_date,status,amount\n"
                "TEST-001,2026-01-10,paid,120\n"
                "TEST-002,2026-01-10,pending,80\n"
                "TEST-003,2026-01-11,paid,75\n",
            )
            result = self.artifact.summarize_paid_orders(sample)

        self.assertEqual(
            result,
            {
                "paid_order_count": 2,
                "revenue": 195.0,
                "average_paid_order": 97.5,
            },
        )

    def test_missing_column_is_reported(self) -> None:
        with TemporaryDirectory() as directory:
            sample = self.write_sample(directory, "order_id,status\n1,paid\n")

            with self.assertRaisesRegex(ValueError, "amount"):
                self.artifact.summarize_paid_orders(sample)

    def test_invalid_paid_amount_names_source_row(self) -> None:
        with TemporaryDirectory() as directory:
            sample = self.write_sample(
                directory,
                "order_id,status,amount\n1,paid,not-a-number\n",
            )

            with self.assertRaisesRegex(ValueError, "row 2"):
                self.artifact.summarize_paid_orders(sample)

    def test_file_without_paid_orders_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            sample = self.write_sample(
                directory,
                "order_id,status,amount\n1,pending,80\n",
            )

            with self.assertRaisesRegex(ValueError, "no paid orders"):
                self.artifact.summarize_paid_orders(sample)

    def test_cli_prints_json(self) -> None:
        with TemporaryDirectory() as directory:
            sample = self.write_sample(
                directory,
                "order_id,status,amount\n1,paid,10.5\n2,paid,20\n",
            )
            result = subprocess.run(
                [sys.executable, str(ARTIFACT_PATH), str(sample)],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            json.loads(result.stdout),
            {
                "paid_order_count": 2,
                "revenue": 30.5,
                "average_paid_order": 15.25,
            },
        )
