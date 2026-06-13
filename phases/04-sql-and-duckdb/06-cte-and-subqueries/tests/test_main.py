from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "cte_pipeline.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("cte_pipeline", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CTE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CTE)


class CtePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = CTE.run_pipeline(DATA / "orders.csv", DATA / "order_items.csv")
        self.stages = self.report["stages"]

    def test_typing_preserves_source_rows(self) -> None:
        self.assertEqual(self.stages["raw_order_rows"], 12)
        self.assertEqual(self.stages["typed_order_rows"], 12)
        self.assertTrue(self.report["checks"]["typing_preserves_rows"])

    def test_paid_stage_has_expected_rows(self) -> None:
        self.assertEqual(self.stages["paid_order_rows"], 9)

    def test_final_preserves_paid_grain(self) -> None:
        self.assertEqual(self.stages["final_rows"], 9)
        self.assertTrue(self.report["checks"]["final_matches_paid_grain"])
        self.assertTrue(self.report["checks"]["final_key_unique"])

    def test_item_stage_is_one_row_per_order(self) -> None:
        self.assertEqual(self.stages["item_total_rows"], 12)
        self.assertEqual(self.stages["missing_item_totals"], 0)

    def test_pipeline_reconciles_amounts(self) -> None:
        self.assertEqual(self.stages["paid_revenue"], 5005.0)
        self.assertEqual(self.stages["amount_item_mismatches"], 0)
        self.assertTrue(self.report["valid"])

    def test_named_steps_are_present(self) -> None:
        for name in ("raw_orders", "typed_orders", "paid_orders", "item_totals", "final"):
            self.assertIn(f"{name} AS", CTE.PIPELINE_SQL)

    def test_missing_item_is_visible_at_final_stage(self) -> None:
        with TemporaryDirectory() as directory:
            broken = Path(directory) / "items.csv"
            lines = (DATA / "order_items.csv").read_text(encoding="utf-8").splitlines()
            broken.write_text(
                "\n".join(line for line in lines if not line.startswith("O1012,")) + "\n",
                encoding="utf-8",
            )
            report = CTE.run_pipeline(DATA / "orders.csv", broken)
            self.assertEqual(report["stages"]["missing_item_totals"], 1)
            self.assertFalse(report["valid"])

    def test_cli_prints_json(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--orders",
                DATA / "orders.csv",
                "--items",
                DATA / "order_items.csv",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
