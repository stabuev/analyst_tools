from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

MANIFEST_VERSION = 1
DATASET_SCHEMA_VERSION = "order_mart/v1"
BUILDER_NAME = "pandas-order-mart-builder"
BUILDER_VERSION = "1.0"

STATUS_CATEGORIES = ["paid", "refunded", "pending", "cancelled"]
PLAN_CATEGORIES = ["trial", "basic", "premium"]
ITEM_CATEGORIES = ["add_on", "subscription", "service"]
EXPLICIT_OFFSET_PATTERN = r"(?:Z|[+-]\d{2}:\d{2})$"

OUTPUT_SCHEMA = [
    {"name": "order_id", "logical_type": "string", "nullable": False},
    {"name": "user_id", "logical_type": "string", "nullable": False},
    {
        "name": "ordered_at_utc",
        "logical_type": "datetime64[ns, UTC]",
        "nullable": True,
    },
    {"name": "local_order_date", "logical_type": "date", "nullable": True},
    {
        "name": "status",
        "logical_type": f"category[{','.join(STATUS_CATEGORIES)}]",
        "nullable": False,
    },
    {"name": "currency", "logical_type": "string", "nullable": False},
    {"name": "amount", "logical_type": "Float64", "nullable": True},
    {"name": "item_rows", "logical_type": "Int64", "nullable": False},
    {"name": "item_total", "logical_type": "Float64", "nullable": False},
    {"name": "categories", "logical_type": "string", "nullable": False},
    {"name": "country", "logical_type": "string", "nullable": True},
    {
        "name": "plan",
        "logical_type": f"category[{','.join(PLAN_CATEGORIES)}]",
        "nullable": True,
    },
    {"name": "user_found", "logical_type": "boolean", "nullable": False},
    {"name": "is_paid", "logical_type": "boolean", "nullable": False},
    {"name": "paid_amount", "logical_type": "Float64", "nullable": False},
    {
        "name": "amount_matches_items",
        "logical_type": "boolean",
        "nullable": True,
    },
]
OUTPUT_COLUMNS = [column["name"] for column in OUTPUT_SCHEMA]
SOURCE_NAMES = ("users", "orders", "order_items")


class MartContractError(ValueError):
    """Raised when the mart or delivery package breaks a declared contract."""


def require_columns(
    frame: pd.DataFrame,
    required: set[str],
    *,
    stage: str,
) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise MartContractError(f"{stage}: missing columns: {missing}")


def examples(series: pd.Series, mask: pd.Series) -> list[str]:
    values = series.loc[mask].astype("string").dropna().unique().tolist()
    return [str(value) for value in values[:5]]


def canonical_identifier(series: pd.Series) -> pd.Series:
    result = series.astype("string").str.normalize("NFKC").str.strip()
    return result.mask(result.eq("").fillna(False), pd.NA)


def assert_unique_nonblank(
    frame: pd.DataFrame,
    keys: Sequence[str],
    *,
    stage: str,
) -> None:
    require_columns(frame, set(keys), stage=stage)
    missing_key = frame[list(keys)].isna().any(axis=1)
    if missing_key.any():
        raise MartContractError(
            f"{stage}: keys must be non-missing and non-blank: {list(keys)}"
        )
    duplicate = frame.duplicated(list(keys), keep=False)
    if duplicate.any():
        duplicate_examples = [
            tuple(str(value) for value in row)
            for row in frame.loc[duplicate, list(keys)].head(5).itertuples(
                index=False,
                name=None,
            )
        ]
        raise MartContractError(
            f"{stage}: keys are not unique: {list(keys)}; "
            f"examples: {duplicate_examples}"
        )


def normalize_text(
    series: pd.Series,
    *,
    separators: bool = False,
) -> pd.Series:
    result = (
        series.astype("string")
        .str.normalize("NFKC")
        .str.strip()
        .str.casefold()
    )
    if separators:
        result = (
            result.str.replace(r"[\s_\-‐‑‒–—]+", "_", regex=True)
            .str.strip("_")
        )
    return result.mask(result.eq("").fillna(False), pd.NA)


def categorize(
    series: pd.Series,
    *,
    categories: Sequence[str],
    stage: str,
    aliases: dict[str, str] | None = None,
) -> pd.Series:
    normalized = normalize_text(series, separators=True)
    if aliases:
        normalized = normalized.replace(aliases)
    if normalized.isna().any():
        raise MartContractError(f"{stage}: category must be non-missing and non-blank")
    unknown = ~normalized.isin(categories)
    if unknown.any():
        raise MartContractError(
            f"{stage}: unknown categories: {examples(normalized, unknown)}"
        )
    dtype = pd.CategoricalDtype(categories=list(categories), ordered=False)
    return normalized.astype(dtype)


def strict_numeric(
    series: pd.Series,
    *,
    dtype: str,
    nullable: bool,
    stage: str,
) -> pd.Series:
    source = series.astype("string").str.strip()
    missing = source.isna() | source.eq("").fillna(False)
    parsed = pd.to_numeric(source.mask(missing), errors="coerce")
    invalid = (~missing & parsed.isna()) | parsed.isin(
        [float("inf"), float("-inf")]
    )
    if invalid.any():
        raise MartContractError(
            f"{stage}: invalid numeric values: {examples(source, invalid)}"
        )
    if missing.any() and not nullable:
        raise MartContractError(f"{stage}: numeric value must be non-missing")
    if dtype == "Int64":
        fractional = parsed.notna() & parsed.mod(1).ne(0)
        if fractional.any():
            raise MartContractError(
                f"{stage}: expected integer values: {examples(source, fractional)}"
            )
    return parsed.astype(dtype)


def parse_aware_utc(series: pd.Series, *, stage: str) -> pd.Series:
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
        raise MartContractError(
            f"{stage}: invalid timestamps: {examples(source, invalid)}"
        )
    has_offset = source.str.contains(
        EXPLICIT_OFFSET_PATTERN,
        regex=True,
        na=False,
    )
    naive = ~missing & ~has_offset
    if naive.any():
        raise MartContractError(
            f"{stage}: timestamps need an explicit UTC offset: "
            f"{examples(source, naive)}"
        )
    return parsed.astype(pd.DatetimeTZDtype(unit="ns", tz="UTC"))
