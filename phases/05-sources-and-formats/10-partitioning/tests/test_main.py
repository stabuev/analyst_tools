from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow.dataset as ds

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dataset_builder.py"
CONVERTER_PATH = ROOT.parent / "08-parquet" / "outputs" / "parquet_converter.py"
DATA = ROOT.parent / "data"
CSV = DATA / "tiny" / "orders_typed.csv"
SCHEMA = DATA / "parquet_schema.json"


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
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.parquet = self.root / "orders.parquet"
        self.dataset_path = self.root / "dataset"
        CONVERTER.convert_csv(CSV, self.parquet, SCHEMA)
        self.report = BUILDER.build_dataset(self.parquet, self.dataset_path)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_hive_layout_contains_declared_keys(self) -> None:
        paths = list(self.report["layout"]["files"])
        self.assertTrue(all("order_month=2026-05" in path for path in paths))
        self.assertTrue(any("currency=EUR" in path for path in paths))

    def test_all_rows_are_readable(self) -> None:
        table = ds.dataset(
            self.dataset_path,
            format="parquet",
            partitioning="hive",
        ).to_table()
        self.assertEqual(table.num_rows, 5)
        self.assertTrue(self.report["checks"]["all_rows_readable"])

    def test_month_currency_avoids_daily_partition_explosion(self) -> None:
        self.assertEqual(self.report["layout"]["chosen_partitions"], 2)
        self.assertEqual(self.report["layout"]["daily_candidate_partitions"], 5)

    def test_currency_filter_prunes_fragments(self) -> None:
        pruning = self.report["pruning"]
        self.assertEqual(pruning["all_fragments"], 2)
        self.assertEqual(pruning["selected_fragments"], 1)
        self.assertIn("currency=EUR", pruning["selected_paths"][0])

    def test_small_files_are_reported_not_hidden(self) -> None:
        self.assertEqual(len(self.report["layout"]["small_files"]), 1)
        self.assertIn("currency=EUR", self.report["layout"]["small_files"][0])

    def test_each_file_has_checksum(self) -> None:
        self.assertTrue(self.report["artifacts"])
        self.assertTrue(
            all(len(value["sha256"]) == 64 for value in self.report["artifacts"].values())
        )

    def test_unknown_partition_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(BUILDER.DatasetLayoutError, "unknown partition"):
            BUILDER.build_dataset(
                self.parquet,
                self.root / "bad",
                partition_by=("missing",),
            )

    def test_cli_writes_dataset_and_manifest(self) -> None:
        output = self.root / "cli-dataset"
        manifest = self.root / "manifest.json"
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--input",
                self.parquet,
                "--output-dir",
                output,
                "--manifest",
                manifest,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["summary"]["valid"])
        self.assertTrue(manifest.is_file())


if __name__ == "__main__":
    unittest.main()
