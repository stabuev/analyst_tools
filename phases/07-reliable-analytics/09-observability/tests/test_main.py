from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "quality_monitor.py"
THRESHOLDS_PATH = ROOT / "outputs" / "example_thresholds.json"
DATA = ROOT.parent / "data" / "tiny"
OBSERVED_AT = datetime.fromisoformat("2026-06-10T12:00:00+03:00")
SPEC = importlib.util.spec_from_file_location("quality_monitor", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
MONITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MONITOR)
THRESHOLDS = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))


class QualityMonitorTest(unittest.TestCase):
    def test_valid_batch_reports_success_with_fixed_clock(self) -> None:
        report = MONITOR.monitor_batch(DATA, THRESHOLDS, OBSERVED_AT)
        self.assertEqual(report["status"], "success")
        self.assertIsNone(report["failure_class"])
        self.assertEqual(report["metrics"]["row_count"], 10)
        self.assertAlmostEqual(report["metrics"]["freshness_hours"], 1.083, places=3)

    def test_stale_batch_is_a_data_failure(self) -> None:
        report = MONITOR.monitor_batch(
            DATA,
            {**THRESHOLDS, "freshness_hours": 1},
            OBSERVED_AT,
        )
        self.assertEqual(report["failure_class"], "data_failure")
        freshness = next(check for check in report["checks"] if check["id"] == "freshness")
        self.assertFalse(freshness["passed"])

    def test_volume_limits_are_both_explicit(self) -> None:
        low = MONITOR.monitor_batch(DATA, {**THRESHOLDS, "min_orders": 11}, OBSERVED_AT)
        high = MONITOR.monitor_batch(DATA, {**THRESHOLDS, "max_orders": 9}, OBSERVED_AT)
        self.assertEqual(
            [check["id"] for check in low["checks"] if not check["passed"]],
            ["volume_min"],
        )
        self.assertEqual(
            [check["id"] for check in high["checks"] if not check["passed"]],
            ["volume_max"],
        )

    def test_null_and_duplicate_rates_are_measured_per_row(self) -> None:
        orders = pd.read_csv(DATA / "orders.csv", dtype=str)
        orders.loc[0, "user_id"] = ""
        orders = pd.concat([orders, orders.iloc[[1]]], ignore_index=True)
        report = MONITOR.evaluate_orders(orders, THRESHOLDS, OBSERVED_AT)
        self.assertGreater(report["metrics"]["null_key_rate"], 0)
        self.assertGreater(report["metrics"]["duplicate_order_rate"], 0)
        self.assertEqual(report["failure_class"], "data_failure")

    def test_missing_input_is_classified_as_system_failure(self) -> None:
        report = MONITOR.monitor_batch("/path/that/does/not/exist", THRESHOLDS, OBSERVED_AT)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failure_class"], "system_failure")
        self.assertIn("orders.csv", report["error"])

    def test_cli_writes_report_and_jsonl_event(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            log = Path(directory) / "run.jsonl"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--data-dir",
                    DATA,
                    "--thresholds",
                    THRESHOLDS_PATH,
                    "--observed-at",
                    OBSERVED_AT.isoformat(),
                    "--output",
                    output,
                    "--log",
                    log,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), json.loads(output.read_text()))
            event = json.loads(log.read_text().strip())
            self.assertEqual(event["event"], "quality_monitor_finished")
            self.assertEqual(event["status"], "success")


if __name__ == "__main__":
    unittest.main()
