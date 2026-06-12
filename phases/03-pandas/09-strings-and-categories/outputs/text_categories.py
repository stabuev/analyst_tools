from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd


class CategoryContractError(ValueError):
    """Raised when text cannot be mapped to the declared category vocabulary."""


def normalize_text(
    series: pd.Series,
    *,
    aliases: Mapping[str, str] | None = None,
) -> pd.Series:
    result = series.astype("string").str.strip().str.lower().str.replace(r"[\s-]+", "_", regex=True)
    if aliases:
        result = result.replace(dict(aliases))
    return result


def as_category(
    series: pd.Series,
    *,
    categories: Sequence[str],
    unknown: str = "error",
) -> pd.Series:
    allowed = list(categories)
    if len(allowed) != len(set(allowed)):
        raise CategoryContractError("categories must be unique")
    non_null = series.dropna()
    unknown_values = sorted(set(non_null) - set(allowed))
    prepared = series.copy()
    if unknown_values:
        if unknown == "error":
            raise CategoryContractError(f"unknown categories: {unknown_values}")
        if unknown != "other":
            raise CategoryContractError("unknown policy must be error or other")
        if "other" not in allowed:
            allowed.append("other")
        prepared = prepared.where(prepared.isin(allowed), "other")
    return prepared.astype(pd.CategoricalDtype(categories=allowed))


def normalize_users(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"user_id", "country", "plan"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise CategoryContractError(f"missing user columns: {missing}")
    result = frame.copy()
    result["country"] = result["country"].astype("string").str.strip().str.upper()
    plans = normalize_text(result["plan"])
    result["plan"] = as_category(
        plans,
        categories=["basic", "premium", "trial"],
        unknown="other",
    )
    return result


def normalize_items(frame: pd.DataFrame) -> pd.DataFrame:
    if "category" not in frame:
        raise CategoryContractError("missing item column: category")
    result = frame.copy()
    normalized = normalize_text(
        result["category"],
        aliases={"addon": "add_on"},
    )
    result["category"] = as_category(
        normalized,
        categories=["add_on", "subscription", "service"],
        unknown="other",
    )
    return result


def category_report(series: pd.Series) -> dict[str, Any]:
    if not isinstance(series.dtype, pd.CategoricalDtype):
        raise CategoryContractError("series must have categorical dtype")
    return {
        "categories": series.cat.categories.tolist(),
        "counts": {
            str(key): int(value) for key, value in series.value_counts(dropna=False).items()
        },
        "missing": int(series.isna().sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize text and categorical values")
    parser.add_argument("users", type=Path)
    parser.add_argument("--items", type=Path)
    args = parser.parse_args()
    try:
        users = normalize_users(pd.read_csv(args.users))
        report: dict[str, Any] = {"plans": category_report(users["plan"])}
        if args.items:
            items = normalize_items(pd.read_csv(args.items))
            report["item_categories"] = category_report(items["category"])
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, CategoryContractError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
