from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "arrow_compatibility.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("arrow_compatibility", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось загрузить {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def buffer_sizes(array: pa.Array) -> list[int | None]:
    return [None if buffer is None else buffer.size for buffer in array.buffers()]


amount = pa.array(
    [Decimal("1200.50"), None, Decimal("19.90")],
    type=pa.decimal128(12, 2),
)
comment = pa.array(["первый заказ", None, "повторный заказ"], type=pa.string())

print("decimal buffers [validity, values]:", buffer_sizes(amount))
print("string buffers [validity, offsets, data]:", buffer_sizes(comment))

table = pa.table(
    {
        "order_id": pa.array(["O1", "O2", "O3"]),
        "amount": amount,
        "comment": comment,
    }
)
frame = table.to_pandas(types_mapper=pd.ArrowDtype)
returned = pa.Table.from_pandas(frame, preserve_index=False)

artifact = load_artifact()
reuse = artifact.buffer_reuse_report(table, returned)

print("\nArrow schema:")
print(table.schema)
print("\npandas dtypes:", {name: str(dtype) for name, dtype in frame.dtypes.items()})
print(
    "buffer reuse:",
    {name: evidence["all_source_buffers_reused"] for name, evidence in reuse.items()},
)
