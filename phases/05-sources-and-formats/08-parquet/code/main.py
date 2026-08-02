from __future__ import annotations

import csv
import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT.parent / "data"
CSV_PATH = DATA / "tiny" / "orders_typed.csv"
SCHEMA_PATH = DATA / "parquet_schema.json"
ARTIFACT = ROOT / "outputs" / "parquet_converter.py"


def load_converter():
    spec = importlib.util.spec_from_file_location("parquet_converter", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


with CSV_PATH.open(encoding="utf-8", newline="") as source:
    raw_rows = list(csv.DictReader(source))

print(
    "CSV token types:",
    type(raw_rows[0]["amount"]).__name__,
    type(raw_rows[0]["ordered_at"]).__name__,
)
typed_preview = {
    "amount": Decimal(raw_rows[0]["amount"]),
    "ordered_at": datetime.fromisoformat(
        raw_rows[0]["ordered_at"].replace("Z", "+00:00")
    ).astimezone(UTC),
}
print("After declared conversion:", typed_preview)

converter = load_converter()
with TemporaryDirectory() as directory:
    output = Path(directory) / "orders.parquet"
    manifest = converter.convert_csv(CSV_PATH, output, SCHEMA_PATH)
    parquet_file = pq.ParquetFile(output)
    projection = pq.read_table(output, columns=["order_id", "amount"])

    print("Parquet schema:")
    print(parquet_file.schema_arrow)
    print(
        "Rows per row group:",
        [
            parquet_file.metadata.row_group(i).num_rows
            for i in range(parquet_file.metadata.num_row_groups)
        ],
    )
    print("Projected columns:", projection.schema.names)
    print("Roundtrip checks:", manifest["checks"])
