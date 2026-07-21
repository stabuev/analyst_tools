from __future__ import annotations

import pandas as pd
from pandas.api.types import is_timedelta64_dtype

EXPLICIT_OFFSET_PATTERN = r"(?:Z|[+-]\d{2}:\d{2})$"


class TimeContractError(ValueError):
    """Raised when temporal data violates the declared source contract."""


def _require_series(value: object, *, name: str) -> pd.Series:
    if not isinstance(value, pd.Series):
        raise TimeContractError(f"{name} must be a pandas Series")
    return value


def parse_aware_utc(series: pd.Series) -> pd.Series:
    """Parse ISO 8601 timestamps with explicit offsets onto the UTC timeline."""

    series = _require_series(series, name="series")
    source = series.astype("string").str.strip()
    missing = source.isna() | source.eq("").fillna(False)
    parsed = pd.to_datetime(
        source.mask(missing),
        format="ISO8601",
        errors="coerce",
        utc=True,
    )
    invalid = ~missing & parsed.isna()
    if invalid.any():
        raise TimeContractError(f"cannot parse {int(invalid.sum())} timestamps")

    has_offset = source.str.contains(EXPLICIT_OFFSET_PATTERN, regex=True, na=False)
    naive = ~missing & ~has_offset
    if naive.any():
        raise TimeContractError(
            f"{int(naive.sum())} timestamps have no explicit UTC offset"
        )
    return parsed


def add_business_calendar(
    frame: pd.DataFrame,
    *,
    column: str,
    timezone: str,
) -> pd.DataFrame:
    """Add UTC, local timestamp, local day, and local hour without changing grain."""

    if not isinstance(frame, pd.DataFrame):
        raise TimeContractError("frame must be a pandas DataFrame")
    if column not in frame.columns:
        raise TimeContractError(f"missing timestamp column: {column}")
    if not isinstance(timezone, str) or not timezone.strip():
        raise TimeContractError("timezone must be a non-empty named zone")

    result = frame.copy()
    utc = parse_aware_utc(result[column])
    try:
        local = utc.dt.tz_convert(timezone)
    except (TypeError, ValueError, KeyError) as error:
        raise TimeContractError(f"invalid timezone: {timezone}") from error

    result[f"{column}_utc"] = utc
    result[f"{column}_local"] = local
    result["local_day"] = local.dt.normalize()
    result["local_hour"] = local.dt.hour.astype("Int64")
    return result


def elapsed_time(start: pd.Series, end: pd.Series) -> pd.Series:
    """Return non-negative elapsed time between index-aligned aware moments."""

    start = _require_series(start, name="start")
    end = _require_series(end, name="end")
    if not start.index.equals(end.index):
        raise TimeContractError("start and end indexes must match exactly")

    start_utc = parse_aware_utc(start)
    end_utc = parse_aware_utc(end)
    duration = (end_utc - start_utc).rename("elapsed_time")
    if duration.dropna().lt(pd.Timedelta(0)).any():
        raise TimeContractError("end timestamp precedes start timestamp")
    return duration


def duration_to_hours(duration: pd.Series) -> pd.Series:
    """Convert a Timedelta Series to reporting hours without losing whole days."""

    duration = _require_series(duration, name="duration")
    if not is_timedelta64_dtype(duration.dtype):
        raise TimeContractError("duration must have a timedelta64 dtype")
    hours = duration.dt.total_seconds().div(3600).astype("Float64")
    return hours.rename("elapsed_hours")
