from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


class LoaderError(RuntimeError):
    """Raised when raw pages or a dataset version cannot be validated."""


class PageFetcher(Protocol):
    def __call__(self, url: str) -> bytes: ...


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.part")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
    )


class LocalPageFetcher:
    def __init__(self, source_dir: str | Path) -> None:
        self.source_dir = Path(source_dir)
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        query = parse_qs(urlparse(url).query)
        try:
            page = int(query.get("page", ["1"])[0])
        except ValueError as error:
            raise LoaderError(f"invalid page in URL: {url}") from error
        path = self.source_dir / f"api_page_{page}.json"
        if not path.is_file():
            raise LoaderError(f"local page fixture does not exist: {path}")
        return path.read_bytes()


class RequestsPageFetcher:
    def __init__(
        self,
        *,
        timeout: tuple[float, float] = (3.05, 30.0),
        max_bytes: int = 10_000_000,
    ) -> None:
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist={429, 500, 502, 503, 504},
            allowed_methods={"GET"},
            respect_retry_after_header=True,
        )
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.timeout = timeout
        self.max_bytes = max_bytes

    def __call__(self, url: str) -> bytes:
        if urlparse(url).scheme != "https":
            raise LoaderError("network source must use HTTPS")
        try:
            with self.session.get(
                url,
                timeout=self.timeout,
                stream=True,
                headers={"Accept": "application/json"},
            ) as response:
                response.raise_for_status()
                media_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if media_type != "application/json":
                    raise LoaderError(f"unexpected content type: {media_type}")
                chunks = []
                size = 0
                for chunk in response.iter_content(64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise LoaderError(f"page exceeds max_bytes={self.max_bytes}")
                    chunks.append(chunk)
                return b"".join(chunks)
        except requests.RequestException as error:
            raise LoaderError(f"request failed: {error}") from error

    def close(self) -> None:
        self.session.close()


def load_schema(path: str | Path) -> tuple[dict[str, Any], pa.Schema]:
    schema_path = Path(path)
    try:
        contract = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LoaderError(f"cannot read schema contract: {error}") from error
    fields = []
    for name, column in contract["columns"].items():
        type_name = column["type"]
        if type_name == "string":
            value_type = pa.string()
        elif type_name == "timestamp[us, tz=UTC]":
            value_type = pa.timestamp("us", tz="UTC")
        elif type_name == "decimal128(12, 2)":
            value_type = pa.decimal128(12, 2)
        else:
            raise LoaderError(f"unsupported schema type: {type_name}")
        fields.append(pa.field(name, value_type, nullable=column["nullable"]))
    return contract, pa.schema(fields)


def convert_record(record: Any, schema: pa.Schema, location: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise LoaderError(f"{location}: item must be an object")
    missing = [field.name for field in schema if field.name not in record]
    unexpected = sorted(set(record) - set(schema.names))
    if missing or unexpected:
        raise LoaderError(f"{location}: missing={missing}, unexpected={unexpected}")
    converted = {}
    for field in schema:
        value = record[field.name]
        if value is None:
            if not field.nullable:
                raise LoaderError(f"{location}.{field.name}: null is forbidden")
            converted[field.name] = None
        elif pa.types.is_string(field.type):
            if not isinstance(value, str):
                raise LoaderError(f"{location}.{field.name}: expected string")
            converted[field.name] = value
        elif pa.types.is_decimal(field.type):
            try:
                converted[field.name] = Decimal(str(value))
            except InvalidOperation as error:
                raise LoaderError(f"{location}.{field.name}: invalid decimal") from error
        elif pa.types.is_timestamp(field.type):
            if not isinstance(value, str):
                raise LoaderError(f"{location}.{field.name}: expected timestamp string")
            try:
                converted[field.name] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as error:
                raise LoaderError(f"{location}.{field.name}: invalid timestamp") from error
    return converted


def read_cached_or_fetch(
    url: str,
    *,
    raw_dir: Path,
    cache_index: dict[str, Any],
    fetch_page: PageFetcher,
    refresh: bool,
) -> tuple[bytes, bool, dict[str, Any]]:
    entry = cache_index.get(url)
    if not refresh and entry:
        path = raw_dir / entry["file"]
        if path.is_file() and sha256_file(path) == entry["sha256"]:
            return path.read_bytes(), True, entry
    body = fetch_page(url)
    digest = sha256_bytes(body)
    name = f"{hashlib.sha256(url.encode()).hexdigest()[:16]}.json"
    atomic_write(raw_dir / name, body)
    return body, False, {"file": name, "sha256": digest, "bytes": len(body)}


def write_dataset_version(
    table: pa.Table,
    versions_dir: Path,
    run_id: str,
) -> tuple[Path, dict[str, Any], bool]:
    version_dir = versions_dir / run_id
    if version_dir.is_dir():
        manifest = json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
        return version_dir, manifest, True
    staging = versions_dir / f".{run_id}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    versions_dir.mkdir(parents=True, exist_ok=True)
    months = pc.strftime(table["ordered_at"], format="%Y-%m")
    partitioned = table.append_column("order_month", months)
    partition_schema = pa.schema(
        [pa.field("order_month", pa.string()), table.schema.field("currency")]
    )
    try:
        ds.write_dataset(
            partitioned,
            staging / "data",
            format="parquet",
            partitioning=ds.partitioning(partition_schema, flavor="hive"),
            basename_template="part-{i}.parquet",
        )
        files = sorted((staging / "data").rglob("*.parquet"))
        manifest = {
            "run_id": run_id,
            "rows": table.num_rows,
            "partition_by": ["order_month", "currency"],
            "schema": [
                {"name": field.name, "type": str(field.type), "nullable": field.nullable}
                for field in table.schema
            ],
            "files": {
                str(path.relative_to(staging)): {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in files
            },
        }
        atomic_write_json(staging / "manifest.json", manifest)
        staging.rename(version_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return version_dir, manifest, False


def run_loader(
    start_url: str,
    output_dir: str | Path,
    schema_path: str | Path,
    fetch_page: PageFetcher,
    *,
    refresh: bool = False,
    max_pages: int = 100,
) -> dict[str, Any]:
    output = Path(output_dir)
    raw_dir = output / "raw"
    cache_path = raw_dir / "cache_index.json"
    cache_index = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
    new_cache = dict(cache_index)
    pages = []
    records = []
    visited: set[str] = set()
    url: str | None = start_url
    reused_pages = 0
    _, schema = load_schema(schema_path)
    while url is not None:
        if len(pages) >= max_pages:
            raise LoaderError(f"max_pages={max_pages} reached")
        if url in visited:
            raise LoaderError(f"pagination cycle detected: {url}")
        visited.add(url)
        body, reused, entry = read_cached_or_fetch(
            url,
            raw_dir=raw_dir,
            cache_index=cache_index,
            fetch_page=fetch_page,
            refresh=refresh,
        )
        reused_pages += int(reused)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise LoaderError(f"invalid JSON page {url}: {error.msg}") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise LoaderError(f"invalid page shape: {url}")
        page_number = len(pages) + 1
        records.extend(
            convert_record(record, schema, f"page[{page_number}].items[{position}]")
            for position, record in enumerate(payload["items"], start=1)
        )
        next_url = payload.get("next")
        if next_url is not None and not isinstance(next_url, str):
            raise LoaderError(f"invalid next value: {url}")
        new_cache[url] = entry
        pages.append({"url": url, "sha256": entry["sha256"], "items": len(payload["items"])})
        url = next_url

    ids = [record["order_id"] for record in records]
    if len(ids) != len(set(ids)):
        raise LoaderError("order_id grain is not unique")
    table = pa.Table.from_pylist(records, schema=schema)
    contract_digest = sha256_file(Path(schema_path))
    run_material = json.dumps(
        {"pages": [page["sha256"] for page in pages], "schema": contract_digest},
        sort_keys=True,
    ).encode()
    run_id = sha256_bytes(run_material)[:16]
    version_dir, version_manifest, reused_dataset = write_dataset_version(
        table,
        output / "datasets",
        run_id,
    )
    dataset = ds.dataset(version_dir / "data", format="parquet", partitioning="hive")
    if dataset.count_rows() != table.num_rows:
        raise LoaderError("published dataset row count differs from validated table")

    atomic_write_json(cache_path, new_cache)
    current = {
        "run_id": run_id,
        "dataset": str((Path("datasets") / run_id / "data").as_posix()),
        "manifest": str((Path("datasets") / run_id / "manifest.json").as_posix()),
        "manifest_sha256": sha256_file(version_dir / "manifest.json"),
    }
    atomic_write_json(output / "current.json", current)
    report = {
        "run_id": run_id,
        "source": {
            "start_url": start_url,
            "pages": pages,
            "reused_pages": reused_pages,
            "fetched_pages": len(pages) - reused_pages,
        },
        "dataset": {
            "rows": table.num_rows,
            "version_dir": str(version_dir),
            "reused_version": reused_dataset,
            "files": version_manifest["files"],
        },
        "current": current,
        "summary": {
            "valid": True,
            "page_count": len(pages),
            "row_count": table.num_rows,
        },
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache pages and publish verified Parquet")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    fetcher: Any = LocalPageFetcher(args.source_dir) if args.source_dir else RequestsPageFetcher()
    try:
        report = run_loader(
            args.url,
            args.output_dir,
            args.schema,
            fetcher,
            refresh=args.refresh,
        )
    except LoaderError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    finally:
        close = getattr(fetcher, "close", None)
        if close:
            close()
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
