from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "order_pipeline.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("order_pipeline", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
PIPELINE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PIPELINE)


class OrderPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.orders = pd.read_csv(DATA)

    def test_pipeline_preserves_order_grain(self) -> None:
        result = PIPELINE.prepare_orders(self.orders, timezone="Europe/Moscow")
        self.assertEqual(len(result), len(self.orders))
        self.assertTrue(result["order_id"].is_unique)

    def test_pipeline_normalizes_values(self) -> None:
        result = PIPELINE.prepare_orders(self.orders, timezone="Europe/Moscow")
        self.assertIn("paid", result["status"].tolist())
        self.assertNotIn(" paid ", result["status"].tolist())

    def test_pipeline_adds_nullable_metrics(self) -> None:
        result = PIPELINE.prepare_orders(self.orders, timezone="Europe/Moscow")
        self.assertEqual(str(result["amount"].dtype), "Float64")
        self.assertEqual(str(result["is_paid"].dtype), "boolean")

    def test_pipeline_adds_business_date(self) -> None:
        result = PIPELINE.prepare_orders(self.orders, timezone="Europe/Moscow")
        row = result.loc[result["order_id"] == "O1002"].iloc[0]
        self.assertEqual(str(row["local_order_date"]), "2026-02-02")

    def test_pipeline_does_not_mutate_input(self) -> None:
        original = self.orders.copy(deep=True)
        PIPELINE.prepare_orders(self.orders, timezone="Europe/Moscow")
        pd.testing.assert_frame_equal(self.orders, original)

    def test_duplicate_order_fails_early(self) -> None:
        broken = pd.concat([self.orders, self.orders.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(PIPELINE.PipelineContractError, "one row"):
            PIPELINE.prepare_orders(broken, timezone="Europe/Moscow")

    def test_invalid_timestamp_fails_at_time_stage(self) -> None:
        broken = self.orders.copy()
        broken.loc[0, "ordered_at"] = "not-a-date"
        with self.assertRaisesRegex(PIPELINE.PipelineContractError, "timestamps"):
            PIPELINE.prepare_orders(broken, timezone="Europe/Moscow")

    def test_cli_returns_pipeline_report(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                DATA,
                "--timezone",
                "Europe/Moscow",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["paid_orders"], 4)


if __name__ == "__main__":
    unittest.main()
