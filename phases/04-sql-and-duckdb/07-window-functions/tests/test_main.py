from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "window_metrics.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("window_metrics", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
WINDOW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WINDOW)


class WindowMetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = WINDOW.build_window_metrics(DATA)
        self.rows = {row["order_id"]: row for row in self.report["rows"]}

    def test_windows_preserve_paid_order_grain(self) -> None:
        self.assertEqual(self.report["checks"]["row_count"], 9)
        self.assertTrue(self.report["checks"]["order_id_unique"])

    def test_row_number_restarts_by_user(self) -> None:
        self.assertEqual(self.rows["O1001"]["order_number"], 1)
        self.assertEqual(self.rows["O1005"]["order_number"], 2)
        self.assertEqual(self.rows["O1003"]["order_number"], 1)

    def test_lag_uses_previous_order_in_partition(self) -> None:
        self.assertIsNone(self.rows["O1001"]["previous_amount"])
        self.assertEqual(self.rows["O1005"]["previous_amount"], 1200.0)

    def test_cumulative_sum_has_explicit_rows_frame(self) -> None:
        self.assertEqual(self.rows["O1001"]["cumulative_amount"], 1200.0)
        self.assertEqual(self.rows["O1005"]["cumulative_amount"], 2700.0)
        self.assertTrue(self.report["checks"]["explicit_rows_frame"])

    def test_another_partition_is_independent(self) -> None:
        self.assertEqual(self.rows["O1012"]["cumulative_amount"], 1600.0)

    def test_rows_and_range_differ_for_peers(self) -> None:
        demo = WINDOW.frame_demo()
        self.assertEqual([row["rows_sum"] for row in demo], [10, 30, 35])
        self.assertEqual([row["range_sum"] for row in demo], [30, 30, 35])

    def test_rank_and_row_number_match_without_ties(self) -> None:
        for row in self.report["rows"]:
            self.assertEqual(row["order_number"], row["order_rank"])

    def test_cli_prints_json(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--orders", DATA],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["checks"]["row_count"], 9)


if __name__ == "__main__":
    unittest.main()
