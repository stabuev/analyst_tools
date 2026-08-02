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
from unittest import mock

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dataset_builder.py"
CONVERTER_PATH = ROOT.parent / "08-parquet" / "outputs" / "parquet_converter.py"
DATA = ROOT.parent / "data"
CSV = DATA / "tiny" / "orders_typed.csv"
PARQUET_SCHEMA = DATA / "parquet_schema.json"
LAYOUT_CONTRACT = DATA / "partition_layout_contract.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = load_module("dataset_builder", ARTIFACT)
CONVERTER = load_module("parquet_converter_for_partitioning", CONVERTER_PATH)


class DatasetBuilderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = TemporaryDirectory()
        cls.temp = Path(cls.directory.name)
        cls.parquet = cls.temp / "orders.parquet"
        CONVERTER.convert_csv(CSV, cls.parquet, PARQUET_SCHEMA)
        cls.source = pq.read_table(cls.parquet)
        cls.contract = BUILDER.load_contract(LAYOUT_CONTRACT)
        cls.package = cls.temp / "package"
        cls.report = BUILDER.build_dataset(cls.parquet, LAYOUT_CONTRACT, cls.package)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def write_contract(self, value: dict, name: str) -> Path:
        path = self.temp / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_report_is_valid(self) -> None:
        self.assertTrue(self.report["summary"]["valid"])
        self.assertEqual(self.report["summary"]["rows"], 5)
        self.assertEqual(self.report["summary"]["file_count"], 2)

    def test_selected_layout_is_declared_not_inferred(self) -> None:
        decision = self.report["decision"]
        self.assertEqual(decision["selected"], "month_currency")
        self.assertEqual(decision["partition_by"], ["order_month", "currency"])

    def test_candidates_make_fragmentation_visible(self) -> None:
        candidates = {item["name"]: item for item in self.report["decision"]["candidates"]}
        self.assertEqual(candidates["month"]["partition_count"], 1)
        self.assertEqual(candidates["month_currency"]["partition_count"], 2)
        self.assertEqual(candidates["day_currency"]["partition_count"], 5)
        self.assertEqual(candidates["order"]["partition_count"], 5)
        self.assertTrue(candidates["day_currency"]["one_partition_per_row"])
        self.assertTrue(candidates["order"]["one_partition_per_row"])

    def test_candidate_report_separates_partition_and_residual_filters(self) -> None:
        candidates = {item["name"]: item for item in self.report["decision"]["candidates"]}
        month_query = candidates["month"]["workload_support"]["currency_orders"]
        selected_query = candidates["month_currency"]["workload_support"]["currency_orders"]
        self.assertEqual(month_query["partition_filters"], [])
        self.assertEqual(month_query["residual_filters"], ["currency"])
        self.assertEqual(selected_query["partition_filters"], ["currency"])
        self.assertEqual(selected_query["residual_filters"], [])

    def test_small_partition_is_warning_not_hidden(self) -> None:
        self.assertEqual(self.report["summary"]["warning_count"], 1)
        self.assertIn("educational", self.report["decision"]["warnings"][0])
        self.assertIn("not a production", self.report["decision"]["diagnostic_scope"])

    def test_package_contains_data_and_manifest(self) -> None:
        self.assertTrue((self.package / "data").is_dir())
        manifest = json.loads((self.package / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest, self.report)

    def test_hive_paths_contain_selected_keys(self) -> None:
        paths = sorted(self.report["package"]["files"])
        self.assertTrue(all("order_month=2026-05" in path for path in paths))
        self.assertTrue(any("currency=EUR" in path for path in paths))

    def test_partition_columns_live_in_paths_and_are_restored(self) -> None:
        first_file = next((self.package / "data").rglob("*.parquet"))
        physical_names = pq.read_schema(first_file).names
        self.assertNotIn("order_month", physical_names)
        self.assertNotIn("currency", physical_names)
        dataset_names = ds.dataset(
            self.package / "data",
            format="parquet",
            partitioning="hive",
        ).schema.names
        self.assertIn("order_month", dataset_names)
        self.assertIn("currency", dataset_names)

    def test_semantic_roundtrip_checks_all_pass(self) -> None:
        self.assertEqual(
            self.report["checks"],
            {
                "row_count_preserved": True,
                "names_and_types_preserved": True,
                "values_preserved": True,
                "null_counts_preserved": True,
                "grain_preserved": True,
                "workload_results_preserved": True,
                "files_created": True,
            },
        )

    def test_currency_workload_prunes_and_preserves_rows(self) -> None:
        observation = self.report["workload"]["currency_orders"]
        self.assertEqual(observation["expected_rows"], 1)
        self.assertEqual(observation["returned_rows"], 1)
        self.assertEqual(observation["selected_fragments"], 1)
        self.assertTrue(observation["fragment_reduction_observed"])
        self.assertTrue(observation["semantic_match"])

    def test_month_workload_is_correct_without_false_reduction_claim(self) -> None:
        observation = self.report["workload"]["monthly_orders"]
        self.assertEqual(observation["expected_rows"], 5)
        self.assertEqual(observation["selected_fragments"], 2)
        self.assertFalse(observation["fragment_reduction_observed"])
        self.assertTrue(observation["semantic_match"])

    def test_each_file_has_rows_bytes_and_checksum(self) -> None:
        for relative, artifact in self.report["package"]["files"].items():
            path = self.package / relative
            self.assertGreater(artifact["bytes"], 0)
            self.assertGreater(artifact["rows"], 0)
            self.assertEqual(
                artifact["sha256"],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )

    def test_report_hashes_source_and_contract_bytes(self) -> None:
        self.assertEqual(
            self.report["source"]["sha256"],
            hashlib.sha256(self.parquet.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            self.report["contract"]["sha256"],
            hashlib.sha256(LAYOUT_CONTRACT.read_bytes()).hexdigest(),
        )

    def test_report_contains_no_absolute_local_paths(self) -> None:
        serialized = json.dumps(self.report)
        self.assertNotIn(str(self.temp), serialized)
        self.assertNotIn(str(ROOT), serialized)
        self.assertTrue(
            all(not Path(path).is_absolute() for path in self.report["package"]["files"])
        )

    def test_existing_output_is_rejected_without_changes(self) -> None:
        output = self.temp / "existing"
        output.mkdir()
        marker = output / "marker.txt"
        marker.write_text("keep\n", encoding="utf-8")
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "already exists"):
            BUILDER.build_dataset(self.parquet, LAYOUT_CONTRACT, output)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")

    def test_preexisting_similar_staging_directory_is_not_deleted(self) -> None:
        output = self.temp / "safe-package"
        old_staging = self.temp / ".safe-package.staging"
        old_staging.mkdir()
        marker = old_staging / "marker.txt"
        marker.write_text("keep\n", encoding="utf-8")
        BUILDER.build_dataset(self.parquet, LAYOUT_CONTRACT, output)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")

    def test_failed_verification_publishes_nothing_and_cleans_staging(self) -> None:
        output = self.temp / "failed-package"
        with (
            mock.patch.object(
                BUILDER,
                "_verify_candidate",
                return_value=({"row_count_preserved": False}, {}),
            ),
            self.assertRaisesRegex(BUILDER.DatasetBuildError, "verification failed"),
        ):
            BUILDER.build_dataset(self.parquet, LAYOUT_CONTRACT, output)
        self.assertFalse(output.exists())
        self.assertEqual(list(self.temp.glob(".failed-package.*.staging")), [])

    def test_contract_rejects_unknown_root_key(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["surprise"] = True
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "unknown keys"):
            BUILDER.load_contract(self.write_contract(contract, "unknown.json"))

    def test_contract_rejects_duplicate_json_keys(self) -> None:
        path = self.temp / "duplicate.json"
        path.write_text('{"version":"1.0.0","version":"1.0.0"}', encoding="utf-8")
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "duplicate JSON key"):
            BUILDER.load_contract(path)

    def test_contract_rejects_unknown_version(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["version"] = "2.0.0"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "unsupported"):
            BUILDER.load_contract(self.write_contract(contract, "version.json"))

    def test_contract_rejects_duplicate_source_columns(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["source"]["columns"][1]["name"] = "order_id"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "duplicate source column"):
            BUILDER.load_contract(self.write_contract(contract, "source-columns.json"))

    def test_contract_rejects_nullable_grain(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["source"]["columns"][0]["nullable"] = True
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "grain columns"):
            BUILDER.load_contract(self.write_contract(contract, "grain.json"))

    def test_contract_rejects_unknown_transform(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["derived_columns"][0]["transform"] = "magic_month"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "unsupported"):
            BUILDER.load_contract(self.write_contract(contract, "transform.json"))

    def test_contract_rejects_non_timestamp_derived_source(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["derived_columns"][0]["source"] = "currency"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "timestamp column"):
            BUILDER.load_contract(self.write_contract(contract, "derived-source.json"))

    def test_contract_rejects_duplicate_derived_column(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["derived_columns"][1]["name"] = "order_month"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "colliding"):
            BUILDER.load_contract(self.write_contract(contract, "derived-name.json"))

    def test_contract_rejects_unknown_partition_column(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["candidates"][0]["partition_by"] = ["missing"]
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "unknown columns"):
            BUILDER.load_contract(self.write_contract(contract, "partition-key.json"))

    def test_contract_rejects_duplicate_partition_column(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["candidates"][0]["partition_by"] = ["order_month", "order_month"]
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "unique names"):
            BUILDER.load_contract(self.write_contract(contract, "partition-duplicate.json"))

    def test_contract_rejects_non_string_partition_dimension(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["candidates"][0]["partition_by"] = ["amount"]
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "string dimensions"):
            BUILDER.load_contract(self.write_contract(contract, "partition-type.json"))

    def test_contract_rejects_unknown_selected_candidate(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["selected"] = "missing"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "selected candidate"):
            BUILDER.load_contract(self.write_contract(contract, "selected.json"))

    def test_contract_rejects_duplicate_workload_name(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["workload"][1]["name"] = "monthly_orders"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "duplicate workload"):
            BUILDER.load_contract(self.write_contract(contract, "workload-name.json"))

    def test_contract_rejects_unknown_filter_column(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["workload"][0]["filters"] = {"missing": "x"}
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "unknown columns"):
            BUILDER.load_contract(self.write_contract(contract, "filter-column.json"))

    def test_contract_rejects_selected_layout_unrelated_to_workload(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["selected"] = "order"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "cannot prune"):
            BUILDER.load_contract(self.write_contract(contract, "workload-support.json"))

    def test_contract_rejects_non_positive_diagnostic(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["diagnostics"]["small_partition_rows"] = 0
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "positive integer"):
            BUILDER.load_contract(self.write_contract(contract, "diagnostic.json"))

    def test_contract_rejects_null_partition_policy(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["diagnostics"]["allow_null_partition_values"] = True
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "requires.*false"):
            BUILDER.load_contract(self.write_contract(contract, "null-policy.json"))

    def test_missing_input_is_rejected(self) -> None:
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "does not exist"):
            BUILDER.build_dataset(
                self.temp / "missing.parquet",
                LAYOUT_CONTRACT,
                self.temp / "missing-output",
            )

    def test_oversized_input_is_rejected_before_read(self) -> None:
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "exceeds max_bytes"):
            BUILDER.build_dataset(
                self.parquet,
                LAYOUT_CONTRACT,
                self.temp / "oversized-output",
                max_bytes=10,
            )

    def test_invalid_parquet_is_rejected(self) -> None:
        path = self.temp / "invalid.parquet"
        path.write_bytes(b"not parquet")
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "cannot decode"):
            BUILDER.build_dataset(path, LAYOUT_CONTRACT, self.temp / "invalid-output")

    def test_source_schema_drift_is_rejected_before_write(self) -> None:
        amount_index = self.source.schema.get_field_index("amount")
        drifted = self.source.set_column(
            amount_index,
            "amount",
            self.source.column("amount").cast(pa.decimal128(13, 2)),
        )
        path = self.temp / "schema-drift.parquet"
        pq.write_table(drifted, path)
        output = self.temp / "schema-drift-output"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "schema differs"):
            BUILDER.build_dataset(path, LAYOUT_CONTRACT, output)
        self.assertFalse(output.exists())

    def test_source_row_count_drift_is_rejected_before_write(self) -> None:
        path = self.temp / "row-drift.parquet"
        pq.write_table(self.source.slice(0, 4), path)
        output = self.temp / "row-drift-output"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "row count differs"):
            BUILDER.build_dataset(path, LAYOUT_CONTRACT, output)
        self.assertFalse(output.exists())

    def test_duplicate_grain_is_rejected_before_write(self) -> None:
        duplicate = pa.concat_tables([self.source, self.source.slice(0, 1)])
        path = self.temp / "duplicate-grain.parquet"
        pq.write_table(duplicate, path)
        contract = copy.deepcopy(self.contract)
        contract["source"]["row_count"] = duplicate.num_rows
        contract["source"]["null_counts"] = {
            name: duplicate.column(name).null_count for name in duplicate.column_names
        }
        contract_path = self.write_contract(contract, "duplicate-grain-contract.json")
        output = self.temp / "duplicate-grain-output"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "duplicate grain"):
            BUILDER.build_dataset(path, contract_path, output)
        self.assertFalse(output.exists())

    def test_null_partition_value_is_rejected_before_write(self) -> None:
        currency_index = self.source.schema.get_field_index("currency")
        values = self.source.column("currency").to_pylist()
        values[0] = None
        changed = self.source.set_column(currency_index, "currency", pa.array(values))
        path = self.temp / "null-partition.parquet"
        pq.write_table(changed, path)
        contract = copy.deepcopy(self.contract)
        currency = next(
            column for column in contract["source"]["columns"] if column["name"] == "currency"
        )
        currency["nullable"] = True
        contract["source"]["null_counts"]["currency"] = 1
        contract_path = self.write_contract(contract, "null-partition-contract.json")
        output = self.temp / "null-partition-output"
        with self.assertRaisesRegex(BUILDER.LayoutContractError, "null tuple"):
            BUILDER.build_dataset(path, contract_path, output)
        self.assertFalse(output.exists())

    def test_cli_writes_verified_package(self) -> None:
        output = self.temp / "cli-package"
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                self.parquet,
                "--contract",
                LAYOUT_CONTRACT,
                "--output-dir",
                output,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["summary"]["valid"])
        self.assertTrue((output / "manifest.json").is_file())

    def test_cli_contract_error_uses_code_two_without_output(self) -> None:
        bad_contract = self.temp / "bad-contract.json"
        bad_contract.write_text("{}", encoding="utf-8")
        output = self.temp / "bad-cli-output"
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                self.parquet,
                "--contract",
                bad_contract,
                "--output-dir",
                output,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn('"kind": "contract"', result.stderr)
        self.assertFalse(output.exists())

    def test_cli_rejects_colliding_paths(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                self.parquet,
                "--contract",
                LAYOUT_CONTRACT,
                "--output-dir",
                self.parquet,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be distinct", result.stderr)


if __name__ == "__main__":
    unittest.main()
