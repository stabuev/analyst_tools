from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

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
        self.root = Path(self.directory.name)
        self.output = self.root / "orders.parquet"
        self.manifest_path = self.root / "orders.parquet.manifest.json"
        self.manifest = CONVERTER.convert_csv(CSV, self.output, SCHEMA)
        self.contract = CONVERTER.load_contract(SCHEMA)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def write_csv(self, text: str, name: str = "input.csv") -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def write_contract(self, value: dict, name: str = "schema.json") -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def convert_broken(self, text: str, *, contract: Path | None = None) -> None:
        source = self.write_csv(text)
        CONVERTER.convert_csv(source, self.output, contract or SCHEMA)

    def test_explicit_schema_and_nullability_are_preserved(self) -> None:
        table = pq.read_table(self.output)
        self.assertEqual(table.schema.field("amount").type, pa.decimal128(12, 2))
        self.assertEqual(
            table.schema.field("ordered_at").type,
            pa.timestamp("us", tz="UTC"),
        )
        self.assertFalse(table.schema.field("order_id").nullable)
        self.assertTrue(table.schema.field("comment").nullable)

    def test_values_and_order_roundtrip_exactly(self) -> None:
        table = pq.read_table(self.output)
        self.assertEqual(table.column("order_id").to_pylist(), [f"O240{i}" for i in range(1, 6)])
        amounts = table.column("amount").to_pylist()
        self.assertEqual(amounts[0], Decimal("1200.50"))
        self.assertEqual(sum(amounts), Decimal("3226.59"))
        self.assertTrue(self.manifest["checks"]["values_and_order_match"])

    def test_empty_comment_has_explicit_null_semantics(self) -> None:
        comments = pq.read_table(self.output, columns=["comment"]).column("comment")
        self.assertEqual(comments.null_count, 2)
        self.assertEqual(comments.to_pylist()[1], None)

    def test_writer_settings_are_observed_in_physical_metadata(self) -> None:
        metadata = pq.ParquetFile(self.output).metadata
        self.assertEqual(metadata.num_row_groups, 2)
        self.assertEqual([metadata.row_group(i).num_rows for i in range(2)], [3, 2])
        for group_index in range(metadata.num_row_groups):
            for column_index in range(metadata.num_columns):
                column = metadata.row_group(group_index).column(column_index)
                self.assertEqual(column.compression, "ZSTD")
                self.assertIsNotNone(column.statistics)

    def test_disabled_statistics_policy_is_verified(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["writer"]["write_statistics"] = False
        contract_path = self.write_contract(contract)
        output = self.root / "without-statistics.parquet"
        manifest = CONVERTER.convert_csv(CSV, output, contract_path)
        metadata = pq.ParquetFile(output).metadata
        for group_index in range(metadata.num_row_groups):
            for column_index in range(metadata.num_columns):
                self.assertIsNone(metadata.row_group(group_index).column(column_index).statistics)
        self.assertTrue(manifest["checks"]["statistics_match_policy"])

    def test_manifest_binds_source_contract_and_artifact(self) -> None:
        saved = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(saved, self.manifest)
        self.assertEqual(saved["source"]["sha256"], hashlib.sha256(CSV.read_bytes()).hexdigest())
        self.assertEqual(
            saved["contract"]["sha256"], hashlib.sha256(SCHEMA.read_bytes()).hexdigest()
        )
        self.assertEqual(
            saved["artifact"]["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest()
        )
        self.assertTrue(saved["summary"]["valid"])

    def test_manifest_does_not_leak_absolute_paths(self) -> None:
        rendered = json.dumps(self.manifest, ensure_ascii=False)
        self.assertNotIn(str(ROOT), rendered)
        self.assertNotIn(str(self.root), rendered)
        self.assertEqual(self.manifest["artifact"]["name"], "orders.parquet")

    def test_duckdb_reads_typed_projection_and_filter(self) -> None:
        rows = duckdb.sql(
            "SELECT order_id, amount FROM read_parquet(?) WHERE amount >= 900 ORDER BY order_id",
            params=[str(self.output)],
        ).fetchall()
        self.assertEqual(
            rows,
            [
                ("O2401", Decimal("1200.50")),
                ("O2402", Decimal("950.00")),
                ("O2405", Decimal("1050.10")),
            ],
        )

    def test_unsupported_contract_version_is_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["version"] = "9.0.0"
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "unsupported schema version"):
            CONVERTER.load_contract(self.write_contract(contract))

    def test_unknown_contract_key_is_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["surprise"] = True
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "unknown keys"):
            CONVERTER.load_contract(self.write_contract(contract))

    def test_duplicate_json_key_is_rejected(self) -> None:
        path = self.root / "duplicate.json"
        path.write_text(
            '{"version":"2.0.0","version":"2.0.0","grain":[],"allow_empty":false,"columns":[],"writer":{}}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "duplicate JSON key"):
            CONVERTER.load_contract(path)

    def test_duplicate_column_name_is_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["columns"].append(copy.deepcopy(contract["columns"][0]))
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "duplicate column name"):
            CONVERTER.load_contract(self.write_contract(contract))

    def test_nullable_grain_is_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["grain"] = ["comment"]
        with self.assertRaisesRegex(
            CONVERTER.ParquetContractError, "grain columns must be non-null"
        ):
            CONVERTER.load_contract(self.write_contract(contract))

    def test_header_order_drift_is_rejected(self) -> None:
        lines = CSV.read_text(encoding="utf-8").splitlines()
        lines[0] = "user_id,order_id,ordered_at,amount,currency,comment"
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "header differs"):
            self.convert_broken("\n".join(lines) + "\n")

    def test_wrong_record_width_is_rejected(self) -> None:
        text = (
            CSV.read_text(encoding="utf-8") + "O9999,U999,2026-01-01T00:00:00Z,1.00,RUB,ok,extra\n"
        )
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "expected 6 fields, got 7"):
            self.convert_broken(text)

    def test_invalid_utf8_is_rejected(self) -> None:
        path = self.root / "invalid.csv"
        path.write_bytes(b"order_id\xff")
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "valid UTF-8"):
            CONVERTER.convert_csv(path, self.output, SCHEMA)

    def test_empty_non_null_string_is_rejected(self) -> None:
        text = CSV.read_text(encoding="utf-8").replace("O2401,U001", "O2401,")
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "non-null field user_id"):
            self.convert_broken(text)

    def test_timezone_naive_timestamp_is_rejected(self) -> None:
        text = CSV.read_text(encoding="utf-8").replace(
            "2026-05-01T10:00:00Z", "2026-05-01T10:00:00"
        )
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "requires Z or numeric"):
            self.convert_broken(text)

    def test_numeric_offset_is_normalized_to_utc(self) -> None:
        text = CSV.read_text(encoding="utf-8").replace(
            "2026-05-01T10:00:00Z", "2026-05-01T13:00:00+03:00"
        )
        source = self.write_csv(text)
        output = self.root / "offset.parquet"
        CONVERTER.convert_csv(source, output, SCHEMA)
        value = pq.read_table(output, columns=["ordered_at"]).column(0)[0].as_py()
        self.assertEqual(value, datetime(2026, 5, 1, 10, 0, tzinfo=UTC))

    def test_decimal_with_extra_scale_is_rejected(self) -> None:
        text = CSV.read_text(encoding="utf-8").replace("1200.50", "1200.501")
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "more than 2 fractional"):
            self.convert_broken(text)

    def test_non_finite_decimal_is_rejected(self) -> None:
        text = CSV.read_text(encoding="utf-8").replace("1200.50", "NaN")
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "must be finite"):
            self.convert_broken(text)

    def test_decimal_precision_overflow_is_rejected(self) -> None:
        text = CSV.read_text(encoding="utf-8").replace("1200.50", "12345678901.50")
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "exceeds decimal128"):
            self.convert_broken(text)

    def test_domain_drift_is_rejected(self) -> None:
        text = CSV.read_text(encoding="utf-8").replace(",RUB,first", ",USD,first")
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "outside domain"):
            self.convert_broken(text)

    def test_duplicate_grain_is_rejected(self) -> None:
        text = (
            CSV.read_text(encoding="utf-8") + "O2401,U999,2026-05-06T00:00:00Z,1.00,RUB,duplicate\n"
        )
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "duplicate grain"):
            self.convert_broken(text)

    def test_empty_dataset_is_rejected_by_policy(self) -> None:
        header = CSV.read_text(encoding="utf-8").splitlines()[0] + "\n"
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "allow_empty is false"):
            self.convert_broken(header)

    def test_row_limit_rejects_instead_of_truncating(self) -> None:
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "exceeds max_rows"):
            CONVERTER.convert_csv(CSV, self.output, SCHEMA, max_rows=4)

    def test_byte_limit_rejects_instead_of_partial_read(self) -> None:
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "exceeds max_bytes"):
            CONVERTER.convert_csv(CSV, self.output, SCHEMA, max_bytes=10)

    def test_contract_failure_preserves_previous_delivery(self) -> None:
        before_output = self.output.read_bytes()
        before_manifest = self.manifest_path.read_bytes()
        text = CSV.read_text(encoding="utf-8").replace("1200.50", "broken")
        with self.assertRaises(CONVERTER.ParquetContractError):
            self.convert_broken(text)
        self.assertEqual(self.output.read_bytes(), before_output)
        self.assertEqual(self.manifest_path.read_bytes(), before_manifest)

    def test_roundtrip_failure_preserves_previous_delivery(self) -> None:
        before_output = self.output.read_bytes()
        before_manifest = self.manifest_path.read_bytes()
        with (
            mock.patch.object(
                CONVERTER,
                "_inspect_candidate",
                return_value=({"schema_matches": False}, {}),
            ),
            self.assertRaises(CONVERTER.ParquetVerificationError),
        ):
            CONVERTER.convert_csv(CSV, self.output, SCHEMA)
        self.assertEqual(self.output.read_bytes(), before_output)
        self.assertEqual(self.manifest_path.read_bytes(), before_manifest)

    def test_path_collisions_are_rejected(self) -> None:
        with self.assertRaisesRegex(CONVERTER.ParquetContractError, "paths must be distinct"):
            CONVERTER.convert_csv(CSV, CSV, SCHEMA)

    def test_cli_writes_explicit_manifest(self) -> None:
        output = self.root / "cli.parquet"
        manifest = self.root / "delivery.json"
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

    def test_cli_contract_failure_uses_code_2_and_publishes_nothing(self) -> None:
        output = self.root / "must-not-exist.parquet"
        broken = self.write_csv(CSV.read_text(encoding="utf-8").replace("1200.50", "NaN"))
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                broken,
                "--output",
                output,
                "--schema",
                SCHEMA,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["kind"], "contract")
        self.assertFalse(output.exists())
        self.assertFalse((self.root / "must-not-exist.parquet.manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
