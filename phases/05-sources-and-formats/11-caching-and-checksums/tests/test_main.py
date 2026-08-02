from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "resilient_loader.py"
DATA = ROOT.parent / "data"
SOURCE = DATA / "tiny"
DELIVERY_SOURCE = DATA / "delivery_contract.json"
SCHEMA_SOURCE = DATA / "parquet_schema.json"
LAYOUT_SOURCE = DATA / "partition_layout_contract.json"
START_URL = "https://api.example.test/orders?page=1"

SPEC = importlib.util.spec_from_file_location("resilient_loader", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
LOADER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOADER)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fixture_pages() -> dict[str, bytes]:
    return {
        f"https://api.example.test/orders?page={page}": (
            SOURCE / f"api_page_{page}.json"
        ).read_bytes()
        for page in (1, 2, 3)
    }


class MappingFetcher:
    def __init__(self, pages: dict[str, bytes]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if url not in self.pages:
            raise LOADER.DeliveryError(f"missing page: {url}")
        return self.pages[url]


class FailingFetcher:
    def __call__(self, url: str) -> bytes:
        raise AssertionError(f"unexpected fetch: {url}")


class ResilientLoaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.temp = Path(self.directory.name)
        self.output = self.temp / "delivery"
        self.delivery = self.temp / "delivery_contract.json"
        self.schema = self.temp / "parquet_schema.json"
        self.layout = self.temp / "partition_layout_contract.json"
        shutil.copy2(DELIVERY_SOURCE, self.delivery)
        shutil.copy2(SCHEMA_SOURCE, self.schema)
        shutil.copy2(LAYOUT_SOURCE, self.layout)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def run_loader(self, fetcher=None, *, refresh: bool = False):
        if fetcher is None:
            fetcher = LOADER.LocalPageFetcher(SOURCE)
        report = LOADER.run_loader(
            self.output,
            self.delivery,
            self.schema,
            self.layout,
            fetcher,
            refresh=refresh,
        )
        return report, fetcher

    def test_end_to_end_publishes_verified_version(self) -> None:
        report, fetcher = self.run_loader()
        self.assertTrue(report["summary"]["valid"])
        self.assertEqual(
            report["source"],
            {
                "pages": 3,
                "rows": 5,
                "reused_pages": 0,
                "fetched_pages": 3,
            },
        )
        self.assertEqual(len(fetcher.calls), 3)
        self.assertEqual(report["dataset"]["partition_by"], ["order_month", "currency"])
        self.assertTrue(all(report["checks"].values()))

    def test_second_run_replays_cache_and_verifies_existing_version(self) -> None:
        first, _ = self.run_loader()
        second, _ = self.run_loader(FailingFetcher())
        self.assertEqual(second["run_id"], first["run_id"])
        self.assertEqual(second["source"]["reused_pages"], 3)
        self.assertTrue(second["dataset"]["reused_version"])

    def test_raw_cache_is_content_addressed(self) -> None:
        self.run_loader()
        cache = read_json(self.output / "raw" / "cache_index.json")
        self.assertEqual(cache["version"], "1.0.0")
        self.assertEqual(len(cache["entries"]), 3)
        for entry in cache["entries"].values():
            blob = self.output / "raw" / "blobs" / f"{entry['sha256']}.json"
            self.assertEqual(blob.stat().st_size, entry["bytes"])
            self.assertEqual(LOADER.sha256_file(blob), entry["sha256"])

    def test_corrupted_blob_is_refetched_and_repaired(self) -> None:
        self.run_loader()
        cache = read_json(self.output / "raw" / "cache_index.json")["entries"]
        page_two = cache["https://api.example.test/orders?page=2"]
        blob = self.output / "raw" / "blobs" / f"{page_two['sha256']}.json"
        blob.write_bytes(b"corrupted")
        fetcher = LOADER.LocalPageFetcher(SOURCE)
        report, _ = self.run_loader(fetcher)
        self.assertEqual(fetcher.calls, ["https://api.example.test/orders?page=2"])
        self.assertEqual(report["source"]["reused_pages"], 2)
        self.assertEqual(LOADER.sha256_file(blob), page_two["sha256"])

    def test_valid_refresh_creates_new_snapshot_and_version(self) -> None:
        first, _ = self.run_loader()
        pages = fixture_pages()
        changed = json.loads(pages["https://api.example.test/orders?page=3"])
        changed["items"][0]["comment"] = "corrected"
        pages["https://api.example.test/orders?page=3"] = json.dumps(changed).encode()
        second, _ = self.run_loader(MappingFetcher(pages), refresh=True)
        self.assertNotEqual(second["snapshot_id"], first["snapshot_id"])
        self.assertNotEqual(second["run_id"], first["run_id"])
        self.assertEqual(read_json(self.output / "current.json")["run_id"], second["run_id"])

    def test_failed_refresh_preserves_pointer_index_and_old_blobs(self) -> None:
        self.run_loader()
        pointer = (self.output / "current.json").read_bytes()
        index = (self.output / "raw" / "cache_index.json").read_bytes()
        old_blobs = {
            path.name: path.read_bytes() for path in (self.output / "raw" / "blobs").glob("*.json")
        }
        pages = fixture_pages()
        bad = json.loads(pages["https://api.example.test/orders?page=2"])
        bad["items"][0]["amount"] = "not-a-number"
        pages["https://api.example.test/orders?page=2"] = json.dumps(bad).encode()
        with self.assertRaisesRegex(LOADER.DeliveryError, "invalid decimal"):
            self.run_loader(MappingFetcher(pages), refresh=True)
        self.assertEqual((self.output / "current.json").read_bytes(), pointer)
        self.assertEqual((self.output / "raw" / "cache_index.json").read_bytes(), index)
        for name, body in old_blobs.items():
            self.assertEqual((self.output / "raw" / "blobs" / name).read_bytes(), body)

    def test_manifest_links_snapshot_contracts_dataset_and_checks(self) -> None:
        report, _ = self.run_loader()
        manifest = read_json(self.output / report["current"]["manifest"])
        self.assertEqual(manifest["snapshot"]["id"], report["snapshot_id"])
        self.assertEqual(len(manifest["snapshot"]["pages"]), 3)
        self.assertEqual(set(manifest["contracts"]), {"delivery", "schema", "layout"})
        self.assertEqual(manifest["dataset"]["rows"], 5)
        self.assertTrue(all(manifest["checks"].values()))
        self.assertEqual(
            set(manifest["workload"]),
            {
                "monthly_orders",
                "currency_orders",
                "monthly_currency_orders",
            },
        )

    def test_manifest_and_report_contain_no_absolute_local_paths(self) -> None:
        report, _ = self.run_loader()
        manifest = read_json(self.output / report["current"]["manifest"])
        rendered = json.dumps({"report": report, "manifest": manifest})
        self.assertNotIn(str(self.temp), rendered)
        self.assertNotIn("/Users/", rendered)

    def test_current_manifest_checksum_is_valid(self) -> None:
        report, _ = self.run_loader()
        current = read_json(self.output / "current.json")
        manifest = self.output / current["manifest"]
        self.assertEqual(current["manifest_sha256"], LOADER.sha256_file(manifest))
        self.assertEqual(current, report["current"])

    def test_pipeline_version_change_changes_run_id(self) -> None:
        first, _ = self.run_loader()
        contract = read_json(self.delivery)
        contract["pipeline_version"] = "orders-delivery-v2"
        write_json(self.delivery, contract)
        second, _ = self.run_loader(FailingFetcher())
        self.assertNotEqual(second["run_id"], first["run_id"])

    def test_schema_digest_change_changes_run_id(self) -> None:
        first, _ = self.run_loader()
        contract = read_json(self.schema)
        contract["writer"]["row_group_size"] = 4
        write_json(self.schema, contract)
        second, _ = self.run_loader(FailingFetcher())
        self.assertNotEqual(second["run_id"], first["run_id"])

    def test_layout_digest_change_changes_run_id(self) -> None:
        first, _ = self.run_loader()
        contract = read_json(self.layout)
        contract["diagnostics"]["small_partition_rows"] = 3
        write_json(self.layout, contract)
        second, _ = self.run_loader(FailingFetcher())
        self.assertNotEqual(second["run_id"], first["run_id"])

    def test_corrupted_existing_parquet_blocks_reuse_and_pointer_change(self) -> None:
        report, _ = self.run_loader()
        pointer = (self.output / "current.json").read_bytes()
        relative = next(iter(report["dataset"]["files"]))
        (self.output / "datasets" / report["run_id"] / relative).write_bytes(b"broken")
        with self.assertRaisesRegex(LOADER.DeliveryError, "checksum verification"):
            self.run_loader(FailingFetcher())
        self.assertEqual((self.output / "current.json").read_bytes(), pointer)

    def test_corrupted_existing_manifest_blocks_reuse(self) -> None:
        report, _ = self.run_loader()
        manifest = self.output / report["current"]["manifest"]
        value = read_json(manifest)
        value["pipeline_version"] = "tampered"
        write_json(manifest, value)
        with self.assertRaisesRegex(LOADER.DeliveryError, "does not match"):
            self.run_loader(FailingFetcher())

    def test_extra_parquet_file_blocks_reuse(self) -> None:
        report, _ = self.run_loader()
        version = self.output / "datasets" / report["run_id"]
        source = next((version / "data").rglob("*.parquet"))
        shutil.copy2(source, version / "data" / "extra.parquet")
        with self.assertRaisesRegex(LOADER.DeliveryError, "file list differs"):
            self.run_loader(FailingFetcher())

    def test_semantic_drift_is_detected_even_with_updated_file_checksum(self) -> None:
        report, _ = self.run_loader()
        version = self.output / "datasets" / report["run_id"]
        relative = next(iter(report["dataset"]["files"]))
        parquet = version / relative
        table = pq.ParquetFile(parquet).read()
        rows = table.to_pylist()
        rows[0]["amount"] = Decimal("999.99")
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), parquet)
        manifest_path = version / "manifest.json"
        manifest = read_json(manifest_path)
        manifest["dataset"]["files"][relative] = {
            "bytes": parquet.stat().st_size,
            "sha256": LOADER.sha256_file(parquet),
        }
        write_json(manifest_path, manifest)
        with self.assertRaisesRegex(LOADER.DeliveryError, "values differ"):
            self.run_loader(FailingFetcher())

    def test_similar_staging_directory_is_not_deleted(self) -> None:
        marker = self.output / "datasets" / ".manual.staging" / "marker.txt"
        marker.parent.mkdir(parents=True)
        marker.write_text("keep", encoding="utf-8")
        self.run_loader()
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_failed_candidate_verification_cleans_unique_staging(self) -> None:
        original = LOADER._verify_package
        calls = 0

        def fail_first(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise LOADER.DeliveryError("injected verification failure")
            return original(*args, **kwargs)

        with (
            mock.patch.object(LOADER, "_verify_package", side_effect=fail_first),
            self.assertRaisesRegex(LOADER.DeliveryError, "injected"),
        ):
            self.run_loader()
        versions = self.output / "datasets"
        self.assertEqual(list(versions.glob(".*.staging")), [])
        self.assertFalse((self.output / "current.json").exists())

    def test_relative_same_origin_next_is_accepted(self) -> None:
        pages = fixture_pages()
        first = json.loads(pages[START_URL])
        first["next"] = "?page=2"
        pages[START_URL] = json.dumps(first).encode()
        report, fetcher = self.run_loader(MappingFetcher(pages))
        self.assertEqual(report["source"]["pages"], 3)
        self.assertEqual(fetcher.calls[1], "https://api.example.test/orders?page=2")

    def test_cross_origin_next_is_rejected_before_fetch(self) -> None:
        pages = fixture_pages()
        first = json.loads(pages[START_URL])
        first["next"] = "https://evil.example/orders?page=2"
        pages[START_URL] = json.dumps(first).encode()
        fetcher = MappingFetcher(pages)
        with self.assertRaisesRegex(LOADER.DeliveryError, "outside"):
            self.run_loader(fetcher)
        self.assertEqual(fetcher.calls, [START_URL])

    def test_https_downgrade_next_is_rejected(self) -> None:
        pages = fixture_pages()
        first = json.loads(pages[START_URL])
        first["next"] = "http://api.example.test/orders?page=2"
        pages[START_URL] = json.dumps(first).encode()
        with self.assertRaisesRegex(LOADER.DeliveryError, "HTTPS"):
            self.run_loader(MappingFetcher(pages))

    def test_missing_next_is_rejected(self) -> None:
        pages = fixture_pages()
        first = json.loads(pages[START_URL])
        del first["next"]
        pages[START_URL] = json.dumps(first).encode()
        with self.assertRaisesRegex(LOADER.DeliveryError, "missing"):
            self.run_loader(MappingFetcher(pages))

    def test_duplicate_page_json_key_is_rejected(self) -> None:
        pages = fixture_pages()
        pages[START_URL] = b'{"items": [], "items": [], "next": null, "page": 1}'
        with self.assertRaisesRegex(LOADER.DeliveryError, "duplicate JSON key"):
            self.run_loader(MappingFetcher(pages))

    def test_page_number_mismatch_is_rejected(self) -> None:
        pages = fixture_pages()
        first = json.loads(pages[START_URL])
        first["page"] = 2
        pages[START_URL] = json.dumps(first).encode()
        with self.assertRaisesRegex(LOADER.DeliveryError, "page number"):
            self.run_loader(MappingFetcher(pages))

    def test_pagination_cycle_is_rejected_before_extra_fetch(self) -> None:
        pages = fixture_pages()
        second_url = "https://api.example.test/orders?page=2"
        second = json.loads(pages[second_url])
        second["next"] = START_URL
        pages[second_url] = json.dumps(second).encode()
        fetcher = MappingFetcher(pages)
        with self.assertRaisesRegex(LOADER.DeliveryError, "cycle"):
            self.run_loader(fetcher)
        self.assertEqual(fetcher.calls, [START_URL, second_url])

    def test_max_pages_is_enforced(self) -> None:
        contract = read_json(self.delivery)
        contract["source"]["max_pages"] = 2
        write_json(self.delivery, contract)
        with self.assertRaisesRegex(LOADER.DeliveryError, "max_pages"):
            self.run_loader(MappingFetcher(fixture_pages()))

    def test_duplicate_grain_is_rejected(self) -> None:
        pages = fixture_pages()
        second_url = "https://api.example.test/orders?page=2"
        second = json.loads(pages[second_url])
        second["items"][0]["order_id"] = "O2301"
        pages[second_url] = json.dumps(second).encode()
        with self.assertRaisesRegex(LOADER.DeliveryError, "grain"):
            self.run_loader(MappingFetcher(pages))

    def test_missing_record_field_is_rejected(self) -> None:
        pages = fixture_pages()
        first = json.loads(pages[START_URL])
        del first["items"][0]["currency"]
        pages[START_URL] = json.dumps(first).encode()
        with self.assertRaisesRegex(LOADER.DeliveryError, "missing"):
            self.run_loader(MappingFetcher(pages))

    def test_domain_drift_is_rejected(self) -> None:
        pages = fixture_pages()
        first = json.loads(pages[START_URL])
        first["items"][0]["currency"] = "USD"
        pages[START_URL] = json.dumps(first).encode()
        with self.assertRaisesRegex(LOADER.DeliveryError, "domain"):
            self.run_loader(MappingFetcher(pages))

    def test_naive_timestamp_is_rejected(self) -> None:
        pages = fixture_pages()
        first = json.loads(pages[START_URL])
        first["items"][0]["ordered_at"] = "2026-05-01T10:00:00"
        pages[START_URL] = json.dumps(first).encode()
        with self.assertRaisesRegex(LOADER.DeliveryError, "requires Z"):
            self.run_loader(MappingFetcher(pages))

    def test_decimal_scale_drift_is_rejected(self) -> None:
        pages = fixture_pages()
        first = json.loads(pages[START_URL])
        first["items"][0]["amount"] = "1.999"
        pages[START_URL] = json.dumps(first).encode()
        with self.assertRaisesRegex(LOADER.DeliveryError, "scale"):
            self.run_loader(MappingFetcher(pages))

    def test_page_size_limit_applies_to_local_fetcher(self) -> None:
        contract = read_json(self.delivery)
        contract["http"]["max_page_bytes"] = 10
        write_json(self.delivery, contract)
        with self.assertRaisesRegex(LOADER.DeliveryError, "max_page_bytes"):
            self.run_loader()

    def test_delivery_contract_rejects_unknown_key(self) -> None:
        contract = read_json(self.delivery)
        contract["surprise"] = True
        write_json(self.delivery, contract)
        with self.assertRaisesRegex(LOADER.ContractError, "unknown"):
            self.run_loader()

    def test_delivery_contract_rejects_duplicate_key(self) -> None:
        self.delivery.write_text(
            '{"version":"1.0.0","version":"1.0.0"}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(LOADER.ContractError, "duplicate JSON key"):
            self.run_loader()

    def test_delivery_contract_rejects_version_drift(self) -> None:
        contract = read_json(self.delivery)
        contract["version"] = "2.0.0"
        write_json(self.delivery, contract)
        with self.assertRaisesRegex(LOADER.ContractError, "unsupported"):
            self.run_loader()

    def test_delivery_contract_rejects_start_url_outside_origin(self) -> None:
        contract = read_json(self.delivery)
        contract["source"]["start_url"] = "https://evil.example/orders?page=1"
        write_json(self.delivery, contract)
        with self.assertRaisesRegex(LOADER.ContractError, "outside"):
            self.run_loader()

    def test_delivery_contract_rejects_secret_query_parameter(self) -> None:
        contract = read_json(self.delivery)
        contract["source"]["start_url"] += "&api_key=secret"
        write_json(self.delivery, contract)
        with self.assertRaisesRegex(LOADER.ContractError, "secret query"):
            self.run_loader()

    def test_schema_contract_rejects_old_object_shape(self) -> None:
        contract = read_json(self.schema)
        contract["columns"] = {column["name"]: column for column in contract["columns"]}
        write_json(self.schema, contract)
        with self.assertRaisesRegex(LOADER.ContractError, "non-empty list"):
            self.run_loader()

    def test_layout_contract_rejects_missing_selected_candidate(self) -> None:
        contract = read_json(self.layout)
        contract["selected"] = "missing"
        write_json(self.layout, contract)
        with self.assertRaisesRegex(LOADER.ContractError, "selected"):
            self.run_loader()

    def test_corrupt_cache_index_is_not_silently_ignored(self) -> None:
        cache = self.output / "raw" / "cache_index.json"
        cache.parent.mkdir(parents=True)
        write_json(
            cache,
            {
                "version": "1.0.0",
                "entries": {
                    START_URL: {
                        "sha256": "bad",
                        "bytes": 10,
                    }
                },
            },
        )
        with self.assertRaisesRegex(LOADER.ContractError, "invalid sha256"):
            self.run_loader()

    def test_cache_index_cannot_supply_a_path(self) -> None:
        cache = self.output / "raw" / "cache_index.json"
        cache.parent.mkdir(parents=True)
        write_json(
            cache,
            {
                "version": "1.0.0",
                "entries": {
                    START_URL: {
                        "sha256": "0" * 64,
                        "bytes": 10,
                        "file": "../../outside",
                    }
                },
            },
        )
        with self.assertRaisesRegex(LOADER.ContractError, "unknown"):
            self.run_loader()

    def test_cli_runs_fully_offline(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--contract",
                self.delivery,
                "--schema",
                self.schema,
                "--layout-contract",
                self.layout,
                "--source-dir",
                SOURCE,
                "--output-dir",
                self.output,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["summary"]["valid"])

    def test_cli_returns_two_for_invalid_contract(self) -> None:
        self.delivery.write_text("{}", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                ARTIFACT,
                "--contract",
                self.delivery,
                "--schema",
                self.schema,
                "--layout-contract",
                self.layout,
                "--source-dir",
                SOURCE,
                "--output-dir",
                self.output,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stderr))

    def test_output_path_collision_is_rejected(self) -> None:
        with self.assertRaisesRegex(LOADER.ContractError, "output-dir"):
            LOADER.run_loader(
                self.delivery,
                self.delivery,
                self.schema,
                self.layout,
                LOADER.LocalPageFetcher(SOURCE),
            )


if __name__ == "__main__":
    unittest.main()
