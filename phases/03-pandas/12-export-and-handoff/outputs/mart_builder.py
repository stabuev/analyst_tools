from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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


def sha256(path: Path) -> str:
    """Return a SHA-256 digest for the exact bytes stored at path."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    *,
    stage: str,
) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise MartContractError(f"{stage}: missing columns: {missing}")


def _examples(series: pd.Series, mask: pd.Series) -> list[str]:
    values = series.loc[mask].astype("string").dropna().unique().tolist()
    return [str(value) for value in values[:5]]


def _canonical_identifier(series: pd.Series) -> pd.Series:
    result = series.astype("string").str.normalize("NFKC").str.strip()
    return result.mask(result.eq("").fillna(False), pd.NA)


def _assert_unique_nonblank(
    frame: pd.DataFrame,
    keys: Sequence[str],
    *,
    stage: str,
) -> None:
    _require_columns(frame, set(keys), stage=stage)
    missing_key = frame[list(keys)].isna().any(axis=1)
    if missing_key.any():
        raise MartContractError(
            f"{stage}: keys must be non-missing and non-blank: {list(keys)}"
        )
    duplicate = frame.duplicated(list(keys), keep=False)
    if duplicate.any():
        examples = [
            tuple(str(value) for value in row)
            for row in frame.loc[duplicate, list(keys)].head(5).itertuples(
                index=False,
                name=None,
            )
        ]
        raise MartContractError(
            f"{stage}: keys are not unique: {list(keys)}; examples: {examples}"
        )


def _normalize_text(
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


def _categorize(
    series: pd.Series,
    *,
    categories: Sequence[str],
    stage: str,
    aliases: dict[str, str] | None = None,
) -> pd.Series:
    normalized = _normalize_text(series, separators=True)
    if aliases:
        normalized = normalized.replace(aliases)
    if normalized.isna().any():
        raise MartContractError(f"{stage}: category must be non-missing and non-blank")
    unknown = ~normalized.isin(categories)
    if unknown.any():
        raise MartContractError(
            f"{stage}: unknown categories: {_examples(normalized, unknown)}"
        )
    dtype = pd.CategoricalDtype(categories=list(categories), ordered=False)
    return normalized.astype(dtype)


def _strict_numeric(
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
            f"{stage}: invalid numeric values: {_examples(source, invalid)}"
        )
    if missing.any() and not nullable:
        raise MartContractError(f"{stage}: numeric value must be non-missing")
    if dtype == "Int64":
        fractional = parsed.notna() & parsed.mod(1).ne(0)
        if fractional.any():
            raise MartContractError(
                f"{stage}: expected integer values: {_examples(source, fractional)}"
            )
    return parsed.astype(dtype)


def _parse_aware_utc(series: pd.Series, *, stage: str) -> pd.Series:
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
            f"{stage}: invalid timestamps: {_examples(source, invalid)}"
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
            f"{_examples(source, naive)}"
        )
    return parsed.astype(pd.DatetimeTZDtype(unit="ns", tz="UTC"))


def prepare_users(users: pd.DataFrame) -> pd.DataFrame:
    """Prepare the user dimension with a stable plan vocabulary."""

    stage = "prepare_users"
    if not isinstance(users, pd.DataFrame):
        raise MartContractError(f"{stage}: expected a pandas DataFrame")
    _require_columns(users, {"user_id", "country", "plan"}, stage=stage)
    result = users.copy(deep=True).assign(
        user_id=lambda value: _canonical_identifier(value["user_id"]),
    )
    _assert_unique_nonblank(result, ["user_id"], stage=stage)

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
            f"{_examples(country, invalid_country)}"
        )

    plan = _categorize(
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
    _require_columns(orders, required, stage=stage)
    result = orders.assign(
        order_id=lambda value: _canonical_identifier(value["order_id"]),
        user_id=lambda value: _canonical_identifier(value["user_id"]),
    )
    _assert_unique_nonblank(result, ["order_id"], stage=stage)
    if result["user_id"].isna().any():
        raise MartContractError(f"{stage}: user_id must be non-missing and non-blank")
    return result


def _normalize_order_fields(orders: pd.DataFrame) -> pd.DataFrame:
    stage = "prepare_orders.fields"
    status = _categorize(
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
            f"{_examples(currency, invalid_currency)}"
        )
    amount = _strict_numeric(
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
    ordered_at_utc = _parse_aware_utc(orders["ordered_at"], stage=stage)
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
            f"{_examples(orders['order_id'], missing_paid_amount)}"
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
    """Run the strict order pipeline from lesson 03/11 inside the mart build."""

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
    """Normalize line items and aggregate them to one row per order."""

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
    _require_columns(items, required, stage=stage)
    result = items.copy(deep=True).assign(
        order_id=lambda value: _canonical_identifier(value["order_id"]),
        product_id=lambda value: _canonical_identifier(value["product_id"]),
    )
    _assert_unique_nonblank(
        result,
        ["order_id", "product_id"],
        stage=stage,
    )

    quantity = _strict_numeric(
        result["quantity"],
        dtype="Int64",
        nullable=False,
        stage=f"{stage}.quantity",
    )
    unit_price = _strict_numeric(
        result["unit_price"],
        dtype="Float64",
        nullable=False,
        stage=f"{stage}.unit_price",
    )
    if quantity.le(0).any():
        raise MartContractError(f"{stage}.quantity: values must be positive")
    if unit_price.lt(0).any():
        raise MartContractError(f"{stage}.unit_price: values must be non-negative")

    category = _categorize(
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
    _assert_unique_nonblank(totals, ["order_id"], stage="item_totals")
    return totals


def _warning_check(
    *,
    count: int,
    examples: list[str],
    message: str,
) -> dict[str, Any]:
    return {
        "status": "warning" if count else "pass",
        "count": count,
        "examples": examples,
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
            f"{_examples(with_items['order_id'], missing_items)}"
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
    _assert_unique_nonblank(mart, ["order_id"], stage="build_order_mart")

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
            f"{_examples(mart['order_id'], mismatch)}"
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
            "examples": _examples(mart["order_id"], unchecked_amount),
        },
        "unknown_users": _warning_check(
            count=int(unknown_user.sum()),
            examples=_examples(mart["user_id"], unknown_user),
            message="Orders are preserved and marked with user_found=false.",
        ),
        "missing_ordered_at": _warning_check(
            count=int(missing_ordered_at.sum()),
            examples=_examples(mart["order_id"], missing_ordered_at),
            message="Missing source timestamps remain missing.",
        ),
        "missing_country": _warning_check(
            count=int(missing_country.sum()),
            examples=_examples(mart["order_id"], missing_country),
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


def _validate_source_paths(source_paths: dict[str, Path]) -> dict[str, Path]:
    if set(source_paths) != set(SOURCE_NAMES):
        raise MartContractError(
            f"export_delivery: expected source paths {list(SOURCE_NAMES)}"
        )
    normalized = {name: Path(source_paths[name]) for name in SOURCE_NAMES}
    for name, path in normalized.items():
        if not path.is_file():
            raise MartContractError(
                f"export_delivery: source file does not exist: {name}={path}"
            )
    return normalized


def _validate_publish_gate(quality: dict[str, Any]) -> None:
    if not isinstance(quality, dict):
        raise MartContractError("export_delivery: quality report is missing")
    status = quality.get("publish_status")
    if status not in {"passed", "passed_with_warnings"}:
        raise MartContractError(
            f"export_delivery: publish gate is not open: {status!r}"
        )
    checks = quality.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise MartContractError("export_delivery: quality checks are missing")
    invalid_statuses = [
        check.get("status")
        for check in checks.values()
        if check.get("status") not in {"pass", "warning"}
    ]
    if invalid_statuses:
        raise MartContractError(
            "export_delivery: invalid check statuses: "
            f"{sorted(repr(value) for value in invalid_statuses)}"
        )
    expected_status = (
        "passed_with_warnings"
        if any(check["status"] == "warning" for check in checks.values())
        else "passed"
    )
    if status != expected_status:
        raise MartContractError(
            "export_delivery: publish status is inconsistent with checks"
        )


def export_delivery(
    mart: pd.DataFrame,
    quality: dict[str, Any],
    output_dir: Path,
    source_paths: dict[str, Path],
    *,
    business_timezone: str,
) -> dict[str, Any]:
    """Write a deterministic CSV and versioned manifest, then verify the package."""

    _validate_publish_gate(quality)
    if mart.columns.tolist() != OUTPUT_COLUMNS:
        raise MartContractError(
            "export_delivery: mart columns do not match order_mart/v1"
        )
    _assert_unique_nonblank(mart, ["order_id"], stage="export_delivery")
    if mart["order_id"].tolist() != sorted(mart["order_id"].tolist()):
        raise MartContractError("export_delivery: mart order is not deterministic")
    grain_check = quality["checks"].get("grain")
    rows_check = quality["checks"].get("rows_equal_orders")
    if (
        not isinstance(grain_check, dict)
        or grain_check.get("expected") != ["order_id"]
        or grain_check.get("rows") != len(mart)
        or grain_check.get("unique") is not True
    ):
        raise MartContractError(
            "export_delivery: grain check does not describe the mart"
        )
    if (
        not isinstance(rows_check, dict)
        or rows_check.get("observed") != len(mart)
    ):
        raise MartContractError(
            "export_delivery: row-count check does not describe the mart"
        )
    normalized_sources = _validate_source_paths(source_paths)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    mart_path = output_dir / "order_mart.csv"
    manifest_path = output_dir / "manifest.json"
    mart.to_csv(
        mart_path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        na_rep="",
        date_format="%Y-%m-%dT%H:%M:%SZ",
        float_format="%.10g",
    )

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "builder": {
            "name": BUILDER_NAME,
            "version": BUILDER_VERSION,
        },
        "parameters": {
            "business_timezone": business_timezone,
            "unknown_user_policy": "keep_and_flag",
            "amount_mismatch_policy": "block",
        },
        "publish_status": quality["publish_status"],
        "dataset": {
            "name": "order_mart",
            "grain": ["order_id"],
            "rows": len(mart),
            "schema": OUTPUT_SCHEMA,
        },
        "quality": quality,
        "artifact": {
            "path": mart_path.name,
            "format": "csv",
            "encoding": "utf-8",
            "delimiter": ",",
            "line_terminator": "LF",
            "na_rep": "",
            "sha256": sha256(mart_path),
        },
        "sources": {
            name: {
                "path": str(path),
                "sha256": sha256(path),
            }
            for name, path in normalized_sources.items()
        },
    }
    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    verify_delivery(output_dir)
    return manifest


def verify_delivery(output_dir: Path) -> dict[str, Any]:
    """Verify the delivery package from a recipient's point of view."""

    output_dir = Path(output_dir)
    manifest_path = output_dir / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MartContractError(
            f"verify_delivery: cannot read manifest: {error}"
        ) from error

    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise MartContractError("verify_delivery: unsupported manifest version")
    if manifest.get("dataset_schema_version") != DATASET_SCHEMA_VERSION:
        raise MartContractError("verify_delivery: unsupported dataset schema version")
    if manifest.get("publish_status") not in {
        "passed",
        "passed_with_warnings",
    }:
        raise MartContractError("verify_delivery: package was not published")

    parameters = manifest.get("parameters")
    if (
        not isinstance(parameters, dict)
        or not isinstance(parameters.get("business_timezone"), str)
        or not parameters["business_timezone"].strip()
        or parameters.get("unknown_user_policy") != "keep_and_flag"
        or parameters.get("amount_mismatch_policy") != "block"
    ):
        raise MartContractError("verify_delivery: build parameters are invalid")

    artifact = manifest.get("artifact")
    if not isinstance(artifact, dict):
        raise MartContractError("verify_delivery: artifact metadata is missing")
    if (
        artifact.get("format") != "csv"
        or artifact.get("encoding") != "utf-8"
        or artifact.get("delimiter") != ","
        or artifact.get("line_terminator") != "LF"
        or artifact.get("na_rep") != ""
    ):
        raise MartContractError("verify_delivery: CSV representation is invalid")
    artifact_name = artifact.get("path")
    if not isinstance(artifact_name, str) or Path(artifact_name).name != artifact_name:
        raise MartContractError("verify_delivery: artifact path must be a file name")
    mart_path = output_dir / artifact_name
    if not mart_path.is_file():
        raise MartContractError("verify_delivery: artifact file is missing")
    actual_digest = sha256(mart_path)
    if actual_digest != artifact.get("sha256"):
        raise MartContractError("verify_delivery: artifact checksum mismatch")

    dataset = manifest.get("dataset")
    if not isinstance(dataset, dict):
        raise MartContractError("verify_delivery: dataset contract is missing")
    if dataset.get("name") != "order_mart" or dataset.get("grain") != ["order_id"]:
        raise MartContractError("verify_delivery: dataset identity or grain is invalid")
    schema = dataset.get("schema")
    if schema != OUTPUT_SCHEMA:
        raise MartContractError("verify_delivery: dataset schema is invalid")
    expected_columns = OUTPUT_COLUMNS

    try:
        delivered = pd.read_csv(
            mart_path,
            dtype="string",
            keep_default_na=False,
            encoding=artifact.get("encoding", "utf-8"),
        )
    except (OSError, ValueError) as error:
        raise MartContractError(
            f"verify_delivery: cannot read artifact: {error}"
        ) from error
    if delivered.columns.tolist() != expected_columns:
        raise MartContractError("verify_delivery: CSV columns differ from manifest")
    if len(delivered) != dataset.get("rows"):
        raise MartContractError("verify_delivery: CSV row count differs from manifest")

    order_id = delivered["order_id"].str.strip()
    if order_id.eq("").any() or order_id.duplicated().any():
        raise MartContractError("verify_delivery: delivered grain is invalid")
    if order_id.tolist() != sorted(order_id.tolist()):
        raise MartContractError("verify_delivery: delivered order is not deterministic")

    quality = manifest.get("quality")
    if not isinstance(quality, dict) or quality.get("publish_status") != manifest.get(
        "publish_status"
    ):
        raise MartContractError("verify_delivery: quality status is inconsistent")
    try:
        _validate_publish_gate(quality)
    except MartContractError as error:
        raise MartContractError(
            f"verify_delivery: quality report is invalid: {error}"
        ) from error
    grain_check = quality["checks"].get("grain")
    rows_check = quality["checks"].get("rows_equal_orders")
    if (
        not isinstance(grain_check, dict)
        or grain_check.get("rows") != len(delivered)
        or grain_check.get("expected") != ["order_id"]
        or grain_check.get("unique") is not True
        or not isinstance(rows_check, dict)
        or rows_check.get("observed") != len(delivered)
    ):
        raise MartContractError(
            "verify_delivery: quality evidence differs from delivered data"
        )

    return {
        "valid": True,
        "manifest_version": manifest["manifest_version"],
        "dataset_schema_version": manifest["dataset_schema_version"],
        "publish_status": manifest["publish_status"],
        "rows": len(delivered),
        "grain": ["order_id"],
        "artifact_sha256": actual_digest,
    }


def _read_raw_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(
        path,
        dtype="string",
        keep_default_na=False,
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or independently verify a checked order-mart delivery"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build and export the delivery")
    build.add_argument("--users", type=Path, required=True)
    build.add_argument("--orders", type=Path, required=True)
    build.add_argument("--items", type=Path, required=True)
    build.add_argument("--output-dir", type=Path, required=True)
    build.add_argument("--business-timezone", required=True)

    verify = commands.add_parser("verify", help="verify an existing delivery")
    verify.add_argument("--output-dir", type=Path, required=True)
    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            report = verify_delivery(args.output_dir)
        else:
            source_paths = {
                "users": args.users,
                "orders": args.orders,
                "order_items": args.items,
            }
            mart, quality = build_order_mart(
                _read_raw_csv(args.users),
                _read_raw_csv(args.orders),
                _read_raw_csv(args.items),
                business_timezone=args.business_timezone,
            )
            manifest = export_delivery(
                mart,
                quality,
                args.output_dir,
                source_paths,
                business_timezone=args.business_timezone,
            )
            report = {
                "valid": True,
                "publish_status": manifest["publish_status"],
                "rows": manifest["dataset"]["rows"],
                "output_dir": str(args.output_dir),
                "artifact_sha256": manifest["artifact"]["sha256"],
            }
    except (OSError, MartContractError) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
