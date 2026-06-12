from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "time_normalizer.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"
SPEC = importlib.util.spec_from_file_location("time_normalizer", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
TIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TIME)


class TimeNormalizerTest(unittest.TestCase):
    def test_equivalent_offsets_become_same_utc_instant(self) -> None:
        parsed = TIME.normalize_utc(
            pd.Series(["2026-01-01T10:00:00+03:00", "2026-01-01T07:00:00Z"])
        )
        self.assertEqual(parsed.iloc[0], parsed.iloc[1])

    def test_invalid_nonempty_timestamp_is_rejected(self) -> None:
        with self.assertRaisesRegex(TIME.TimeContractError, "cannot parse"):
            TIME.normalize_utc(pd.Series(["tomorrow morning"]))

    def test_empty_timestamp_remains_missing(self) -> None:
        parsed = TIME.normalize_utc(pd.Series([""]))
        self.assertTrue(pd.isna(parsed.iloc[0]))

    def test_business_date_uses_explicit_timezone(self) -> None:
        frame = pd.DataFrame({"ts": ["2026-01-01T22:30:00Z"]})
        result = TIME.add_business_calendar(
            frame,
            column="ts",
            timezone="Europe/Moscow",
        )
        self.assertEqual(str(result.loc[0, "local_date"]), "2026-01-02")

    def test_invalid_timezone_is_rejected(self) -> None:
        with self.assertRaisesRegex(TIME.TimeContractError, "invalid timezone"):
            TIME.add_business_calendar(
                pd.DataFrame({"ts": ["2026-01-01T00:00:00Z"]}),
                column="ts",
                timezone="Mars/Olympus",
            )

    def test_elapsed_hours_uses_actual_instants(self) -> None:
        hours = TIME.elapsed_hours(
            pd.Series(["2026-01-01T10:00:00+03:00"]),
            pd.Series(["2026-01-01T09:00:00Z"]),
        )
        self.assertEqual(hours.iloc[0], 2)

    def test_negative_elapsed_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(TIME.TimeContractError, "precedes"):
            TIME.elapsed_hours(
                pd.Series(["2026-01-02T00:00:00Z"]),
                pd.Series(["2026-01-01T00:00:00Z"]),
            )

    def test_cli_reports_missing_timestamp(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                DATA,
                "--column",
                "ordered_at",
                "--timezone",
                "Europe/Moscow",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["missing_timestamps"], 1)


if __name__ == "__main__":
    unittest.main()
