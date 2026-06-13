from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "parquet_converter.py"
DATA = ROOT.parent / "data"
CSV = DATA / "tiny" / "orders_typed.csv"
SCHEMA = DATA / "parquet_schema.json"
SPEC = importlib.util.spec_from_file_location("parquet_converter", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CONVERTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONVERTER)


class ParquetConverterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.output = Path(self.directory.name) / "orders.parquet"
        self.manifest = CONVERTER.convert_csv(CSV, self.output, SCHEMA)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_explicit_schema_is_preserved(self) -> None:
        table = pq.read_table(self.output)
        self.assertEqual(table.schema.field("amount").type, pa.decimal128(12, 2))
        self.assertEqual(table.schema.field("ordered_at").type, pa.timestamp("us", tz="UTC"))

    def test_decimal_values_roundtrip_exactly(self) -> None:
        values = pq.read_table(self.output, columns=["amount"]).column("amount").to_pylist()
        self.assertEqual(values[0], Decimal("1200.50"))
        self.assertEqual(sum(values), Decimal("3226.59"))

    def test_nullable_string_preserves_empty_as_null(self) -> None:
        comments = pq.read_table(self.output, columns=["comment"]).column("comment")
        self.assertEqual(comments.null_count, 2)

    def test_zstd_compression_is_recorded(self) -> None:
        self.assertEqual(self.manifest["output"]["compression"], ["ZSTD"])

    def test_manifest_contains_source_and_output_checksums(self) -> None:
        self.assertEqual(len(self.manifest["source"]["sha256"]), 64)
        self.assertEqual(len(self.manifest["output"]["sha256"]), 64)
        self.assertTrue(self.manifest["summary"]["valid"])

    def test_duckdb_reads_projection_without_csv_parsing(self) -> None:
        rows = duckdb.sql(
            "SELECT order_id, amount FROM read_parquet(?) WHERE amount >= 900 ORDER BY order_id",
            params=[str(self.output)],
        ).fetchall()
        self.assertEqual([row[0] for row in rows], ["O2401", "O2402", "O2405"])

    def test_header_drift_is_rejected(self) -> None:
        broken = Path(self.directory.name) / "broken.csv"
        broken.write_text("id,amount\nO1,1.00\n", encoding="utf-8")
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "header differs"):
            CONVERTER.convert_csv(broken, self.output, SCHEMA)

    def test_cli_writes_parquet_and_manifest(self) -> None:
        output = Path(self.directory.name) / "cli.parquet"
        manifest = Path(self.directory.name) / "manifest.json"
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                CSV,
                "--output",
                output,
                "--schema",
                SCHEMA,
                "--manifest",
                manifest,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["summary"]["valid"])
        self.assertTrue(output.is_file())
        self.assertTrue(manifest.is_file())


if __name__ == "__main__":
    unittest.main()
