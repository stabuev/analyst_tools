from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple

import pandas as pd

SEPARATOR_PATTERN = r"[\s_\-‐‑‒–—]+"
SEPARATOR_REGEX = re.compile(SEPARATOR_PATTERN)


class CategoryContractError(ValueError):
    """Raised when text or a categorical vocabulary breaks the declared contract."""


class CategoryContractResult(NamedTuple):
    """A categorical Series together with evidence collected before lossy mapping."""

    values: pd.Series
    audit: dict[str, Any]


def _canonical_token(value: str) -> str:
    if not isinstance(value, str):
        raise CategoryContractError("text contract values must be strings")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return SEPARATOR_REGEX.sub("_", normalized).strip("_")


def _normalize_aliases(aliases: Mapping[str, str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_source, raw_target in (aliases or {}).items():
        source = _canonical_token(raw_source)
        target = _canonical_token(raw_target)
        if not source or not target:
            raise CategoryContractError("aliases cannot contain blank source or target")
        if source in normalized and normalized[source] != target:
            raise CategoryContractError(f"conflicting alias for {source!r}")
        normalized[source] = target
    return normalized


def normalize_text(
    series: pd.Series,
    *,
    aliases: Mapping[str, str] | None = None,
) -> pd.Series:
    """Normalize categorical text while preserving index, name, and missing values."""

    if not isinstance(series, pd.Series):
        raise CategoryContractError("normalize_text expects a pandas Series")

    result = (
        series.astype("string")
        .str.normalize("NFKC")
        .str.strip()
        .str.casefold()
        .str.replace(SEPARATOR_PATTERN, "_", regex=True)
        .str.strip("_")
    )
    blank = result.eq("").fillna(False)
    result = result.mask(blank, pd.NA)

    normalized_aliases = _normalize_aliases(aliases)
    if normalized_aliases:
        result = result.replace(normalized_aliases)

    result.name = series.name
    return result


def fullmatch_text(series: pd.Series, pattern: str) -> pd.Series:
    """Check the whole value against a format while keeping missing as unknown."""

    if not isinstance(series, pd.Series):
        raise CategoryContractError("fullmatch_text expects a pandas Series")
    if not isinstance(pattern, str) or not pattern:
        raise CategoryContractError("pattern must be a non-empty string")

    result = series.astype("string").str.fullmatch(pattern).astype("boolean")
    result.name = series.name
    return result


def _validate_categories(categories: Sequence[str]) -> list[str]:
    if isinstance(categories, (str, bytes)):
        raise CategoryContractError("categories must be a sequence of strings")
    declared = list(categories)
    if not declared:
        raise CategoryContractError("categories cannot be empty")
    if any(not isinstance(value, str) for value in declared):
        raise CategoryContractError("categories must contain only strings")
    if len(declared) != len(set(declared)):
        raise CategoryContractError("categories must be unique")

    normalized = [_canonical_token(value) for value in declared]
    if any(not value for value in normalized):
        raise CategoryContractError("categories cannot contain blank values")
    if normalized != declared:
        raise CategoryContractError("categories must already use canonical spelling")
    return declared


def categorize_text(
    series: pd.Series,
    *,
    categories: Sequence[str],
    aliases: Mapping[str, str] | None = None,
    unknown: str = "error",
    other_label: str = "other",
    ordered: bool = False,
) -> CategoryContractResult:
    """Normalize text, enforce a stable vocabulary, and retain audit evidence."""

    if unknown not in {"error", "other"}:
        raise CategoryContractError("unknown policy must be 'error' or 'other'")
    if not isinstance(ordered, bool):
        raise CategoryContractError("ordered must be true or false")

    declared = _validate_categories(categories)
    canonical_other = _canonical_token(other_label)
    if unknown == "other" and (not canonical_other or canonical_other != other_label):
        raise CategoryContractError("other_label must be a non-blank canonical string")

    raw = series.astype("string")
    normalized = normalize_text(series, aliases=aliases)
    unknown_mask = normalized.notna() & ~normalized.isin(declared)
    unknown_counts = Counter(str(value) for value in normalized.loc[unknown_mask].tolist())

    if unknown_counts and unknown == "error":
        rendered = ", ".join(
            f"{value!r}: {count}" for value, count in sorted(unknown_counts.items())
        )
        raise CategoryContractError(f"unknown categories: {rendered}")

    final_categories = declared.copy()
    prepared = normalized.copy()
    if unknown == "other":
        if canonical_other not in final_categories:
            final_categories.append(canonical_other)
        prepared = prepared.mask(unknown_mask, canonical_other)

    dtype = pd.CategoricalDtype(categories=final_categories, ordered=ordered)
    values = prepared.astype(dtype)
    values.name = series.name

    raw_blank = raw.notna() & raw.str.strip().eq("").fillna(False)
    changes: Counter[tuple[str, str]] = Counter()
    for raw_value, canonical_value in zip(raw.tolist(), normalized.tolist(), strict=True):
        if pd.isna(raw_value) or pd.isna(canonical_value):
            continue
        raw_text = str(raw_value)
        canonical_text = str(canonical_value)
        if raw_text != canonical_text:
            changes[(raw_text, canonical_text)] += 1

    audit: dict[str, Any] = {
        "categories": final_categories,
        "ordered": ordered,
        "unknown_policy": unknown,
        "source_missing_count": int(raw.isna().sum()),
        "blank_to_missing_count": int(raw_blank.sum()),
        "result_missing_count": int(values.isna().sum()),
        "unknown_count": int(unknown_mask.sum()),
        "unknown_values": dict(sorted(unknown_counts.items())),
        "canonical_counts": {
            category: int(values.eq(category).sum()) for category in final_categories
        },
        "normalization_changes": [
            {"raw": raw_value, "canonical": canonical, "count": count}
            for (raw_value, canonical), count in sorted(changes.items())
        ],
    }
    return CategoryContractResult(values=values, audit=audit)
