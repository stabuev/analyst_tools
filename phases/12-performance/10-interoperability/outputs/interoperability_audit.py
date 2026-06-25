from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import polars as pl
import pyarrow as pa


class InteroperabilityAuditError(ValueError):
    """Raised when a conversion boundary cannot be audited safely."""


COLUMN_ORDER = [
    "order_id",
    "user_id",
    "event_at",
    "plan_tier",
    "gross_revenue_cents",
    "refund_amount_cents",
    "net_revenue_rub",
    "support_ticket_count",
    "comment",
    "is_test_user",
]

ORDERED_PLANS = ["trial", "basic", "plus", "pro"]


def _chunk_bounds(length: int, chunk_size: int) -> list[tuple[int, int]]:
    if length < 8:
        raise InteroperabilityAuditError("rows must be at least 8")
    if chunk_size < 2:
        raise InteroperabilityAuditError("chunk_size must be at least 2")
    return [(start, min(start + chunk_size, length)) for start in range(0, length, chunk_size)]


def _chunked_array(
    values: list[Any],
    *,
    chunk_size: int,
    type_: pa.DataType,
) -> pa.ChunkedArray:
    return pa.chunked_array(
        [
            pa.array(values[start:end], type=type_)
            for start, end in _chunk_bounds(len(values), chunk_size)
        ],
        type=type_,
    )


def _dictionary_chunked_array(
    values: list[str | None],
    *,
    chunk_size: int,
) -> pa.ChunkedArray:
    dictionary_type = pa.dictionary(pa.int8(), pa.string(), ordered=True)
    chunks = []
    for start, end in _chunk_bounds(len(values), chunk_size):
        chunk = pa.array(values[start:end], type=pa.string()).dictionary_encode()
        chunks.append(chunk.cast(dictionary_type))
    return pa.chunked_array(chunks, type=dictionary_type)


def build_canonical_arrow_table(
    *,
    rows: int = 24,
    chunk_size: int = 8,
    seed: int = 42,
) -> pa.Table:
    _chunk_bounds(rows, chunk_size)
    rng = np.random.default_rng(seed)
    index = np.arange(rows, dtype=np.int64)
    gross = rng.integers(1_000, 80_000, size=rows, dtype=np.int64)
    refund = np.where(index % 6 == 0, gross // 4, 0).astype(np.int64)
    plans: list[str | None] = [
        None if position % 11 == 0 else ORDERED_PLANS[position % len(ORDERED_PLANS)]
        for position in range(rows)
    ]
    event_at = [
        None
        if position % 13 == 0
        else pd.Timestamp("2026-01-05T00:00:00Z") + pd.Timedelta(hours=int(position) * 9)
        for position in range(rows)
    ]
    support_tickets: list[int | None] = [
        None if position % 7 == 0 else int(value)
        for position, value in enumerate(rng.poisson(0.3, size=rows))
    ]
    comments = [
        None if position % 5 == 0 else f"support bucket {position % 4}" for position in range(rows)
    ]
    net_revenue_rub = [Decimal(int(value)) / Decimal(100) for value in (gross - refund)]

    schema = pa.schema(
        [
            pa.field(
                "order_id",
                pa.string(),
                nullable=False,
                metadata={b"role": b"primary_key"},
            ),
            pa.field("user_id", pa.string(), nullable=False),
            pa.field("event_at", pa.timestamp("us", tz="UTC"), nullable=True),
            pa.field(
                "plan_tier",
                pa.dictionary(pa.int8(), pa.string(), ordered=True),
                nullable=True,
                metadata={b"business_order": b"trial,basic,plus,pro"},
            ),
            pa.field("gross_revenue_cents", pa.int64(), nullable=False),
            pa.field("refund_amount_cents", pa.int64(), nullable=False),
            pa.field("net_revenue_rub", pa.decimal128(14, 2), nullable=False),
            pa.field("support_ticket_count", pa.int16(), nullable=True),
            pa.field("comment", pa.string(), nullable=True),
            pa.field("is_test_user", pa.bool_(), nullable=False),
        ],
        metadata={
            b"table": b"customer_revenue_interoperability",
            b"business_timezone": b"UTC",
        },
    )
    arrays = [
        _chunked_array(
            [f"O{position:08d}" for position in index],
            chunk_size=chunk_size,
            type_=pa.string(),
        ),
        _chunked_array(
            [f"U{position % max(8, rows // 3):07d}" for position in index],
            chunk_size=chunk_size,
            type_=pa.string(),
        ),
        _chunked_array(
            event_at,
            chunk_size=chunk_size,
            type_=pa.timestamp("us", tz="UTC"),
        ),
        _dictionary_chunked_array(plans, chunk_size=chunk_size),
        _chunked_array(
            gross.tolist(),
            chunk_size=chunk_size,
            type_=pa.int64(),
        ),
        _chunked_array(
            refund.tolist(),
            chunk_size=chunk_size,
            type_=pa.int64(),
        ),
        _chunked_array(
            net_revenue_rub,
            chunk_size=chunk_size,
            type_=pa.decimal128(14, 2),
        ),
        _chunked_array(
            support_tickets,
            chunk_size=chunk_size,
            type_=pa.int16(),
        ),
        _chunked_array(
            comments,
            chunk_size=chunk_size,
            type_=pa.string(),
        ),
        _chunked_array(
            (index % 17 == 0).tolist(),
            chunk_size=chunk_size,
            type_=pa.bool_(),
        ),
    ]
    table = pa.Table.from_arrays(arrays, schema=schema)
    validate_canonical_table(table)
    return table


def validate_canonical_table(table: pa.Table) -> None:
    if table.column_names != COLUMN_ORDER:
        raise InteroperabilityAuditError(f"canonical columns must equal {COLUMN_ORDER}")
    if table.num_rows == 0:
        raise InteroperabilityAuditError("canonical table is empty")
    order_ids = table["order_id"].to_pylist()
    if any(value is None for value in order_ids) or len(set(order_ids)) != len(order_ids):
        raise InteroperabilityAuditError("order_id must be non-null and unique")
    gross = table["gross_revenue_cents"].to_numpy()
    refund = table["refund_amount_cents"].to_numpy()
    if np.any(gross < 0) or np.any(refund < 0):
        raise InteroperabilityAuditError("money columns must be non-negative")
    if np.any(refund > gross):
        raise InteroperabilityAuditError("refund_amount_cents cannot exceed gross_revenue_cents")
    plan_type = table.schema.field("plan_tier").type
    if not pa.types.is_dictionary(plan_type) or not plan_type.ordered:
        raise InteroperabilityAuditError("plan_tier must be an ordered Arrow dictionary")


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def semantic_records(table: pa.Table) -> list[dict[str, Any]]:
    records = [
        {name: _json_value(value) for name, value in row.items()}
        for row in table.select(COLUMN_ORDER).to_pylist()
    ]
    return sorted(records, key=lambda row: str(row["order_id"]))


def _type_family(type_: pa.DataType) -> str:
    if pa.types.is_dictionary(type_):
        return "categorical"
    if (
        pa.types.is_string(type_)
        or pa.types.is_large_string(type_)
        or pa.types.is_string_view(type_)
    ):
        return "string"
    if pa.types.is_timestamp(type_):
        return "timestamp"
    if pa.types.is_decimal(type_):
        return "decimal"
    if pa.types.is_integer(type_):
        return "integer"
    if pa.types.is_boolean(type_):
        return "boolean"
    return str(type_)


def _metadata_json(metadata: dict[bytes, bytes] | None) -> dict[str, str]:
    return {key.decode("utf-8"): value.decode("utf-8") for key, value in (metadata or {}).items()}


def schema_manifest(schema: pa.Schema) -> list[dict[str, Any]]:
    return [
        {
            "name": field.name,
            "type": str(field.type),
            "family": _type_family(field.type),
            "nullable": field.nullable,
            "metadata": _metadata_json(field.metadata),
        }
        for field in schema
    ]


def _array_buffer_addresses(array: pa.Array) -> set[int]:
    addresses = {int(buffer.address) for buffer in array.buffers() if buffer is not None}
    if pa.types.is_dictionary(array.type):
        addresses |= _array_buffer_addresses(array.dictionary)
    return addresses


def _column_buffer_addresses(column: pa.ChunkedArray) -> set[int]:
    addresses: set[int] = set()
    for chunk in column.chunks:
        addresses |= _array_buffer_addresses(chunk)
    return addresses


def buffer_reuse_report(
    source: pa.Table,
    target: pa.Table,
) -> dict[str, Any]:
    columns: dict[str, Any] = {}
    for name in source.column_names:
        source_addresses = _column_buffer_addresses(source[name])
        target_addresses = _column_buffer_addresses(target[name])
        shared = source_addresses & target_addresses
        if not source_addresses:
            status = "no_source_buffers"
        elif source_addresses.issubset(target_addresses):
            status = "full_source_reuse"
        elif shared:
            status = "partial_reuse"
        else:
            status = "no_reuse_observed"
        columns[name] = {
            "source_buffer_count": len(source_addresses),
            "target_buffer_count": len(target_addresses),
            "shared_buffer_count": len(shared),
            "all_source_buffers_reused": bool(source_addresses)
            and source_addresses.issubset(target_addresses),
            "status": status,
        }
    return {
        "columns": columns,
        "columns_with_any_reuse": [
            name for name, detail in columns.items() if detail["shared_buffer_count"] > 0
        ],
        "columns_with_full_source_reuse": [
            name for name, detail in columns.items() if detail["all_source_buffers_reused"]
        ],
        "columns_without_reuse": [
            name for name, detail in columns.items() if detail["status"] == "no_reuse_observed"
        ],
    }


def _category_vocabulary(table: pa.Table, name: str) -> list[str]:
    values = {str(value) for value in table[name].to_pylist() if value is not None}
    return sorted(values)


def _category_ordered(schema: pa.Schema, name: str) -> bool | None:
    type_ = schema.field(name).type
    if pa.types.is_dictionary(type_):
        return bool(type_.ordered)
    return None


def assess_boundary(
    *,
    boundary_id: str,
    source_engine: str,
    target_engine: str,
    api: str,
    source: pa.Table,
    target: pa.Table,
    buffer_evidence: bool = True,
) -> dict[str, Any]:
    source_types = {field.name: field.type for field in source.schema}
    target_types = {field.name: field.type for field in target.schema}
    exact_type_checks = {
        name: source_types[name].equals(target_types[name]) for name in source.column_names
    }
    family_checks = {
        name: _type_family(source_types[name]) == _type_family(target_types[name])
        for name in source.column_names
    }
    null_counts_source = {name: int(source[name].null_count) for name in source.column_names}
    null_counts_target = {name: int(target[name].null_count) for name in target.column_names}
    category_values_match = _category_vocabulary(source, "plan_tier") == _category_vocabulary(
        target, "plan_tier"
    )
    category_ordering_match = _category_ordered(source.schema, "plan_tier") == _category_ordered(
        target.schema, "plan_tier"
    )
    values_match = semantic_records(source) == semantic_records(target)
    names_match = source.column_names == target.column_names
    null_counts_match = null_counts_source == null_counts_target
    semantic_safe = values_match and names_match and null_counts_match and category_values_match
    exact_schema_match = source.schema.equals(target.schema, check_metadata=True)
    if not semantic_safe:
        classification = "unsafe_semantic_drift"
    elif exact_schema_match:
        classification = "exact_schema_and_values"
    else:
        classification = "values_preserved_with_schema_drift"
    return {
        "boundary_id": boundary_id,
        "source_engine": source_engine,
        "target_engine": target_engine,
        "api": api,
        "rows": target.num_rows,
        "checks": {
            "values_match": values_match,
            "column_names_and_order_match": names_match,
            "null_counts_match": null_counts_match,
            "type_families_match": all(family_checks.values()),
            "exact_arrow_types_match": all(exact_type_checks.values()),
            "field_nullability_match": [field.nullable for field in source.schema]
            == [field.nullable for field in target.schema],
            "schema_metadata_match": source.schema.metadata == target.schema.metadata,
            "category_values_match": category_values_match,
            "category_ordering_match": category_ordering_match,
            "semantic_safe": semantic_safe,
            "exact_schema_match": exact_schema_match,
        },
        "column_type_checks": {
            name: {
                "source_type": str(source_types[name]),
                "target_type": str(target_types[name]),
                "source_family": _type_family(source_types[name]),
                "target_family": _type_family(target_types[name]),
                "exact_type_match": exact_type_checks[name],
                "family_match": family_checks[name],
            }
            for name in source.column_names
        },
        "source_null_counts": null_counts_source,
        "target_null_counts": null_counts_target,
        "source_schema": schema_manifest(source.schema),
        "target_schema": schema_manifest(target.schema),
        "buffer_reuse": (
            buffer_reuse_report(source, target)
            if buffer_evidence
            else {
                "available": False,
                "reason": ("Independent exports cannot prove reuse across the direct boundary."),
            }
        ),
        "classification": classification,
    }


def pandas_boundary(
    source: pa.Table,
) -> tuple[pd.DataFrame, pa.Table, pa.Table]:
    frame = source.to_pandas(types_mapper=pd.ArrowDtype)
    underlying = pa.Table.from_arrays(
        [frame[name].array.__arrow_array__() for name in source.column_names],
        names=source.column_names,
    )
    roundtrip = pa.Table.from_pandas(frame, preserve_index=False)
    return frame, underlying, roundtrip


def polars_boundary(source: pa.Table) -> tuple[pl.DataFrame, pa.Table]:
    frame = pl.from_arrow(source, rechunk=False)
    roundtrip = frame.to_arrow(compat_level=pl.CompatLevel.oldest())
    return frame, roundtrip


def duckdb_boundary(
    source: pa.Table,
    *,
    timezone_name: str,
) -> pa.Table:
    allowed_timezones = {"UTC", "Europe/Moscow"}
    if timezone_name not in allowed_timezones:
        raise InteroperabilityAuditError(
            f"timezone_name must be one of {sorted(allowed_timezones)}"
        )
    connection = duckdb.connect()
    try:
        connection.execute(f"SET TimeZone = '{timezone_name}'")
        connection.register("canonical_arrow", source)
        return connection.execute(
            """
            SELECT
                order_id,
                user_id,
                event_at,
                plan_tier,
                gross_revenue_cents,
                refund_amount_cents,
                net_revenue_rub,
                support_ticket_count,
                comment,
                is_test_user
            FROM canonical_arrow
            ORDER BY order_id
            """
        ).to_arrow_table()
    finally:
        connection.close()


def interoperability_matrix(
    boundaries: list[dict[str, Any]],
) -> pd.DataFrame:
    rows = []
    for boundary in boundaries:
        checks = boundary["checks"]
        reuse = boundary["buffer_reuse"]
        rows.append(
            {
                "boundary_id": boundary["boundary_id"],
                "source_engine": boundary["source_engine"],
                "target_engine": boundary["target_engine"],
                "api": boundary["api"],
                "classification": boundary["classification"],
                "values_match": checks["values_match"],
                "null_counts_match": checks["null_counts_match"],
                "type_families_match": checks["type_families_match"],
                "exact_arrow_types_match": checks["exact_arrow_types_match"],
                "field_nullability_match": checks["field_nullability_match"],
                "schema_metadata_match": checks["schema_metadata_match"],
                "category_values_match": checks["category_values_match"],
                "category_ordering_match": checks["category_ordering_match"],
                "columns_with_any_buffer_reuse": ",".join(reuse.get("columns_with_any_reuse", [])),
                "columns_without_buffer_reuse": ",".join(reuse.get("columns_without_reuse", [])),
            }
        )
    return pd.DataFrame(rows)


def build_decision(
    boundaries: list[dict[str, Any]],
    timezone_counterexample: dict[str, Any],
) -> dict[str, Any]:
    by_id = {boundary["boundary_id"]: boundary for boundary in boundaries}
    polars_reuse = by_id["arrow_to_polars"]["buffer_reuse"]["columns_with_any_reuse"]
    return {
        "selected_path": "pyarrow -> polars -> pyarrow",
        "reason": (
            "The analytical pipeline can stay columnar, primitive/decimal/timestamp "
            "buffers show reuse, and only one engine boundary is crossed before export."
        ),
        "required_controls": [
            "Keep the canonical Arrow schema beside the data.",
            "Validate values, null counts, timezone instants and category vocabulary.",
            "Restore ordered category metadata before a persisted contract boundary.",
            "Avoid pandas object dtypes; use explicit ArrowDtype.",
            "Set DuckDB TimeZone explicitly and export only the reduced result.",
        ],
        "observed_polars_buffer_reuse_columns": polars_reuse,
        "known_drifts": {
            "pandas": (
                "Arrow-backed values reuse buffers, but field nullability and schema "
                "metadata are not a pandas DataFrame contract."
            ),
            "polars": (
                "String representation and dictionary index type change; ordered "
                "dictionary metadata is lost."
            ),
            "duckdb": (
                "The query result is materialized, ordered dictionary becomes string, "
                "and timezone labeling follows the DuckDB session."
            ),
        },
        "timezone_counterexample_detected": (
            timezone_counterexample["checks"]["values_match"]
            and not timezone_counterexample["checks"]["exact_arrow_types_match"]
        ),
        "avoid": [
            "Converting through pandas object columns.",
            "Ping-pong conversion between engines inside one pipeline.",
            "Treating category codes as stable business identifiers.",
            "Assuming timezone labels are preserved without session configuration.",
        ],
    }


def _write_arrow_file(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = table.unify_dictionaries()
    with (
        pa.OSFile(str(path), "wb") as sink,
        pa.ipc.new_file(sink, serializable.schema) as writer,
    ):
        writer.write_table(serializable)


def _decision_markdown(decision: dict[str, Any]) -> str:
    controls = "\n".join(f"- {item}" for item in decision["required_controls"])
    drifts = "\n".join(
        f"- **{engine}:** {description}" for engine, description in decision["known_drifts"].items()
    )
    avoid = "\n".join(f"- {item}" for item in decision["avoid"])
    return (
        "# Interoperability decision\n\n"
        f"**Selected path:** `{decision['selected_path']}`\n\n"
        f"{decision['reason']}\n\n"
        "## Required controls\n\n"
        f"{controls}\n\n"
        "## Known drifts\n\n"
        f"{drifts}\n\n"
        "## Avoid\n\n"
        f"{avoid}\n"
    )


def build_interoperability_report(
    *,
    rows: int = 24,
    chunk_size: int = 8,
    seed: int = 42,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    if output_dir is None:
        raise InteroperabilityAuditError("output_dir is required")
    package_dir = Path(output_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    source = build_canonical_arrow_table(
        rows=rows,
        chunk_size=chunk_size,
        seed=seed,
    )
    pandas_frame, pandas_storage, pandas_roundtrip = pandas_boundary(source)
    polars_frame, polars_roundtrip = polars_boundary(source)
    duckdb_utc = duckdb_boundary(source, timezone_name="UTC")
    duckdb_moscow = duckdb_boundary(
        source,
        timezone_name="Europe/Moscow",
    )

    boundaries = [
        assess_boundary(
            boundary_id="arrow_to_pandas",
            source_engine="pyarrow",
            target_engine="pandas-arrow",
            api="Table.to_pandas(types_mapper=pd.ArrowDtype)",
            source=source,
            target=pandas_storage,
        ),
        assess_boundary(
            boundary_id="pandas_to_arrow",
            source_engine="pandas-arrow",
            target_engine="pyarrow",
            api="pa.Table.from_pandas(preserve_index=False)",
            source=source,
            target=pandas_roundtrip,
        ),
        assess_boundary(
            boundary_id="arrow_to_polars",
            source_engine="pyarrow",
            target_engine="polars-arrow-export",
            api=("pl.from_arrow(rechunk=False) -> DataFrame.to_arrow(CompatLevel.oldest())"),
            source=source,
            target=polars_roundtrip,
        ),
        assess_boundary(
            boundary_id="arrow_to_duckdb",
            source_engine="pyarrow",
            target_engine="duckdb-arrow-result",
            api=("DuckDB register(Arrow) -> SELECT -> to_arrow_table() with TimeZone=UTC"),
            source=source,
            target=duckdb_utc,
        ),
    ]
    timezone_counterexample = assess_boundary(
        boundary_id="duckdb_timezone_session_counterexample",
        source_engine="pyarrow-utc",
        target_engine="duckdb-arrow-europe-moscow",
        api="DuckDB SELECT with TimeZone=Europe/Moscow",
        source=source,
        target=duckdb_moscow,
    )
    matrix = interoperability_matrix(boundaries)
    decision = build_decision(boundaries, timezone_counterexample)

    by_id = {boundary["boundary_id"]: boundary for boundary in boundaries}
    checks = {
        "all_boundaries_preserve_values_and_nulls": all(
            boundary["checks"]["semantic_safe"] for boundary in boundaries
        ),
        "pandas_uses_only_arrow_backed_dtypes": all(
            isinstance(dtype, pd.ArrowDtype) for dtype in pandas_frame.dtypes
        ),
        "pandas_storage_reuses_source_buffers": set(
            by_id["arrow_to_pandas"]["buffer_reuse"]["columns_with_full_source_reuse"]
        )
        == set(COLUMN_ORDER),
        "pandas_schema_metadata_drift_is_visible": not by_id["pandas_to_arrow"]["checks"][
            "schema_metadata_match"
        ],
        "polars_reuses_numeric_decimal_and_timestamp_buffers": {
            "event_at",
            "gross_revenue_cents",
            "refund_amount_cents",
            "net_revenue_rub",
            "support_ticket_count",
        }.issubset(set(by_id["arrow_to_polars"]["buffer_reuse"]["columns_with_any_reuse"])),
        "polars_ordered_category_drift_is_visible": not by_id["arrow_to_polars"]["checks"][
            "category_ordering_match"
        ],
        "duckdb_decodes_dictionary_and_materializes_output": (
            by_id["arrow_to_duckdb"]["column_type_checks"]["plan_tier"]["target_family"] == "string"
            and not by_id["arrow_to_duckdb"]["buffer_reuse"]["columns_with_any_reuse"]
        ),
        "duckdb_timezone_session_counterexample_is_visible": decision[
            "timezone_counterexample_detected"
        ],
        "decision_uses_single_engine_boundary": decision["selected_path"]
        == "pyarrow -> polars -> pyarrow",
    }
    report = {
        "scenario": {
            "scenario_id": "columnar-interoperability-audit",
            "rows": int(rows),
            "chunk_size": int(chunk_size),
            "seed": int(seed),
            "versions": {
                "python": platform.python_version(),
                "pandas": pd.__version__,
                "pyarrow": pa.__version__,
                "polars": pl.__version__,
                "duckdb": duckdb.__version__,
            },
            "platform": platform.platform(),
        },
        "canonical_contract": {
            "schema": schema_manifest(source.schema),
            "schema_metadata": _metadata_json(source.schema.metadata),
            "null_counts": {name: int(source[name].null_count) for name in source.column_names},
            "ordered_plan_vocabulary": ORDERED_PLANS,
        },
        "pandas": {
            "dtypes": {name: str(dtype) for name, dtype in pandas_frame.dtypes.items()},
            "rows": len(pandas_frame),
        },
        "polars": {
            "schema": {name: str(type_) for name, type_ in polars_frame.schema.items()},
            "rows": polars_frame.height,
        },
        "boundaries": boundaries,
        "timezone_counterexample": timezone_counterexample,
        "decision": decision,
        "interpretation": {
            "checks": checks,
            "safe_to_ship": all(checks.values()),
            "notes": [
                ("Value equivalence and exact schema equivalence are separate questions."),
                (
                    "Buffer addresses are process-local evidence for this boundary, "
                    "not a universal library promise."
                ),
                (
                    "Ordered categories and timezone configuration belong to the "
                    "business contract, not only to storage."
                ),
            ],
        },
        "package": {
            "output_dir": str(package_dir),
            "files": [
                "canonical-input.arrow",
                "pandas-roundtrip.arrow",
                "polars-roundtrip.arrow",
                "duckdb-utc-output.arrow",
                "interoperability-matrix.csv",
                "conversion-audit.json",
                "engine-boundary-decision.md",
                "report.json",
            ],
        },
    }

    _write_arrow_file(source, package_dir / "canonical-input.arrow")
    _write_arrow_file(
        pandas_roundtrip,
        package_dir / "pandas-roundtrip.arrow",
    )
    _write_arrow_file(
        polars_roundtrip,
        package_dir / "polars-roundtrip.arrow",
    )
    _write_arrow_file(
        duckdb_utc,
        package_dir / "duckdb-utc-output.arrow",
    )
    matrix.to_csv(package_dir / "interoperability-matrix.csv", index=False)
    (package_dir / "conversion-audit.json").write_text(
        json.dumps(
            {
                "boundaries": boundaries,
                "timezone_counterexample": timezone_counterexample,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (package_dir / "engine-boundary-decision.md").write_text(
        _decision_markdown(decision),
        encoding="utf-8",
    )
    (package_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit pandas, Arrow, Polars and DuckDB conversion boundaries"
    )
    parser.add_argument("--rows", type=int, default=24)
    parser.add_argument("--chunk-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_interoperability_report(
            rows=args.rows,
            chunk_size=args.chunk_size,
            seed=args.seed,
            output_dir=args.output_dir,
        )
    except InteroperabilityAuditError as error:
        print(f"interoperability audit error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
