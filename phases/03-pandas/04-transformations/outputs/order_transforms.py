from __future__ import annotations

import math
from numbers import Real

import pandas as pd


class TransformContractError(ValueError):
    """Raised when a table cannot be transformed without changing its meaning."""


def _validate_review_threshold(review_threshold: Real) -> float:
    if isinstance(review_threshold, bool) or not isinstance(review_threshold, Real):
        raise TransformContractError("review_threshold must be a finite non-negative number")
    threshold = float(review_threshold)
    if not math.isfinite(threshold) or threshold < 0:
        raise TransformContractError("review_threshold must be a finite non-negative number")
    return threshold


def _validate_input(frame: pd.DataFrame) -> None:
    required = {"quantity", "unit_price"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise TransformContractError(f"missing columns: {missing}")

    produced = {"line_total", "requires_review", "review_amount"}
    collisions = sorted(produced & set(frame.columns))
    if collisions:
        raise TransformContractError(f"output columns already exist: {collisions}")

    expected_dtypes = {"quantity": "Int64", "unit_price": "Float64"}
    wrong_dtypes = {
        column: {"expected": expected, "actual": str(frame[column].dtype)}
        for column, expected in expected_dtypes.items()
        if str(frame[column].dtype) != expected
    }
    if wrong_dtypes:
        raise TransformContractError(
            f"input must already satisfy the dtype contract: {wrong_dtypes}"
        )

    quantity_is_invalid = frame["quantity"].notna() & frame["quantity"].le(0)
    price_is_invalid = frame["unit_price"].notna() & frame["unit_price"].lt(0)
    if quantity_is_invalid.any():
        labels = frame.index[quantity_is_invalid].tolist()
        raise TransformContractError(f"quantity must be positive at rows: {labels}")
    if price_is_invalid.any():
        labels = frame.index[price_is_invalid].tolist()
        raise TransformContractError(f"unit_price must be non-negative at rows: {labels}")


def add_line_item_features(
    frame: pd.DataFrame,
    *,
    review_threshold: Real,
) -> pd.DataFrame:
    """Add row-preserving line-item features to an already typed DataFrame.

    Missing quantity or price remains unknown in every dependent feature. The input
    object is not modified; its row count, index and existing columns are preserved.
    """

    threshold = _validate_review_threshold(review_threshold)
    _validate_input(frame)

    result = frame.copy()

    line_total = (result["quantity"] * result["unit_price"]).astype("Float64")
    requires_review = line_total.ge(threshold).astype("boolean")

    # Series.where uses ``other`` not only for False, but also for pd.NA in a nullable
    # condition. Restore unknown decisions explicitly instead of turning them into zero.
    review_amount = line_total.where(requires_review, 0.0).astype("Float64")
    review_amount = review_amount.mask(requires_review.isna(), pd.NA)

    result["line_total"] = line_total
    result["requires_review"] = requires_review
    result["review_amount"] = review_amount.astype("Float64")
    return result
