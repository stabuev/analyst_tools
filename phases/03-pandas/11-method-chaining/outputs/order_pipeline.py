from __future__ import annotations

import pandas as pd
from pandas.api.types import CategoricalDtype

REQUIRED_COLUMNS = {"order_id", "ordered_at", "status", "currency", "amount"}
STATUS_CATEGORIES = ["paid", "refunded", "pending", "cancelled"]
STATUS_DTYPE = CategoricalDtype(categories=STATUS_CATEGORIES, ordered=False)
EXPLICIT_OFFSET_PATTERN = r"(?:Z|[+-]\d{2}:\d{2})$"


class PipelineContractError(ValueError):
    """Raised when a named pipeline stage breaks its declared contract."""


def _require_columns(frame: pd.DataFrame, *, stage: str) -> None:
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise PipelineContractError(f"{stage}: missing columns: {missing}")


def _examples(series: pd.Series, mask: pd.Series) -> list[str]:
    values = series.loc[mask].astype("string").dropna().unique().tolist()
    return [str(value) for value in values[:5]]


def _normalize_text(series: pd.Series) -> pd.Series:
    normalized = (
        series.astype("string")
        .str.normalize("NFKC")
        .str.strip()
        .str.casefold()
    )
    return normalized.mask(normalized.eq("").fillna(False), pd.NA)


def check_raw_orders(frame: pd.DataFrame) -> pd.DataFrame:
    """Check the incoming schema and order grain without changing the frame."""

    if not isinstance(frame, pd.DataFrame):
        raise PipelineContractError("check_raw_orders: expected a pandas DataFrame")
    _require_columns(frame, stage="check_raw_orders")

    order_id = frame["order_id"].astype("string").str.strip()
    missing_key = order_id.isna() | order_id.eq("").fillna(False)
    if missing_key.any():
        raise PipelineContractError(
            "check_raw_orders: order_id must be non-missing and non-blank"
        )
    if order_id.duplicated().any():
        duplicates = _examples(order_id, order_id.duplicated(keep=False))
        raise PipelineContractError(
            f"check_raw_orders: expected one row per order_id; duplicates: {duplicates}"
        )
    return frame


def normalize_order_fields(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize text and parse amount without confusing invalid values with missing."""

    _require_columns(frame, stage="normalize_order_fields")

    status = _normalize_text(frame["status"])
    if status.isna().any():
        raise PipelineContractError(
            "normalize_order_fields: status must be non-missing and non-blank"
        )
    unknown_status = ~status.isin(STATUS_CATEGORIES)
    if unknown_status.any():
        unknown = _examples(status, unknown_status)
        raise PipelineContractError(
            f"normalize_order_fields: unknown status values: {unknown}"
        )

    currency = (
        frame["currency"]
        .astype("string")
        .str.normalize("NFKC")
        .str.strip()
        .str.upper()
    )
    currency = currency.mask(currency.eq("").fillna(False), pd.NA)
    if currency.isna().any():
        raise PipelineContractError(
            "normalize_order_fields: currency must be non-missing and non-blank"
        )
    invalid_currency = ~currency.str.fullmatch(r"[A-Z]{3}", na=False)
    if invalid_currency.any():
        invalid = _examples(currency, invalid_currency)
        raise PipelineContractError(
            f"normalize_order_fields: invalid currency codes: {invalid}"
        )

    amount_source = frame["amount"].astype("string").str.strip()
    amount_missing = amount_source.isna() | amount_source.eq("").fillna(False)
    amount = pd.to_numeric(
        amount_source.mask(amount_missing),
        errors="coerce",
    )
    invalid_amount = (~amount_missing & amount.isna()) | amount.isin(
        [float("inf"), float("-inf")]
    )
    if invalid_amount.any():
        invalid = _examples(amount_source, invalid_amount)
        raise PipelineContractError(
            f"normalize_order_fields: invalid amount values: {invalid}"
        )

    return frame.assign(
        status=status.astype(STATUS_DTYPE),
        currency=currency.astype("string"),
        amount=amount.astype("Float64"),
    )


def check_normalized_orders(
    frame: pd.DataFrame,
    *,
    expected_index: pd.Index,
) -> pd.DataFrame:
    """Checkpoint the text, dtype, vocabulary, and row-identity contracts."""

    if not frame.index.equals(expected_index):
        raise PipelineContractError(
            "check_normalized_orders: stage changed row labels or their order"
        )
    if str(frame["amount"].dtype) != "Float64":
        raise PipelineContractError(
            "check_normalized_orders: amount must have nullable Float64 dtype"
        )
    if frame["status"].dtype != STATUS_DTYPE:
        raise PipelineContractError(
            "check_normalized_orders: status vocabulary or category order changed"
        )
    if str(frame["currency"].dtype) != "string":
        raise PipelineContractError(
            "check_normalized_orders: currency must have string dtype"
        )
    return frame


def add_time_columns(
    frame: pd.DataFrame,
    *,
    timezone: str,
) -> pd.DataFrame:
    """Parse aware timestamps onto UTC and derive the local business date."""

    source = frame["ordered_at"].astype("string").str.strip()
    missing = source.isna() | source.eq("").fillna(False)
    parsed = pd.to_datetime(
        source.mask(missing),
        format="ISO8601",
        errors="coerce",
        utc=True,
    )
    invalid = ~missing & parsed.isna()
    if invalid.any():
        values = _examples(source, invalid)
        raise PipelineContractError(
            f"add_time_columns: invalid ordered_at values: {values}"
        )

    has_offset = source.str.contains(
        EXPLICIT_OFFSET_PATTERN,
        regex=True,
        na=False,
    )
    naive = ~missing & ~has_offset
    if naive.any():
        values = _examples(source, naive)
        raise PipelineContractError(
            f"add_time_columns: timestamps need an explicit UTC offset: {values}"
        )

    try:
        local = parsed.dt.tz_convert(timezone)
    except (TypeError, ValueError, KeyError) as error:
        raise PipelineContractError(
            f"add_time_columns: invalid timezone: {timezone}"
        ) from error

    return frame.assign(
        ordered_at_utc=parsed,
        local_order_date=local.dt.date,
    )


def add_paid_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """Add paid flags and amounts after status and amount contracts are satisfied."""

    if frame["status"].isna().any():
        raise PipelineContractError(
            "add_paid_metrics: status must be known before calculating paid metrics"
        )
    is_paid = frame["status"].eq("paid").astype("boolean")
    return frame.assign(
        is_paid=is_paid,
        paid_amount=frame["amount"].where(is_paid, 0).astype("Float64"),
    )


def check_prepared_orders(
    frame: pd.DataFrame,
    *,
    expected_index: pd.Index,
    expected_rows: int,
) -> pd.DataFrame:
    """Check final grain, row identity, and paid-metric invariants."""

    if len(frame) != expected_rows or not frame.index.equals(expected_index):
        raise PipelineContractError(
            "check_prepared_orders: a preserving stage changed rows or their order"
        )
    check_raw_orders(frame)

    paid = frame["is_paid"]
    paid_missing_amount = paid & frame["amount"].isna()
    if paid_missing_amount.any():
        order_ids = _examples(frame["order_id"], paid_missing_amount)
        raise PipelineContractError(
            f"check_prepared_orders: paid orders need amount: {order_ids}"
        )
    if frame.loc[paid, "paid_amount"].ne(frame.loc[paid, "amount"]).any():
        raise PipelineContractError(
            "check_prepared_orders: paid rows must preserve amount"
        )
    if frame.loc[~paid, "paid_amount"].ne(0).any():
        raise PipelineContractError(
            "check_prepared_orders: non-paid rows must contribute zero"
        )
    return frame


def prepare_orders(frame: pd.DataFrame, *, timezone: str) -> pd.DataFrame:
    """Run the checked order pipeline and return a deterministic order-level table."""

    if not isinstance(frame, pd.DataFrame):
        raise PipelineContractError("prepare_orders: expected a pandas DataFrame")
    source = frame.copy(deep=True)
    source_index = source.index.copy()
    source_rows = len(source)

    return (
        source.pipe(check_raw_orders)
        .pipe(normalize_order_fields)
        .pipe(check_normalized_orders, expected_index=source_index)
        .pipe(add_time_columns, timezone=timezone)
        .pipe(add_paid_metrics)
        .pipe(
            check_prepared_orders,
            expected_index=source_index,
            expected_rows=source_rows,
        )
        .sort_values("order_id", kind="stable")
        .reset_index(drop=True)
    )
