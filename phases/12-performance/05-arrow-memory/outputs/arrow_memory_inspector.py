from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa


class ArrowMemoryError(ValueError):
    """Raised when the Arrow memory inspection cannot be built safely."""


DIMENSION_VALUES = {
    "platform": ["web", "ios", "android"],
    "plan": ["trial", "basic", "plus", "pro"],
}


def _chunk_bounds(length: int, chunk_size: int) -> list[tuple[int, int]]:
    if length <= 0:
        raise ArrowMemoryError("rows must be positive")
    if chunk_size <= 0:
        raise ArrowMemoryError("chunk_size must be positive")
    return [(start, min(start + chunk_size, length)) for start in range(0, length, chunk_size)]


def _chunked_array_from_values(
    values: list[Any] | np.ndarray,
    *,
    chunk_size: int,
    type_: pa.DataType,
    dictionary_encode: bool = False,
) -> pa.ChunkedArray:
    chunks: list[pa.Array] = []
    sequence = list(values)
    for start, end in _chunk_bounds(len(sequence), chunk_size):
        array = pa.array(sequence[start:end], type=type_)
        chunks.append(array.dictionary_encode() if dictionary_encode else array)
    return pa.chunked_array(chunks)


def build_customer_revenue_arrow_table(
    *,
    rows: int = 48,
    chunk_size: int = 16,
    seed: int = 42,
) -> pa.Table:
    if rows < 8:
        raise ArrowMemoryError("rows must be at least 8 to expose chunks, nulls and dictionaries")
    rng = np.random.default_rng(seed)
    index = np.arange(rows, dtype=np.int64)
    week_index = (index % 8).astype(np.int16)
    platforms = [DIMENSION_VALUES["platform"][int(i % 3)] for i in index]
    plans = [DIMENSION_VALUES["plan"][int(rng.integers(0, 4))] for _ in range(rows)]
    paid_orders = rng.binomial(1, 0.72, size=rows).astype(np.int8)
    gross = rng.integers(399, 30_000, size=rows, dtype=np.int64) * paid_orders
    refunds = np.where(rng.random(rows) < 0.08, gross // 3, 0).astype(np.int64)
    net_revenue = (gross - refunds).astype(np.int64)
    support_tickets: list[int | None] = [
        None if position % 7 == 0 else int(value)
        for position, value in enumerate(rng.poisson(0.2, size=rows))
    ]
    notes = [
        None if position % 11 == 0 else f"ticket bucket {int(index[position] % 5)}"
        for position in range(rows)
    ]

    columns = {
        "order_id": _chunked_array_from_values(
            [f"O{position // 2:08d}" for position in index],
            chunk_size=chunk_size,
            type_=pa.string(),
        ),
        "week_index": _chunked_array_from_values(
            week_index,
            chunk_size=chunk_size,
            type_=pa.int16(),
        ),
        "platform": _chunked_array_from_values(
            platforms,
            chunk_size=chunk_size,
            type_=pa.string(),
            dictionary_encode=True,
        ),
        "plan": _chunked_array_from_values(
            plans,
            chunk_size=chunk_size,
            type_=pa.string(),
            dictionary_encode=True,
        ),
        "paid_orders": _chunked_array_from_values(
            paid_orders,
            chunk_size=chunk_size,
            type_=pa.int8(),
        ),
        "net_revenue_cents": _chunked_array_from_values(
            net_revenue,
            chunk_size=chunk_size,
            type_=pa.int64(),
        ),
        "support_ticket_count": _chunked_array_from_values(
            support_tickets,
            chunk_size=chunk_size,
            type_=pa.int16(),
        ),
        "support_notes": _chunked_array_from_values(
            notes,
            chunk_size=chunk_size,
            type_=pa.string(),
        ),
    }
    return pa.table(columns)


def _buffer_roles(array: pa.Array) -> list[str]:
    data_type = array.type
    if pa.types.is_dictionary(data_type):
        return ["validity_bitmap", "indices"]
    if pa.types.is_string(data_type) or pa.types.is_binary(data_type):
        return ["validity_bitmap", "offsets", "values"]
    if pa.types.is_large_string(data_type) or pa.types.is_large_binary(data_type):
        return ["validity_bitmap", "large_offsets", "values"]
    if pa.types.is_primitive(data_type) or pa.types.is_temporal(data_type):
        return ["validity_bitmap", "values"]
    return [f"buffer_{index}" for index, _buffer in enumerate(array.buffers())]


def _buffer_summary(buffer: pa.Buffer | None, *, index: int, role: str) -> dict[str, Any]:
    if buffer is None:
        return {
            "index": index,
            "role": role,
            "present": False,
            "size_bytes": 0,
            "address": None,
            "is_cpu": None,
            "is_mutable": None,
        }
    return {
        "index": index,
        "role": role,
        "present": True,
        "size_bytes": int(buffer.size),
        "address": int(buffer.address),
        "is_cpu": bool(buffer.is_cpu),
        "is_mutable": bool(buffer.is_mutable),
    }


def inspect_array(name: str, array: pa.Array) -> dict[str, Any]:
    roles = _buffer_roles(array)
    buffers = [
        _buffer_summary(
            buffer,
            index=index,
            role=roles[index] if index < len(roles) else f"buffer_{index}",
        )
        for index, buffer in enumerate(array.buffers())
    ]
    result: dict[str, Any] = {
        "name": name,
        "type": str(array.type),
        "length": len(array),
        "null_count": int(array.null_count),
        "offset": int(array.offset),
        "nbytes": int(array.nbytes),
        "total_buffer_size": int(array.get_total_buffer_size()),
        "buffers": buffers,
    }
    if pa.types.is_dictionary(array.type):
        dictionary = array.dictionary
        result["dictionary"] = {
            "index_type": str(array.indices.type),
            "value_type": str(dictionary.type),
            "values": dictionary.to_pylist(),
            "values_count": len(dictionary),
            "buffers": inspect_array(f"{name}.dictionary", dictionary)["buffers"],
        }
    return result


def inspect_chunked_array(name: str, chunked: pa.ChunkedArray) -> dict[str, Any]:
    chunks = [inspect_array(f"{name}.chunk[{index}]", chunk) for index, chunk in enumerate(chunked.chunks)]
    result: dict[str, Any] = {
        "name": name,
        "type": str(chunked.type),
        "length": len(chunked),
        "num_chunks": int(chunked.num_chunks),
        "null_count": int(chunked.null_count),
        "nbytes": int(chunked.nbytes),
        "total_buffer_size": int(chunked.get_total_buffer_size()),
        "chunks": chunks,
    }
    if pa.types.is_dictionary(chunked.type):
        result["dictionary_values_per_chunk"] = [
            chunk.dictionary.to_pylist()
            for chunk in chunked.chunks
        ]
    return result


def inspect_table(table: pa.Table) -> dict[str, Any]:
    return {
        "schema": str(table.schema),
        "rows": table.num_rows,
        "columns": table.num_columns,
        "nbytes": int(table.nbytes),
        "column_names": table.column_names,
        "columns_detail": [
            inspect_chunked_array(name, table[name])
            for name in table.column_names
        ],
    }


def _array_buffer_addresses(array: pa.Array, *, include_dictionary: bool = True) -> set[int]:
    addresses = {int(buffer.address) for buffer in array.buffers() if buffer is not None}
    if include_dictionary and pa.types.is_dictionary(array.type):
        addresses |= _array_buffer_addresses(array.dictionary, include_dictionary=False)
    return addresses


def _chunked_buffer_addresses(chunked: pa.ChunkedArray, *, include_dictionary: bool = True) -> set[int]:
    addresses: set[int] = set()
    for chunk in chunked.chunks:
        addresses |= _array_buffer_addresses(chunk, include_dictionary=include_dictionary)
    return addresses


def _numpy_address(values: np.ndarray) -> int:
    return int(values.__array_interface__["data"][0])


def _capture_failure(operation: str, callback: Any) -> dict[str, Any]:
    try:
        callback()
    except Exception as error:  # noqa: BLE001 - report class and message for a learning artifact.
        return {
            "operation": operation,
            "succeeded": False,
            "error_type": type(error).__name__,
            "message": str(error),
        }
    return {"operation": operation, "succeeded": True, "error_type": None, "message": None}


def build_copy_audit(table: pa.Table) -> dict[str, Any]:
    primitive = table["net_revenue_cents"].chunk(0)
    primitive_numpy = primitive.to_numpy(zero_copy_only=True)
    values_buffer = primitive.buffers()[1]
    if values_buffer is None:
        raise ArrowMemoryError("primitive array unexpectedly has no values buffer")
    expected_numpy_address = int(values_buffer.address) + int(primitive.offset) * 8

    nullable = table["support_ticket_count"].chunk(0)
    string_array = table["support_notes"].chunk(0)
    chunked = table["net_revenue_cents"]
    combined = chunked.combine_chunks()
    sliced = primitive.slice(2, min(5, len(primitive) - 2))
    dictionary_chunked = table["platform"]
    unified_dictionary = dictionary_chunked.unify_dictionaries()

    before_combine = _chunked_buffer_addresses(chunked)
    after_combine = _array_buffer_addresses(combined)
    before_dictionary = _chunked_buffer_addresses(dictionary_chunked)
    after_dictionary = _chunked_buffer_addresses(unified_dictionary)
    primitive_pandas_failure = _capture_failure(
        "table.to_pandas(zero_copy_only=True)",
        lambda: table.select(["week_index", "net_revenue_cents"]).to_pandas(zero_copy_only=True),
    )
    primitive_pandas_split_failure = _capture_failure(
        "chunked table.to_pandas(zero_copy_only=True, split_blocks=True)",
        lambda: table.select(["week_index", "net_revenue_cents"]).to_pandas(
            zero_copy_only=True,
            split_blocks=True,
        ),
    )
    single_chunk_numeric_table = table.select(["week_index", "net_revenue_cents"]).combine_chunks()
    primitive_pandas_split = single_chunk_numeric_table.to_pandas(
        zero_copy_only=True,
        split_blocks=True,
    )

    return {
        "zero_copy_numpy": {
            "column": "net_revenue_cents",
            "chunk": 0,
            "succeeded": True,
            "arrow_values_buffer_address": int(values_buffer.address),
            "numpy_data_address": _numpy_address(primitive_numpy),
            "expected_numpy_address": expected_numpy_address,
            "shares_arrow_values_buffer": _numpy_address(primitive_numpy) == expected_numpy_address,
            "dtype": str(primitive_numpy.dtype),
            "shape": list(primitive_numpy.shape),
        },
        "nullable_numpy_zero_copy": _capture_failure(
            "support_ticket_count.to_numpy(zero_copy_only=True)",
            lambda: nullable.to_numpy(zero_copy_only=True),
        ),
        "string_numpy_zero_copy": _capture_failure(
            "support_notes.to_numpy(zero_copy_only=True)",
            lambda: string_array.to_numpy(zero_copy_only=True),
        ),
        "chunked_numpy_zero_copy": _capture_failure(
            "chunked_array.to_numpy(zero_copy_only=True)",
            lambda: chunked.to_numpy(zero_copy_only=True),
        ),
        "table_to_pandas_zero_copy": primitive_pandas_failure,
        "chunked_table_to_pandas_split_blocks": primitive_pandas_split_failure,
        "single_chunk_table_to_pandas_split_blocks": {
            "operation": "table.combine_chunks().to_pandas(zero_copy_only=True, split_blocks=True)",
            "succeeded": True,
            "precondition": "combine_chunks creates single-chunk columns before the pandas boundary",
            "shape": list(primitive_pandas_split.shape),
            "dtypes": {name: str(dtype) for name, dtype in primitive_pandas_split.dtypes.items()},
        },
        "slice_buffer_reuse": {
            "operation": "primitive.slice(2, 5)",
            "succeeded": True,
            "source_offset": int(primitive.offset),
            "slice_offset": int(sliced.offset),
            "source_buffer_addresses": sorted(_array_buffer_addresses(primitive)),
            "slice_buffer_addresses": sorted(_array_buffer_addresses(sliced)),
            "shares_buffers": bool(_array_buffer_addresses(primitive) & _array_buffer_addresses(sliced)),
        },
        "combine_chunks": {
            "operation": "chunked_array.combine_chunks()",
            "succeeded": True,
            "source_num_chunks": int(chunked.num_chunks),
            "result_length": len(combined),
            "source_buffer_addresses": sorted(before_combine),
            "combined_buffer_addresses": sorted(after_combine),
            "shares_any_source_buffer": bool(before_combine & after_combine),
            "requires_copy": not bool(before_combine & after_combine),
        },
        "dictionary_unify": {
            "operation": "dictionary_chunked.unify_dictionaries()",
            "succeeded": True,
            "source_dictionaries": [
                chunk.dictionary.to_pylist()
                for chunk in dictionary_chunked.chunks
            ],
            "unified_dictionaries": [
                chunk.dictionary.to_pylist()
                for chunk in unified_dictionary.chunks
            ],
            "source_buffer_addresses": sorted(before_dictionary),
            "unified_buffer_addresses": sorted(after_dictionary),
            "shares_any_source_buffer": bool(before_dictionary & after_dictionary),
            "requires_some_rewrite": [
                chunk.dictionary.to_pylist()
                for chunk in dictionary_chunked.chunks
            ]
            != [
                chunk.dictionary.to_pylist()
                for chunk in unified_dictionary.chunks
            ],
        },
    }


def build_arrow_memory_report(
    *,
    rows: int = 48,
    chunk_size: int = 16,
    seed: int = 42,
) -> dict[str, Any]:
    table = build_customer_revenue_arrow_table(rows=rows, chunk_size=chunk_size, seed=seed)
    inspection = inspect_table(table)
    copy_audit = build_copy_audit(table)

    buffer_findings = {
        "numeric_without_nulls_has_no_validity_bitmap": not inspection["columns_detail"][5]["chunks"][0]["buffers"][0]["present"],
        "nullable_numeric_has_validity_bitmap": inspection["columns_detail"][6]["chunks"][0]["buffers"][0]["present"],
        "string_column_has_offsets_and_values": all(
            buffer["present"]
            for buffer in inspection["columns_detail"][7]["chunks"][1]["buffers"][1:]
        ),
        "dictionary_column_uses_indices_and_dictionary_values": (
            "dictionary" in inspection["columns_detail"][2]["chunks"][0]
        ),
        "table_has_chunked_columns": any(
            column["num_chunks"] > 1
            for column in inspection["columns_detail"]
        ),
    }
    core_checks = [
        *buffer_findings.values(),
        copy_audit["zero_copy_numpy"]["shares_arrow_values_buffer"],
        not copy_audit["nullable_numpy_zero_copy"]["succeeded"],
        not copy_audit["chunked_numpy_zero_copy"]["succeeded"],
        not copy_audit["table_to_pandas_zero_copy"]["succeeded"],
        not copy_audit["chunked_table_to_pandas_split_blocks"]["succeeded"],
        copy_audit["single_chunk_table_to_pandas_split_blocks"]["succeeded"],
        copy_audit["slice_buffer_reuse"]["shares_buffers"],
        copy_audit["combine_chunks"]["requires_copy"],
        copy_audit["dictionary_unify"]["requires_some_rewrite"],
    ]

    return {
        "scenario": {
            "scenario_id": "arrow-memory-copy-audit",
            "rows": int(rows),
            "chunk_size": int(chunk_size),
            "seed": int(seed),
            "engine_versions": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "pyarrow": pa.__version__,
            },
        },
        "table": inspection,
        "buffer_findings": buffer_findings,
        "copy_audit": copy_audit,
        "interpretation": {
            "safe_to_ship": all(core_checks),
            "notes": [
                "Zero-copy is a boundary property, not a generic promise of every Arrow conversion.",
                "Primitive arrays without nulls can share values buffers with NumPy.",
                "Null bitmaps, offsets, chunks and dictionary unification are the places to inspect before assuming no copy.",
            ],
        },
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Arrow buffers and copy boundaries")
    parser.add_argument("--rows", type=int, default=48)
    parser.add_argument("--chunk-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        report = build_arrow_memory_report(
            rows=args.rows,
            chunk_size=args.chunk_size,
            seed=args.seed,
        )
        if args.output is not None:
            write_report(report, args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except ArrowMemoryError as error:
        print(f"arrow memory error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
