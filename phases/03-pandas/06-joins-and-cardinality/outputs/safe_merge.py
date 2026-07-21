from __future__ import annotations

from typing import Any

import pandas as pd


class MergeContractError(ValueError):
    """Raised when a merge would violate the declared data contract."""


ALLOWED_HOW = {"inner", "left", "right", "outer"}
ALLOWED_VALIDATE = {"one_to_one", "one_to_many", "many_to_one"}
ROLLUP_DTYPES = {
    "order_id": "string",
    "line_count": "Int64",
    "known_amount_lines": "Int64",
    "missing_amount_lines": "Int64",
    "known_amount_total": "Float64",
    "order_amount": "Float64",
}


def _normalise_keys(on: object) -> list[str]:
    if not isinstance(on, list) or not on:
        raise MergeContractError("on must be a non-empty list of column names")
    if any(not isinstance(column, str) or not column for column in on):
        raise MergeContractError("every merge key must be a non-empty string")
    if len(on) != len(set(on)):
        raise MergeContractError("merge key names must not repeat")
    return on


def _validate_frame(frame: object, *, label: str, keys: list[str]) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise MergeContractError(f"{label} must be a pandas DataFrame")
    if not frame.columns.is_unique:
        raise MergeContractError(f"{label} column labels must be unique")

    missing_columns = sorted(set(keys) - set(frame.columns))
    if missing_columns:
        raise MergeContractError(f"{label} misses key columns: {missing_columns}")

    missing_key = frame[keys].isna().any(axis=1)
    if missing_key.any():
        labels = frame.index[missing_key].tolist()
        raise MergeContractError(
            f"{label} merge key must be non-missing at rows: {labels}"
        )

    blank_key = pd.Series(False, index=frame.index, dtype="boolean")
    for column in keys:
        blank_key |= frame[column].map(
            lambda value: isinstance(value, str) and value.strip() == ""
        ).astype("boolean")
    if blank_key.any():
        labels = frame.index[blank_key].tolist()
        raise MergeContractError(
            f"{label} merge key must be non-blank at rows: {labels}"
        )
    return frame


def _assert_unique_key(frame: pd.DataFrame, keys: list[str], *, label: str) -> None:
    duplicated = frame.duplicated(keys, keep=False)
    if duplicated.any():
        examples = frame.loc[duplicated, keys].drop_duplicates().head(5).to_dict("records")
        raise MergeContractError(
            f"{label} key must be unique for the declared cardinality; "
            f"duplicate key examples: {examples}"
        )


def _validate_cardinality(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    keys: list[str],
    validate: str,
) -> None:
    if validate not in ALLOWED_VALIDATE:
        if validate == "many_to_many":
            raise MergeContractError(
                "many_to_many performs no uniqueness check; declare a safer cardinality"
            )
        raise MergeContractError(
            f"validate must be one of {sorted(ALLOWED_VALIDATE)}"
        )
    if validate in {"one_to_one", "one_to_many"}:
        _assert_unique_key(left, keys, label="left")
    if validate in {"one_to_one", "many_to_one"}:
        _assert_unique_key(right, keys, label="right")


def _frequency_table(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    keys: list[str],
) -> pd.DataFrame:
    left_frequency = (
        left.groupby(keys, as_index=False, sort=False, dropna=False)
        .size()
        .rename(columns={"size": "left_frequency"})
    )
    right_frequency = (
        right.groupby(keys, as_index=False, sort=False, dropna=False)
        .size()
        .rename(columns={"size": "right_frequency"})
    )
    coverage = left_frequency.merge(
        right_frequency,
        on=keys,
        how="outer",
        validate="one_to_one",
        indicator="key_status",
        sort=False,
    )
    coverage["left_frequency"] = coverage["left_frequency"].fillna(0).astype("Int64")
    coverage["right_frequency"] = coverage["right_frequency"].fillna(0).astype("Int64")
    return coverage


def _predicted_rows(coverage: pd.DataFrame, *, how: str) -> int:
    left_frequency = coverage["left_frequency"]
    right_frequency = coverage["right_frequency"]
    matched = left_frequency * right_frequency

    if how == "inner":
        contribution = matched
    elif how == "left":
        contribution = matched.mask(right_frequency.eq(0), left_frequency)
    elif how == "right":
        contribution = matched.mask(left_frequency.eq(0), right_frequency)
    else:
        contribution = matched.mask(
            right_frequency.eq(0), left_frequency
        ).mask(left_frequency.eq(0), right_frequency)
    return int(contribution.sum())


def _key_examples(
    coverage: pd.DataFrame,
    *,
    keys: list[str],
    status: str,
) -> list[dict[str, Any]]:
    return coverage.loc[coverage["key_status"].eq(status), keys].head(5).to_dict("records")


def merge_with_contract(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    on: list[str],
    how: str,
    validate: str,
    indicator: str = "merge_status",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Merge two tables only after checking the declared relationship.

    Business keys are mandatory: missing and blank values are rejected before pandas can
    match null keys to each other. The report counts distinct unmatched keys independently
    of ``how``, so a left join still reveals keys that exist only on the right.
    """

    keys = _normalise_keys(on)
    if how not in ALLOWED_HOW:
        raise MergeContractError(f"how must be one of {sorted(ALLOWED_HOW)}")
    if not isinstance(indicator, str) or not indicator.strip():
        raise MergeContractError("indicator must be a non-blank column name")

    left_frame = _validate_frame(left, label="left", keys=keys)
    right_frame = _validate_frame(right, label="right", keys=keys)

    if indicator in left_frame.columns or indicator in right_frame.columns:
        raise MergeContractError(f"indicator column already exists: {indicator}")

    dtype_mismatches = {
        key: {"left": str(left_frame[key].dtype), "right": str(right_frame[key].dtype)}
        for key in keys
        if str(left_frame[key].dtype) != str(right_frame[key].dtype)
    }
    if dtype_mismatches:
        raise MergeContractError(
            f"merge key dtypes must match before merge: {dtype_mismatches}"
        )

    overlaps = sorted((set(left_frame.columns) & set(right_frame.columns)) - set(keys))
    if overlaps:
        raise MergeContractError(
            "non-key columns overlap; rename them before merge so provenance stays "
            f"explicit: {overlaps}"
        )

    _validate_cardinality(
        left_frame,
        right_frame,
        keys=keys,
        validate=validate,
    )
    coverage = _frequency_table(left_frame, right_frame, keys=keys)
    expected_rows = _predicted_rows(coverage, how=how)

    try:
        merged = left_frame.merge(
            right_frame,
            on=keys,
            how=how,
            validate=validate,
            indicator=indicator,
            sort=False,
        )
    except pd.errors.MergeError as error:
        raise MergeContractError(str(error)) from error

    if len(merged) != expected_rows:
        raise MergeContractError(
            f"row-count prediction failed: expected {expected_rows}, got {len(merged)}"
        )

    key_counts = coverage["key_status"].value_counts()
    report: dict[str, Any] = {
        "on": keys.copy(),
        "how": how,
        "validate": validate,
        "left_rows": len(left_frame),
        "right_rows": len(right_frame),
        "left_distinct_keys": len(coverage.loc[coverage["left_frequency"].gt(0)]),
        "right_distinct_keys": len(coverage.loc[coverage["right_frequency"].gt(0)]),
        "matched_key_count": int(key_counts.get("both", 0)),
        "left_only_key_count": int(key_counts.get("left_only", 0)),
        "right_only_key_count": int(key_counts.get("right_only", 0)),
        "left_only_key_examples": _key_examples(
            coverage,
            keys=keys,
            status="left_only",
        ),
        "right_only_key_examples": _key_examples(
            coverage,
            keys=keys,
            status="right_only",
        ),
        "predicted_result_rows": expected_rows,
        "result_rows": len(merged),
    }
    return merged, report


def _validate_order_rollup(frame: object) -> pd.DataFrame:
    rollup = _validate_frame(frame, label="order_rollup", keys=["order_id"])
    missing_columns = sorted(set(ROLLUP_DTYPES) - set(rollup.columns))
    if missing_columns:
        raise MergeContractError(f"order_rollup misses columns: {missing_columns}")

    wrong_dtypes = {
        column: {"expected": expected, "actual": str(rollup[column].dtype)}
        for column, expected in ROLLUP_DTYPES.items()
        if str(rollup[column].dtype) != expected
    }
    if wrong_dtypes:
        raise MergeContractError(
            f"order_rollup must satisfy the 03/05 dtype contract: {wrong_dtypes}"
        )
    return rollup


def attach_order_rollup(
    orders: pd.DataFrame,
    order_rollup: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Attach the typed 03/05 rollup while preserving one row per order."""

    orders_frame = _validate_frame(orders, label="orders", keys=["order_id"])
    if str(orders_frame["order_id"].dtype) != "string":
        raise MergeContractError("orders.order_id must already have dtype string")
    rollup_frame = _validate_order_rollup(order_rollup)

    merged, report = merge_with_contract(
        orders_frame,
        rollup_frame,
        on=["order_id"],
        how="left",
        validate="one_to_one",
        indicator="items_match",
    )
    if report["right_only_key_count"]:
        raise MergeContractError(
            "order_rollup references unknown orders: "
            f"{report['right_only_key_examples']}"
        )
    if len(merged) != len(orders_frame) or merged["order_id"].duplicated().any():
        raise MergeContractError("result grain must remain one row per order_id")

    expected_left = orders_frame.reset_index(drop=True)
    actual_left = merged.loc[:, orders_frame.columns].reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(actual_left, expected_left)
    except AssertionError as error:
        raise MergeContractError("left-table values changed during merge") from error

    report["target_grain"] = "one row per order_id"
    report["grain_preserved"] = True
    report["left_values_preserved"] = True
    return merged, report
