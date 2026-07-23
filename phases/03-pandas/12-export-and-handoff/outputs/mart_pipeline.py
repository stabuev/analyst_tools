from __future__ import annotations

from typing import Any

import pandas as pd

if __package__:
    from .mart_contracts import (
        ITEM_CATEGORIES,
        OUTPUT_COLUMNS,
        PLAN_CATEGORIES,
        STATUS_CATEGORIES,
        MartContractError,
        assert_unique_nonblank,
        canonical_identifier,
        categorize,
        examples,
        parse_aware_utc,
        require_columns,
        strict_numeric,
    )
else:
    from mart_contracts import (
        ITEM_CATEGORIES,
        OUTPUT_COLUMNS,
        PLAN_CATEGORIES,
        STATUS_CATEGORIES,
        MartContractError,
        assert_unique_nonblank,
        canonical_identifier,
        categorize,
        examples,
        parse_aware_utc,
        require_columns,
        strict_numeric,
    )


def prepare_users(users: pd.DataFrame) -> pd.DataFrame:
    """Prepare the user dimension with a stable plan vocabulary."""

    stage = "prepare_users"
    if not isinstance(users, pd.DataFrame):
        raise MartContractError(f"{stage}: expected a pandas DataFrame")
    require_columns(users, {"user_id", "country", "plan"}, stage=stage)
    result = users.copy(deep=True).assign(
        user_id=lambda value: canonical_identifier(value["user_id"]),
    )
    assert_unique_nonblank(result, ["user_id"], stage=stage)

    country = (
        result["country"]
        .astype("string")
        .str.normalize("NFKC")
        .str.strip()
        .str.upper()
    )
    country = country.mask(country.eq("").fillna(False), pd.NA)
    invalid_country = country.notna() & ~country.str.fullmatch(
        r"[A-Z]{2}",
        na=False,
    )
    if invalid_country.any():
        raise MartContractError(
            f"{stage}: invalid country codes: "
            f"{examples(country, invalid_country)}"
        )

    plan = categorize(
        result["plan"],
        categories=PLAN_CATEGORIES,
        stage=f"{stage}.plan",
    )
    return result.assign(
        country=country.astype("string"),
        plan=plan,
    )


def _prepare_order_identity(orders: pd.DataFrame) -> pd.DataFrame:
    stage = "prepare_orders.identity"
    required = {
        "order_id",
        "user_id",
        "ordered_at",
        "status",
        "currency",
        "amount",
    }
    require_columns(orders, required, stage=stage)
    result = orders.assign(
        order_id=lambda value: canonical_identifier(value["order_id"]),
        user_id=lambda value: canonical_identifier(value["user_id"]),
    )
    assert_unique_nonblank(result, ["order_id"], stage=stage)
    if result["user_id"].isna().any():
        raise MartContractError(f"{stage}: user_id must be non-missing and non-blank")
    return result


def _normalize_order_fields(orders: pd.DataFrame) -> pd.DataFrame:
    stage = "prepare_orders.fields"
    status = categorize(
        orders["status"],
        categories=STATUS_CATEGORIES,
        stage=f"{stage}.status",
    )
    currency = (
        orders["currency"]
        .astype("string")
        .str.normalize("NFKC")
        .str.strip()
        .str.upper()
    )
    currency = currency.mask(currency.eq("").fillna(False), pd.NA)
    missing_currency = currency.isna()
    invalid_currency = currency.notna() & ~currency.str.fullmatch(
        r"[A-Z]{3}",
        na=False,
    )
    if missing_currency.any():
        raise MartContractError(
            f"{stage}.currency: value must be non-missing and non-blank"
        )
    if invalid_currency.any():
        raise MartContractError(
            f"{stage}.currency: invalid codes: "
            f"{examples(currency, invalid_currency)}"
        )
    amount = strict_numeric(
        orders["amount"],
        dtype="Float64",
        nullable=True,
        stage=f"{stage}.amount",
    )
    return orders.assign(
        status=status,
        currency=currency.astype("string"),
        amount=amount,
    )


def _add_order_time(
    orders: pd.DataFrame,
    *,
    business_timezone: str,
) -> pd.DataFrame:
    stage = "prepare_orders.time"
    ordered_at_utc = parse_aware_utc(orders["ordered_at"], stage=stage)
    try:
        local = ordered_at_utc.dt.tz_convert(business_timezone)
    except (TypeError, ValueError, KeyError) as error:
        raise MartContractError(
            f"{stage}: invalid business timezone: {business_timezone}"
        ) from error
    local_order_date = local.dt.strftime("%Y-%m-%d").astype("string")
    return orders.assign(
        ordered_at_utc=ordered_at_utc,
        local_order_date=local_order_date,
    )


def _add_paid_metrics(orders: pd.DataFrame) -> pd.DataFrame:
    stage = "prepare_orders.paid_metrics"
    is_paid = orders["status"].eq("paid").astype("boolean")
    missing_paid_amount = is_paid & orders["amount"].isna()
    if missing_paid_amount.any():
        raise MartContractError(
            f"{stage}: paid orders need amount: "
            f"{examples(orders['order_id'], missing_paid_amount)}"
        )
    return orders.assign(
        is_paid=is_paid,
        paid_amount=orders["amount"].where(is_paid, 0).astype("Float64"),
    )


def prepare_orders(
    orders: pd.DataFrame,
    *,
    business_timezone: str,
) -> pd.DataFrame:
    """Compose the checked order stages introduced in lesson 03/11."""

    if not isinstance(orders, pd.DataFrame):
        raise MartContractError("prepare_orders: expected a pandas DataFrame")
    source = orders.copy(deep=True)
    source_index = source.index.copy()
    result = (
        source.pipe(_prepare_order_identity)
        .pipe(_normalize_order_fields)
        .pipe(_add_order_time, business_timezone=business_timezone)
        .pipe(_add_paid_metrics)
    )
    if len(result) != len(source) or not result.index.equals(source_index):
        raise MartContractError(
            "prepare_orders: preserving stages changed rows or their order"
        )
    return result


def _join_categories(values: pd.Series) -> str:
    present = set(str(value) for value in values.dropna().tolist())
    return "|".join(
        category for category in ITEM_CATEGORIES if category in present
    )


def prepare_item_totals(items: pd.DataFrame) -> pd.DataFrame:
    """Normalize item rows and apply the stricter delivery aggregation policy."""

    stage = "prepare_item_totals"
    if not isinstance(items, pd.DataFrame):
        raise MartContractError(f"{stage}: expected a pandas DataFrame")
    required = {
        "order_id",
        "product_id",
        "category",
        "quantity",
        "unit_price",
    }
    require_columns(items, required, stage=stage)
    result = items.copy(deep=True).assign(
        order_id=lambda value: canonical_identifier(value["order_id"]),
        product_id=lambda value: canonical_identifier(value["product_id"]),
    )
    assert_unique_nonblank(
        result,
        ["order_id", "product_id"],
        stage=stage,
    )

    quantity = strict_numeric(
        result["quantity"],
        dtype="Int64",
        nullable=False,
        stage=f"{stage}.quantity",
    )
    unit_price = strict_numeric(
        result["unit_price"],
        dtype="Float64",
        nullable=False,
        stage=f"{stage}.unit_price",
    )
    if quantity.le(0).any():
        raise MartContractError(f"{stage}.quantity: values must be positive")
    if unit_price.lt(0).any():
        raise MartContractError(f"{stage}.unit_price: values must be non-negative")

    category = categorize(
        result["category"],
        categories=ITEM_CATEGORIES,
        aliases={"addon": "add_on"},
        stage=f"{stage}.category",
    )
    prepared = result.assign(
        category=category,
        quantity=quantity,
        unit_price=unit_price,
        line_total=quantity.astype("Float64").mul(unit_price),
    )
    totals = prepared.groupby(
        "order_id",
        as_index=False,
        observed=True,
    ).agg(
        item_rows=("product_id", "size"),
        item_total=("line_total", lambda values: values.sum(min_count=1)),
        categories=("category", _join_categories),
    )
    totals = totals.assign(
        order_id=lambda value: value["order_id"].astype("string"),
        item_rows=lambda value: value["item_rows"].astype("Int64"),
        item_total=lambda value: value["item_total"].astype("Float64"),
        categories=lambda value: value["categories"].astype("string"),
    )
    assert_unique_nonblank(totals, ["order_id"], stage="item_totals")
    return totals


def _warning_check(
    *,
    count: int,
    examples_list: list[str],
    message: str,
) -> dict[str, Any]:
    return {
        "status": "warning" if count else "pass",
        "count": count,
        "examples": examples_list,
        "message": message,
    }


def build_order_mart(
    users: pd.DataFrame,
    orders: pd.DataFrame,
    items: pd.DataFrame,
    *,
    business_timezone: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build a checked one-row-per-order mart and its publish-gate report."""

    prepared_users = prepare_users(users)
    prepared_orders = prepare_orders(
        orders,
        business_timezone=business_timezone,
    )
    item_totals = prepare_item_totals(items)

    known_orders = set(prepared_orders["order_id"].tolist())
    orphan_items = item_totals.loc[
        ~item_totals["order_id"].isin(known_orders),
        "order_id",
    ]
    if not orphan_items.empty:
        raise MartContractError(
            "build_order_mart.items_join: order_items reference unknown orders: "
            f"{orphan_items.tolist()}"
        )

    with_items = prepared_orders.merge(
        item_totals,
        on="order_id",
        how="left",
        validate="one_to_one",
        indicator="items_merge",
    )
    missing_items = with_items["items_merge"].ne("both")
    if missing_items.any():
        raise MartContractError(
            "build_order_mart.items_join: orders have no item rows: "
            f"{examples(with_items['order_id'], missing_items)}"
        )

    mart = with_items.merge(
        prepared_users[["user_id", "country", "plan"]],
        on="user_id",
        how="left",
        validate="many_to_one",
        indicator="user_merge",
    )
    if len(mart) != len(prepared_orders):
        raise MartContractError(
            "build_order_mart.user_join: mart row count differs from orders"
        )
    assert_unique_nonblank(mart, ["order_id"], stage="build_order_mart")

    known_amount = mart["amount"].notna() & mart["item_total"].notna()
    amount_matches_items = (
        mart["amount"]
        .sub(mart["item_total"])
        .abs()
        .le(1e-9)
        .where(known_amount, pd.NA)
        .astype("boolean")
    )
    mismatch = amount_matches_items.eq(False).fillna(False)
    if mismatch.any():
        raise MartContractError(
            "build_order_mart.reconciliation: order amount differs from item total: "
            f"{examples(mart['order_id'], mismatch)}"
        )

    mart = (
        mart.assign(
            user_found=mart["user_merge"].eq("both").astype("boolean"),
            amount_matches_items=amount_matches_items,
        )
        .drop(columns=["items_merge", "user_merge"])
        .loc[:, OUTPUT_COLUMNS]
        .sort_values("order_id", kind="stable")
        .reset_index(drop=True)
    )

    unknown_user = ~mart["user_found"]
    unchecked_amount = mart["amount_matches_items"].isna()
    missing_ordered_at = mart["ordered_at_utc"].isna()
    missing_country = mart["country"].isna()
    checks = {
        "grain": {
            "status": "pass",
            "expected": ["order_id"],
            "rows": len(mart),
            "unique": bool(mart["order_id"].is_unique),
        },
        "rows_equal_orders": {
            "status": "pass",
            "expected": len(prepared_orders),
            "observed": len(mart),
        },
        "amount_reconciliation": {
            "status": "warning" if unchecked_amount.any() else "pass",
            "checked_rows": int((~unchecked_amount).sum()),
            "unchecked_rows": int(unchecked_amount.sum()),
            "mismatches": 0,
            "examples": examples(mart["order_id"], unchecked_amount),
        },
        "unknown_users": _warning_check(
            count=int(unknown_user.sum()),
            examples_list=examples(mart["user_id"], unknown_user),
            message="Orders are preserved and marked with user_found=false.",
        ),
        "missing_ordered_at": _warning_check(
            count=int(missing_ordered_at.sum()),
            examples_list=examples(mart["order_id"], missing_ordered_at),
            message="Missing source timestamps remain missing.",
        ),
        "missing_country": _warning_check(
            count=int(missing_country.sum()),
            examples_list=examples(mart["order_id"], missing_country),
            message="Country may be missing for a known or unmatched user.",
        ),
    }
    has_warnings = any(
        check["status"] == "warning" for check in checks.values()
    )
    quality = {
        "publish_status": "passed_with_warnings" if has_warnings else "passed",
        "checks": checks,
    }
    return mart, quality
