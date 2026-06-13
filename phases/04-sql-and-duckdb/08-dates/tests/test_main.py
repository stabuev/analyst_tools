from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "time_model.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("time_model", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
TIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TIME)


class TimeModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.report = TIME.normalize_order_times(DATA)
        self.rows = {row["order_id"]: row for row in self.report["rows"]}

    def test_offsets_normalize_to_utc(self) -> None:
        self.assertEqual(self.rows["O1001"]["ordered_at_utc"], "2026-01-05T07:00:00Z")
        self.assertEqual(self.rows["O1003"]["ordered_at_utc"], "2026-02-01T10:00:00Z")

    def test_business_timezone_is_explicit(self) -> None:
        self.assertEqual(self.report["business_timezone"], "Europe/Moscow")
        self.assertEqual(self.rows["O1001"]["business_local_time"], "2026-01-05 10:00:00")

    def test_missing_timestamp_remains_missing(self) -> None:
        self.assertIsNone(self.rows["O1008"]["ordered_at_utc"])
        self.assertIsNone(self.rows["O1008"]["business_date"])

    def test_calendar_months_are_built_after_timezone_conversion(self) -> None:
        self.assertEqual(self.rows["O1007"]["business_month"], "2026-03-01")
        self.assertEqual(
            self.report["summary"]["orders_by_business_month"],
            {
                "2026-01-01": 2,
                "2026-02-01": 4,
                "2026-03-01": 3,
                "2026-04-01": 2,
            },
        )

    def test_summary_reconciles_rows(self) -> None:
        self.assertEqual(self.report["summary"]["source_rows"], 12)
        self.assertEqual(self.report["summary"]["parsed_timestamps"], 11)
        self.assertEqual(self.report["summary"]["missing_timestamps"], 1)

    def test_different_business_timezone_changes_local_time(self) -> None:
        report = TIME.normalize_order_times(DATA, "America/New_York")
        row = next(item for item in report["rows"] if item["order_id"] == "O1001")
        self.assertEqual(row["business_local_time"], "2026-01-05 02:00:00")

    def test_invalid_timezone_is_rejected(self) -> None:
        with self.assertRaisesRegex(Exception, "TimeZone|timezone"):
            TIME.normalize_order_times(DATA, "Not/A_Zone")

    def test_cli_prints_json(self) -> None:
        result = subprocess.run(
            [sys.executable, ARTIFACT, "--orders", DATA],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["summary"]["parsed_timestamps"], 11)


if __name__ == "__main__":
    unittest.main()
