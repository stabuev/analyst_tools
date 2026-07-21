from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd
from pandas.api.types import is_timedelta64_dtype

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "time_normalizer.py"
SPEC = importlib.util.spec_from_file_location("time_normalizer", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
TIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TIME)


class TimeNormalizerTest(unittest.TestCase):
    def test_equivalent_offsets_become_same_utc_instant(self) -> None:
        parsed = TIME.parse_aware_utc(
            pd.Series(["2026-01-01T10:00:00+03:00", "2026-01-01T07:00:00Z"])
        )

        self.assertEqual(parsed.iloc[0], parsed.iloc[1])
        self.assertEqual(str(parsed.dt.tz), "UTC")

    def test_naive_timestamp_is_rejected_instead_of_assumed_utc(self) -> None:
        with self.assertRaisesRegex(TIME.TimeContractError, "no explicit UTC offset"):
            TIME.parse_aware_utc(pd.Series(["2026-01-01T10:00:00"]))

    def test_invalid_nonempty_timestamp_is_rejected(self) -> None:
        with self.assertRaisesRegex(TIME.TimeContractError, "cannot parse"):
            TIME.parse_aware_utc(pd.Series(["not-a-date"]))

    def test_empty_and_null_timestamps_remain_missing(self) -> None:
        parsed = TIME.parse_aware_utc(pd.Series(["  ", None]))

        self.assertTrue(parsed.isna().all())

    def test_business_day_is_derived_after_timezone_conversion(self) -> None:
        frame = pd.DataFrame({"ts": ["2026-01-01T22:30:00Z"]})

        result = TIME.add_business_calendar(
            frame,
            column="ts",
            timezone="Europe/Moscow",
        )

        self.assertEqual(result.loc[0, "ts_local"].hour, 1)
        self.assertEqual(str(result.loc[0, "local_day"]), "2026-01-02 00:00:00+03:00")
        self.assertEqual(str(result["local_day"].dt.tz), "Europe/Moscow")

    def test_calendar_enrichment_preserves_input_grain_index_and_object(self) -> None:
        frame = pd.DataFrame(
            {"ts": ["2026-01-01T00:00:00Z", None]},
            index=["O2", "O1"],
        )
        before = frame.copy(deep=True)

        result = TIME.add_business_calendar(
            frame,
            column="ts",
            timezone="Europe/Moscow",
        )

        pd.testing.assert_frame_equal(frame, before)
        self.assertIsNot(result, frame)
        self.assertEqual(result.index.tolist(), ["O2", "O1"])
        self.assertEqual(len(result), len(frame))

    def test_invalid_timezone_is_rejected(self) -> None:
        with self.assertRaisesRegex(TIME.TimeContractError, "invalid timezone"):
            TIME.add_business_calendar(
                pd.DataFrame({"ts": ["2026-01-01T00:00:00Z"]}),
                column="ts",
                timezone="Mars/Olympus",
            )

    def test_elapsed_time_returns_timedelta_for_actual_instants(self) -> None:
        duration = TIME.elapsed_time(
            pd.Series(["2026-03-29T01:30:00+01:00"], index=["D1"]),
            pd.Series(["2026-03-29T03:30:00+02:00"], index=["D1"]),
        )

        self.assertTrue(is_timedelta64_dtype(duration.dtype))
        self.assertEqual(duration.loc["D1"], pd.Timedelta(hours=1))

    def test_missing_endpoint_produces_missing_duration(self) -> None:
        duration = TIME.elapsed_time(
            pd.Series([None], index=["D1"]),
            pd.Series(["2026-03-29T03:30:00+02:00"], index=["D1"]),
        )

        self.assertTrue(pd.isna(duration.loc["D1"]))

    def test_misaligned_series_are_rejected_before_subtraction(self) -> None:
        with self.assertRaisesRegex(TIME.TimeContractError, "indexes must match"):
            TIME.elapsed_time(
                pd.Series(["2026-01-01T00:00:00Z"], index=["A"]),
                pd.Series(["2026-01-01T01:00:00Z"], index=["B"]),
            )

    def test_negative_elapsed_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(TIME.TimeContractError, "precedes"):
            TIME.elapsed_time(
                pd.Series(["2026-01-02T00:00:00Z"]),
                pd.Series(["2026-01-01T00:00:00Z"]),
            )

    def test_duration_to_hours_keeps_whole_days(self) -> None:
        duration = pd.Series([pd.Timedelta(hours=49), pd.NaT])

        hours = TIME.duration_to_hours(duration)

        self.assertEqual(hours.iloc[0], 49.0)
        self.assertTrue(pd.isna(hours.iloc[1]))
        self.assertEqual(str(hours.dtype), "Float64")

    def test_duration_to_hours_rejects_plain_numbers(self) -> None:
        with self.assertRaisesRegex(TIME.TimeContractError, "timedelta64"):
            TIME.duration_to_hours(pd.Series([1.5]))


if __name__ == "__main__":
    unittest.main()
