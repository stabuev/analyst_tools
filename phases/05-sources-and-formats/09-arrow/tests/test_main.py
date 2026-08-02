from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "arrow_compatibility.py"
CONVERTER_PATH = ROOT.parent / "08-parquet" / "outputs" / "parquet_converter.py"
DATA = ROOT.parent / "data"
CSV = DATA / "tiny" / "orders_typed.csv"
PARQUET_SCHEMA = DATA / "parquet_schema.json"
EXCHANGE_CONTRACT = DATA / "arrow_exchange_contract.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPORTER = load_module("arrow_compatibility", ARTIFACT)
CONVERTER = load_module("parquet_converter_for_arrow", CONVERTER_PATH)


class ArrowCompatibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = TemporaryDirectory()
        cls.temp = Path(cls.directory.name)
        cls.parquet = cls.temp / "orders.parquet"
        CONVERTER.convert_csv(CSV, cls.parquet, PARQUET_SCHEMA)
        cls.source = pq.read_table(cls.parquet)
        cls.contract = REPORTER.load_contract(EXCHANGE_CONTRACT)
        cls.report = REPORTER.build_report(cls.parquet, EXCHANGE_CONTRACT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def write_contract(self, value: dict, name: str = "contract.json") -> Path:
        path = self.temp / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_report_is_valid_for_both_routes(self) -> None:
        self.assertTrue(self.report["summary"]["valid"])
        self.assertEqual(
            self.report["summary"]["semantic_routes_valid"],
            {"pandas_roundtrip": True, "duckdb_roundtrip": True},
        )
        self.assertEqual(self.report["source"]["rows"], 5)

    def test_source_schema_and_null_counts_match_contract(self) -> None:
        expected = self.contract["source"]
        self.assertEqual(self.report["source"]["schema"], expected["columns"])
        self.assertEqual(self.report["source"]["null_counts"], expected["null_counts"])

    def test_pandas_preserves_types_values_rows_and_nulls(self) -> None:
        checks = self.report["pandas_roundtrip"]["checks"]
        self.assertTrue(checks["row_count_preserved"])
        self.assertTrue(checks["names_and_types_preserved"])
        self.assertTrue(checks["values_preserved"])
        self.assertTrue(checks["null_counts_preserved"])

    def test_pandas_uses_arrow_backed_dtypes(self) -> None:
        route = self.report["pandas_roundtrip"]
        self.assertTrue(all(route["arrow_backed_dtypes"].values()))
        self.assertEqual(route["dtypes"]["amount"], "decimal128(12, 2)[pyarrow]")

    def test_pandas_index_does_not_leak_into_schema(self) -> None:
        names = [field["name"] for field in self.report["pandas_roundtrip"]["schema"]]
        self.assertEqual(names, self.source.column_names)
        self.assertNotIn("__index_level_0__", names)

    def test_nullability_loss_is_visible_and_explicitly_allowed(self) -> None:
        for route_name in ("pandas_roundtrip", "duckdb_roundtrip"):
            observation = self.report[route_name]["field_nullability"]
            self.assertFalse(observation["exact"])
            self.assertTrue(observation["only_relaxed"])
            self.assertTrue(observation["allowed"])
            self.assertIn(
                "order_id",
                {field["name"] for field in observation["changed_fields"]},
            )

    def test_buffer_evidence_has_no_process_addresses(self) -> None:
        evidence = self.report["pandas_roundtrip"]["buffer_reuse"]
        self.assertEqual(set(evidence), set(self.source.column_names))
        self.assertIn("shared_source_fraction", evidence["order_id"])
        serialized = json.dumps(evidence)
        self.assertNotIn("address", serialized)

    def test_forced_copy_is_not_reported_as_full_reuse(self) -> None:
        copied = pa.Table.from_pylist(self.source.to_pylist(), schema=self.source.schema)
        evidence = REPORTER.buffer_reuse_report(self.source, copied)
        self.assertTrue(
            any(not column["all_source_buffers_reused"] for column in evidence.values())
        )

    def test_type_drift_invalidates_route(self) -> None:
        amount_index = self.source.schema.get_field_index("amount")
        drifted = self.source.set_column(
            amount_index,
            "amount",
            self.source.column("amount").cast(pa.decimal128(13, 2)),
        )
        route = REPORTER.compare_route(
            self.source,
            drifted,
            grain=["order_id"],
            allow_field_nullability_loss=True,
        )
        self.assertFalse(route["checks"]["names_and_types_preserved"])
        self.assertFalse(route["valid"])

    def test_null_drift_invalidates_route(self) -> None:
        comment_index = self.source.schema.get_field_index("comment")
        filled = self.source.set_column(
            comment_index,
            "comment",
            pa.array([value or "нет" for value in self.source.column("comment").to_pylist()]),
        )
        route = REPORTER.compare_route(
            self.source,
            filled,
            grain=["order_id"],
            allow_field_nullability_loss=True,
        )
        self.assertFalse(route["checks"]["values_preserved"])
        self.assertFalse(route["checks"]["null_counts_preserved"])
        self.assertFalse(route["valid"])

    def test_duckdb_returns_full_typed_table(self) -> None:
        route = self.report["duckdb_roundtrip"]
        self.assertTrue(route["checks"]["names_and_types_preserved"])
        self.assertTrue(route["checks"]["values_preserved"])
        timestamp = next(field for field in route["schema"] if field["name"] == "ordered_at")
        self.assertEqual(timestamp["type"], "timestamp[us, tz=UTC]")

    def test_duckdb_session_timezone_is_pinned(self) -> None:
        route = self.report["duckdb_roundtrip"]
        self.assertEqual(route["session_timezone"], "UTC")
        self.assertTrue(route["checks"]["session_timezone_pinned"])

    def test_duckdb_helper_rejects_uncontrolled_timezone(self) -> None:
        with self.assertRaisesRegex(REPORTER.ArrowRouteError, "unsupported.*timezone"):
            REPORTER._duckdb_roundtrip(self.source, "Europe/Moscow")

    def test_report_contains_reproducible_hashes_not_absolute_paths(self) -> None:
        self.assertEqual(
            self.report["source"]["sha256"],
            hashlib.sha256(self.parquet.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            self.report["contract"]["sha256"],
            hashlib.sha256(EXCHANGE_CONTRACT.read_bytes()).hexdigest(),
        )
        serialized = json.dumps(self.report)
        self.assertNotIn(str(self.temp), serialized)
        self.assertNotIn(str(ROOT), serialized)

    def test_contract_rejects_unknown_root_key(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["surprise"] = True
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "unknown keys"):
            REPORTER.load_contract(self.write_contract(contract, "unknown.json"))

    def test_contract_rejects_unknown_version(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["version"] = "2.0.0"
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "unsupported"):
            REPORTER.load_contract(self.write_contract(contract, "version.json"))

    def test_contract_rejects_duplicate_json_keys(self) -> None:
        duplicate = self.temp / "duplicate.json"
        duplicate.write_text('{"version":"1.0.0","version":"1.0.0"}', encoding="utf-8")
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "duplicate JSON key"):
            REPORTER.load_contract(duplicate)

    def test_contract_rejects_duplicate_columns(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["source"]["columns"][1]["name"] = "order_id"
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "duplicate source column"):
            REPORTER.load_contract(self.write_contract(contract, "columns.json"))

    def test_contract_rejects_incomplete_null_counts(self) -> None:
        contract = copy.deepcopy(self.contract)
        del contract["source"]["null_counts"]["comment"]
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "every source column"):
            REPORTER.load_contract(self.write_contract(contract, "nulls.json"))

    def test_contract_rejects_impossible_null_count(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["source"]["null_counts"]["comment"] = 6
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "cannot exceed"):
            REPORTER.load_contract(self.write_contract(contract, "null-count.json"))

    def test_contract_rejects_nullable_grain(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["source"]["columns"][0]["nullable"] = True
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "grain columns"):
            REPORTER.load_contract(self.write_contract(contract, "grain.json"))

    def test_contract_rejects_unpinned_duckdb_timezone(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["routes"]["duckdb_roundtrip"]["session_timezone"] = "Europe/Moscow"
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "requires.*UTC"):
            REPORTER.load_contract(self.write_contract(contract, "timezone.json"))

    def test_missing_input_is_rejected(self) -> None:
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "does not exist"):
            REPORTER.build_report(self.temp / "missing.parquet", EXCHANGE_CONTRACT)

    def test_oversized_input_is_rejected(self) -> None:
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "exceeds max_bytes"):
            REPORTER.build_report(self.parquet, EXCHANGE_CONTRACT, max_bytes=10)

    def test_source_schema_drift_is_rejected_before_routes(self) -> None:
        amount_index = self.source.schema.get_field_index("amount")
        drifted = self.source.set_column(
            amount_index,
            "amount",
            self.source.column("amount").cast(pa.decimal128(13, 2)),
        )
        path = self.temp / "schema-drift.parquet"
        pq.write_table(drifted, path)
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "schema differs"):
            REPORTER.build_report(path, EXCHANGE_CONTRACT)

    def test_duplicate_grain_is_rejected_before_routes(self) -> None:
        duplicate = pa.concat_tables([self.source, self.source.slice(0, 1)])
        path = self.temp / "duplicate-grain.parquet"
        pq.write_table(duplicate, path)
        contract = copy.deepcopy(self.contract)
        contract["source"]["row_count"] = 6
        contract["source"]["null_counts"]["comment"] = 2
        contract_path = self.write_contract(contract, "six-rows.json")
        with self.assertRaisesRegex(REPORTER.ArrowCompatibilityError, "duplicate grain"):
            REPORTER.build_report(path, contract_path)

    def test_invalid_report_is_not_published(self) -> None:
        output = self.temp / "preserved.json"
        output.write_text("old\n", encoding="utf-8")
        invalid = copy.deepcopy(self.report)
        invalid["summary"]["valid"] = False
        with self.assertRaisesRegex(REPORTER.ArrowRouteError, "must not be published"):
            REPORTER.publish_report(invalid, output)
        self.assertEqual(output.read_text(encoding="utf-8"), "old\n")

    def test_publish_report_writes_parseable_json(self) -> None:
        output = self.temp / "published.json"
        REPORTER.publish_report(self.report, output)
        self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["summary"]["valid"])

    def test_cli_writes_report_file(self) -> None:
        output = self.temp / "cli-report.json"
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                self.parquet,
                "--contract",
                EXCHANGE_CONTRACT,
                "--output",
                output,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(output.read_text(encoding="utf-8"))["summary"]["valid"])

    def test_cli_contract_error_uses_code_two_without_output(self) -> None:
        bad_contract = self.temp / "bad-contract.json"
        bad_contract.write_text("{}", encoding="utf-8")
        output = self.temp / "must-not-exist.json"
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                self.parquet,
                "--contract",
                bad_contract,
                "--output",
                output,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn('"kind": "contract"', result.stderr)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
