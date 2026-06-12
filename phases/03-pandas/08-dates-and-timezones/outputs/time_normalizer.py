from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


class TimeContractError(ValueError):
    """Raised when timestamps cannot be placed on a reliable timeline."""


def normalize_utc(series: pd.Series) -> pd.Series:
    source = series.astype("string")
    parsed = pd.to_datetime(source, errors="coerce", format="mixed", utc=True)
    non_empty = source.notna() & source.str.strip().ne("")
    invalid = non_empty & parsed.isna()
    if invalid.any():
        raise TimeContractError(f"cannot parse {int(invalid.sum())} timestamps")
    return parsed


def add_business_calendar(
    frame: pd.DataFrame,
    *,
    column: str,
    timezone: str,
) -> pd.DataFrame:
    if column not in frame:
        raise TimeContractError(f"missing timestamp column: {column}")
    result = frame.copy()
    utc = normalize_utc(result[column])
    try:
        local = utc.dt.tz_convert(timezone)
    except (TypeError, ValueError, KeyError) as error:
        raise TimeContractError(f"invalid timezone: {timezone}") from error
    result[f"{column}_utc"] = utc
    result[f"{column}_local"] = local
    result["local_date"] = local.dt.date
    result["local_hour"] = local.dt.hour.astype("Int64")
    result["local_week_start"] = (
        local.dt.tz_localize(None).dt.to_period("W-SUN").dt.start_time.dt.date
    )
    return result


def elapsed_hours(start: pd.Series, end: pd.Series) -> pd.Series:
    start_utc = normalize_utc(start)
    end_utc = normalize_utc(end)
    result = (end_utc - start_utc).dt.total_seconds() / 3600
    if result.dropna().lt(0).any():
        raise TimeContractError("end timestamp precedes start timestamp")
    return result.astype("Float64")


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize timestamps and calendar fields")
    parser.add_argument("input", type=Path)
    parser.add_argument("--column", required=True)
    parser.add_argument("--timezone", required=True)
    args = parser.parse_args()
    try:
        result = add_business_calendar(
            pd.read_csv(args.input),
            column=args.column,
            timezone=args.timezone,
        )
        report = {
            "rows": len(result),
            "missing_timestamps": int(result[f"{args.column}_utc"].isna().sum()),
            "local_dates": sorted(str(value) for value in result["local_date"].dropna().unique()),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, TimeContractError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
