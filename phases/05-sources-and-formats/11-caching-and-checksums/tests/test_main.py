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
ARTIFACT = ROOT / "outputs" / "resilient_loader.py"
DATA = ROOT.parent / "data"
SOURCE = DATA / "tiny"
SCHEMA = DATA / "parquet_schema.json"
START_URL = "https://api.example.test/orders?page=1"
SPEC = importlib.util.spec_from_file_location("resilient_loader", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
LOADER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOADER)


class FailingFetcher:
    def __call__(self, url: str) -> bytes:
        raise AssertionError(f"unexpected fetch: {url}")


class BadFetcher:
    def __init__(self, source_dir: Path) -> None:
        self.good = LOADER.LocalPageFetcher(source_dir)

    def __call__(self, url: str) -> bytes:
        payload = json.loads(self.good(url))
        if url.endswith("page=2"):
            payload["items"][0]["amount"] = "not-a-number"
        return json.dumps(payload).encode()


class ResilientLoaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.output = Path(self.directory.name) / "delivery"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def run_valid(self):
        fetcher = LOADER.LocalPageFetcher(SOURCE)
        report = LOADER.run_loader(START_URL, self.output, SCHEMA, fetcher)
        return report, fetcher

    def test_end_to_end_publishes_partitioned_dataset(self) -> None:
        report, fetcher = self.run_valid()
        self.assertTrue(report["summary"]["valid"])
        self.assertEqual(report["summary"]["row_count"], 5)
        self.assertEqual(len(fetcher.calls), 3)
        paths = list(report["dataset"]["files"])
        self.assertTrue(any("currency=EUR" in path for path in paths))

    def test_second_run_uses_raw_cache_and_existing_version(self) -> None:
        first, _ = self.run_valid()
        second = LOADER.run_loader(START_URL, self.output, SCHEMA, FailingFetcher())
        self.assertEqual(second["source"]["reused_pages"], 3)
        self.assertTrue(second["dataset"]["reused_version"])
        self.assertEqual(second["run_id"], first["run_id"])

    def test_cache_index_contains_verified_checksums(self) -> None:
        self.run_valid()
        cache = json.loads((self.output / "raw" / "cache_index.json").read_text())
        self.assertEqual(len(cache), 3)
        for entry in cache.values():
            path = self.output / "raw" / entry["file"]
            self.assertEqual(LOADER.sha256_file(path), entry["sha256"])

    def test_corrupted_cache_page_is_refetched(self) -> None:
        self.run_valid()
        cache_path = self.output / "raw" / "cache_index.json"
        cache = json.loads(cache_path.read_text())
        page_two = cache["https://api.example.test/orders?page=2"]
        (self.output / "raw" / page_two["file"]).write_text("corrupted")
        fetcher = LOADER.LocalPageFetcher(SOURCE)
        report = LOADER.run_loader(START_URL, self.output, SCHEMA, fetcher)
        self.assertEqual(fetcher.calls, ["https://api.example.test/orders?page=2"])
        self.assertEqual(report["source"]["reused_pages"], 2)

    def test_failed_refresh_does_not_change_current_pointer(self) -> None:
        self.run_valid()
        pointer = (self.output / "current.json").read_bytes()
        with self.assertRaisesRegex(LOADER.LoaderError, "invalid decimal"):
            LOADER.run_loader(
                START_URL,
                self.output,
                SCHEMA,
                BadFetcher(SOURCE),
                refresh=True,
            )
        self.assertEqual((self.output / "current.json").read_bytes(), pointer)

    def test_current_points_to_immutable_version_manifest(self) -> None:
        report, _ = self.run_valid()
        current = json.loads((self.output / "current.json").read_text())
        manifest = self.output / current["manifest"]
        self.assertTrue(manifest.is_file())
        self.assertEqual(current["manifest_sha256"], LOADER.sha256_file(manifest))
        self.assertIn(report["run_id"], current["dataset"])

    def test_dataset_schema_and_partition_columns_are_readable(self) -> None:
        report, _ = self.run_valid()
        dataset = ds.dataset(
            self.output / report["current"]["dataset"],
            format="parquet",
            partitioning="hive",
        )
        self.assertEqual(dataset.count_rows(), 5)
        self.assertIn("order_month", dataset.schema.names)
        self.assertIn("currency", dataset.schema.names)

    def test_schema_drift_is_rejected_before_pointer_update(self) -> None:
        with self.assertRaisesRegex(LOADER.LoaderError, "invalid decimal"):
            LOADER.run_loader(START_URL, self.output, SCHEMA, BadFetcher(SOURCE))
        self.assertFalse((self.output / "current.json").exists())

    def test_cli_runs_fully_offline(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--url",
                START_URL,
                "--source-dir",
                SOURCE,
                "--output-dir",
                self.output,
                "--schema",
                SCHEMA,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["summary"]["valid"])
        self.assertTrue((self.output / "current.json").is_file())


if __name__ == "__main__":
    unittest.main()
