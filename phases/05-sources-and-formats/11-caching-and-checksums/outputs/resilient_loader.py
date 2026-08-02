from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urljoin, urlparse

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import requests

DELIVERY_VERSION = "1.0.0"
SCHEMA_VERSION = "2.0.0"
LAYOUT_VERSION = "1.0.0"
CACHE_VERSION = "1.0.0"
MANIFEST_VERSION = "1.0.0"
MAX_CONTRACT_BYTES = 1_000_000
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
DECIMAL_PATTERN = re.compile(r"decimal128\((\d+),\s*(\d+)\)")
OFFSET_PATTERN = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")


class DeliveryError(RuntimeError):
    """Raised when source data or a delivery candidate cannot be trusted."""


class ContractError(DeliveryError):
    """Raised when a declared contract or local configuration is invalid."""


class PageFetcher(Protocol):
    def __call__(self, url: str) -> bytes: ...


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as error:
        raise DeliveryError(f"cannot read file for checksum: {path.name}") from error


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-finite JSON number is forbidden: {value}")


def _parse_json(raw: bytes, *, label: str) -> Any:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ContractError(f"{label} must be valid UTF-8") from error
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ContractError(f"invalid {label} JSON: {error.msg}") from error


def _read_bounded(path: Path, *, label: str) -> bytes:
    if not path.is_file():
        raise ContractError(f"{label} file does not exist: {path}")
    try:
        size = path.stat().st_size
        if size > MAX_CONTRACT_BYTES:
            raise ContractError(f"{label} exceeds {MAX_CONTRACT_BYTES} bytes")
        return path.read_bytes()
    except OSError as error:
        raise ContractError(f"cannot read {label}: {error}") from error


def _exact_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    label: str,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - required - optional)
    if missing:
        raise ContractError(f"{label} misses keys: {missing}")
    if unknown:
        raise ContractError(f"{label} has unknown keys: {unknown}")


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _positive_number(value: Any, label: str) -> float:
    if type(value) not in {int, float} or value <= 0:
        raise ContractError(f"{label} must be a positive number")
    return float(value)


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


def _validate_url(url: Any, *, origin: tuple[str, str, int | None], label: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ContractError(f"{label} must be a non-empty URL")
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ContractError(f"{label} must use absolute HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise ContractError(f"{label} must not contain credentials or a fragment")
    forbidden_query_keys = {
        "access_token",
        "api_key",
        "key",
        "password",
        "secret",
        "sig",
        "signature",
    }
    observed_query_keys = {key.lower() for key in parse_qs(parsed.query)}
    if observed_query_keys & forbidden_query_keys:
        raise ContractError(f"{label} must not contain a secret query parameter")
    if _origin(url) != origin:
        raise DeliveryError(f"{label} points outside the declared origin")
    return url


def load_delivery_contract(path: str | Path) -> tuple[dict[str, Any], str]:
    raw = _read_bounded(Path(path), label="delivery contract")
    value = _parse_json(raw, label="delivery contract")
    if not isinstance(value, dict):
        raise ContractError("delivery contract root must be an object")
    _exact_keys(
        value,
        required={"version", "pipeline_version", "source", "http", "integrity"},
        label="delivery contract",
    )
    if value["version"] != DELIVERY_VERSION:
        raise ContractError(f"unsupported delivery contract version: {value['version']!r}")
    if not isinstance(value["pipeline_version"], str) or not value["pipeline_version"]:
        raise ContractError("pipeline_version must be a non-empty string")

    source = value["source"]
    if not isinstance(source, dict):
        raise ContractError("source must be an object")
    _exact_keys(
        source,
        required={
            "start_url",
            "allowed_origin",
            "items_field",
            "next_field",
            "page_number_field",
            "max_pages",
        },
        label="source",
    )
    if not isinstance(source["allowed_origin"], str):
        raise ContractError("allowed_origin must be a string")
    origin = _origin(source["allowed_origin"])
    if (
        origin[0] != "https"
        or not origin[1]
        or urlparse(source["allowed_origin"]).path
        not in {
            "",
            "/",
        }
    ):
        raise ContractError("allowed_origin must contain only an HTTPS origin")
    try:
        _validate_url(source["start_url"], origin=origin, label="start_url")
    except DeliveryError as error:
        raise ContractError(str(error)) from error
    fields = [source[name] for name in ("items_field", "next_field", "page_number_field")]
    if any(not isinstance(name, str) or not name for name in fields) or len(set(fields)) != 3:
        raise ContractError("page field names must be three unique non-empty strings")
    _positive_int(source["max_pages"], "source.max_pages")

    http = value["http"]
    if not isinstance(http, dict):
        raise ContractError("http must be an object")
    _exact_keys(
        http,
        required={
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "max_page_bytes",
            "max_redirects",
            "retries_per_page",
            "backoff_factor_seconds",
            "max_retry_after_seconds",
        },
        label="http",
    )
    _positive_number(http["connect_timeout_seconds"], "http.connect_timeout_seconds")
    _positive_number(http["read_timeout_seconds"], "http.read_timeout_seconds")
    _positive_int(http["max_page_bytes"], "http.max_page_bytes")
    if type(http["max_redirects"]) is not int or http["max_redirects"] < 0:
        raise ContractError("http.max_redirects must be a non-negative integer")
    if type(http["retries_per_page"]) is not int or http["retries_per_page"] < 0:
        raise ContractError("http.retries_per_page must be a non-negative integer")
    _positive_number(http["backoff_factor_seconds"], "http.backoff_factor_seconds")
    _positive_number(http["max_retry_after_seconds"], "http.max_retry_after_seconds")

    integrity = value["integrity"]
    if not isinstance(integrity, dict):
        raise ContractError("integrity must be an object")
    _exact_keys(integrity, required={"algorithm"}, label="integrity")
    if integrity["algorithm"] != "sha256":
        raise ContractError("only sha256 integrity is supported")
    return value, sha256_bytes(raw)


def _arrow_type(type_name: Any) -> pa.DataType:
    if type_name == "string":
        return pa.string()
    if type_name == "timestamp[us, tz=UTC]":
        return pa.timestamp("us", tz="UTC")
    if isinstance(type_name, str):
        match = DECIMAL_PATTERN.fullmatch(type_name)
        if match:
            precision, scale = (int(item) for item in match.groups())
            if 1 <= precision <= 38 and 0 <= scale <= precision:
                return pa.decimal128(precision, scale)
    raise ContractError(f"unsupported schema type: {type_name!r}")


def load_schema_contract(path: str | Path) -> tuple[dict[str, Any], pa.Schema, str]:
    raw = _read_bounded(Path(path), label="schema contract")
    value = _parse_json(raw, label="schema contract")
    if not isinstance(value, dict):
        raise ContractError("schema contract root must be an object")
    _exact_keys(
        value,
        required={"version", "grain", "allow_empty", "columns", "writer"},
        label="schema contract",
    )
    if value["version"] != SCHEMA_VERSION:
        raise ContractError(f"unsupported schema contract version: {value['version']!r}")
    if type(value["allow_empty"]) is not bool:
        raise ContractError("allow_empty must be boolean")
    columns = value["columns"]
    if not isinstance(columns, list) or not columns:
        raise ContractError("columns must be a non-empty list")
    names: list[str] = []
    fields: list[pa.Field] = []
    for position, column in enumerate(columns):
        label = f"columns[{position}]"
        if not isinstance(column, dict):
            raise ContractError(f"{label} must be an object")
        _exact_keys(
            column,
            required={"name", "type", "nullable", "empty_as_null"},
            optional={"domain"},
            label=label,
        )
        name = column["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ContractError(f"{label}.name must be unique and non-empty")
        names.append(name)
        if type(column["nullable"]) is not bool or type(column["empty_as_null"]) is not bool:
            raise ContractError(f"{label} null flags must be boolean")
        if column["empty_as_null"] and not column["nullable"]:
            raise ContractError(f"{label} cannot map empty to a forbidden null")
        if "domain" in column:
            domain = column["domain"]
            if (
                column["type"] != "string"
                or not isinstance(domain, list)
                or not domain
                or any(not isinstance(item, str) or not item for item in domain)
                or len(domain) != len(set(domain))
            ):
                raise ContractError(f"{label}.domain must contain unique strings")
        fields.append(pa.field(name, _arrow_type(column["type"]), nullable=column["nullable"]))
    grain = value["grain"]
    if (
        not isinstance(grain, list)
        or not grain
        or any(not isinstance(name, str) for name in grain)
        or len(grain) != len(set(grain))
        or set(grain) - set(names)
    ):
        raise ContractError("grain must contain unique declared column names")
    by_name = {column["name"]: column for column in columns}
    if any(by_name[name]["nullable"] for name in grain):
        raise ContractError("grain columns must be non-null")
    writer = value["writer"]
    if not isinstance(writer, dict):
        raise ContractError("writer must be an object")
    _exact_keys(
        writer,
        required={"compression", "write_statistics", "row_group_size"},
        label="writer",
    )
    if writer["compression"] not in {"zstd", "snappy", "none"}:
        raise ContractError("unsupported writer compression")
    if type(writer["write_statistics"]) is not bool:
        raise ContractError("writer.write_statistics must be boolean")
    _positive_int(writer["row_group_size"], "writer.row_group_size")
    return value, pa.schema(fields), sha256_bytes(raw)


def load_layout_contract(path: str | Path) -> tuple[dict[str, Any], str]:
    raw = _read_bounded(Path(path), label="layout contract")
    value = _parse_json(raw, label="layout contract")
    if not isinstance(value, dict):
        raise ContractError("layout contract root must be an object")
    _exact_keys(
        value,
        required={
            "version",
            "source",
            "derived_columns",
            "candidates",
            "selected",
            "workload",
            "diagnostics",
        },
        label="layout contract",
    )
    if value["version"] != LAYOUT_VERSION:
        raise ContractError(f"unsupported layout contract version: {value['version']!r}")
    rules = value["derived_columns"]
    if not isinstance(rules, list) or not rules:
        raise ContractError("derived_columns must be a non-empty list")
    derived_names: list[str] = []
    for position, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ContractError(f"derived_columns[{position}] must be an object")
        _exact_keys(
            rule,
            required={"name", "source", "transform"},
            label=f"derived_columns[{position}]",
        )
        if (
            any(not isinstance(rule[key], str) or not rule[key] for key in rule)
            or rule["name"] in derived_names
            or rule["transform"] not in {"utc_month", "utc_date"}
        ):
            raise ContractError(f"invalid derived_columns[{position}]")
        derived_names.append(rule["name"])
    candidates = value["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise ContractError("candidates must be a non-empty list")
    by_candidate: dict[str, list[str]] = {}
    for position, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ContractError(f"candidates[{position}] must be an object")
        _exact_keys(
            candidate,
            required={"name", "partition_by"},
            label=f"candidates[{position}]",
        )
        name = candidate["name"]
        keys = candidate["partition_by"]
        if (
            not isinstance(name, str)
            or not name
            or name in by_candidate
            or not isinstance(keys, list)
            or not keys
            or any(not isinstance(key, str) or not key for key in keys)
            or len(keys) != len(set(keys))
        ):
            raise ContractError(f"invalid candidates[{position}]")
        by_candidate[name] = keys
    if value["selected"] not in by_candidate:
        raise ContractError("selected must name a declared candidate")
    workload = value["workload"]
    if not isinstance(workload, list) or not workload:
        raise ContractError("workload must be a non-empty list")
    names: set[str] = set()
    for position, query in enumerate(workload):
        if not isinstance(query, dict):
            raise ContractError(f"workload[{position}] must be an object")
        _exact_keys(query, required={"name", "filters"}, label=f"workload[{position}]")
        if (
            not isinstance(query["name"], str)
            or not query["name"]
            or query["name"] in names
            or not isinstance(query["filters"], dict)
            or not query["filters"]
            or any(
                not isinstance(key, str) or not isinstance(item, str)
                for key, item in query["filters"].items()
            )
        ):
            raise ContractError(f"invalid workload[{position}]")
        names.add(query["name"])
    if not isinstance(value["source"], dict) or not isinstance(value["diagnostics"], dict):
        raise ContractError("layout source and diagnostics must be objects")
    return value, sha256_bytes(raw)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".part",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    except OSError as error:
        raise DeliveryError(f"cannot atomically write {path.name}: {error}") from error
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write(path, _canonical_bytes(value) + b"\n")


class LocalPageFetcher:
    def __init__(self, source_dir: str | Path) -> None:
        self.source_dir = Path(source_dir)
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        query = parse_qs(urlparse(url).query)
        raw_page = query.get("page", ["1"])[0]
        try:
            page = int(raw_page)
        except ValueError as error:
            raise DeliveryError(f"invalid page in URL: {raw_page!r}") from error
        path = self.source_dir / f"api_page_{page}.json"
        if not path.is_file():
            raise DeliveryError(f"local page fixture does not exist: {path.name}")
        try:
            return path.read_bytes()
        except OSError as error:
            raise DeliveryError(f"cannot read local page: {path.name}") from error


class RequestsPageFetcher:
    def __init__(
        self,
        contract: dict[str, Any],
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.http = contract["http"]
        self.origin = _origin(contract["source"]["allowed_origin"])
        self.session = requests.Session()
        self.sleep = sleep

    def _retry_after(self, value: str | None) -> float | None:
        if value is None:
            return None
        try:
            delay = float(value)
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            delay = max(0.0, (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds())
        maximum = float(self.http["max_retry_after_seconds"])
        if delay > maximum:
            raise DeliveryError(f"Retry-After exceeds declared maximum {maximum:g}s")
        return max(0.0, delay)

    def _request_once(self, url: str) -> tuple[bytes | None, float | None]:
        target = url
        for redirects in range(self.http["max_redirects"] + 1):
            _validate_url(target, origin=self.origin, label="request URL")
            try:
                response = self.session.get(
                    target,
                    timeout=(
                        self.http["connect_timeout_seconds"],
                        self.http["read_timeout_seconds"],
                    ),
                    stream=True,
                    allow_redirects=False,
                    headers={"Accept": "application/json"},
                )
            except (requests.Timeout, requests.ConnectionError):
                return None, None
            except requests.RequestException as error:
                raise DeliveryError(f"request failed: {error}") from error
            with response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise DeliveryError("redirect response misses Location")
                    if redirects >= self.http["max_redirects"]:
                        raise DeliveryError("redirect budget exhausted")
                    target = urljoin(target, location)
                    _validate_url(target, origin=self.origin, label="redirect URL")
                    continue
                if response.status_code in {429, 500, 502, 503, 504}:
                    return None, self._retry_after(response.headers.get("Retry-After"))
                try:
                    response.raise_for_status()
                except requests.RequestException as error:
                    raise DeliveryError(
                        f"request failed with status {response.status_code}"
                    ) from error
                media_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if media_type != "application/json":
                    raise DeliveryError(f"unexpected content type: {media_type!r}")
                chunks: list[bytes] = []
                size = 0
                try:
                    for chunk in response.iter_content(64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > self.http["max_page_bytes"]:
                            raise DeliveryError(
                                f"page exceeds max_page_bytes={self.http['max_page_bytes']}"
                            )
                        chunks.append(chunk)
                except requests.RequestException as error:
                    raise DeliveryError(f"response read failed: {error}") from error
                return b"".join(chunks), None
        raise DeliveryError("redirect budget exhausted")

    def __call__(self, url: str) -> bytes:
        attempts = self.http["retries_per_page"] + 1
        for attempt in range(attempts):
            body, retry_after = self._request_once(url)
            if body is not None:
                return body
            if attempt + 1 == attempts:
                break
            delay = retry_after
            if delay is None:
                delay = min(
                    self.http["backoff_factor_seconds"] * 2**attempt,
                    self.http["max_retry_after_seconds"],
                )
            self.sleep(delay)
        raise DeliveryError(f"retry budget exhausted for {urlparse(url).path}")

    def close(self) -> None:
        self.session.close()


def _parse_decimal(value: Any, field: pa.Field, location: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise DeliveryError(f"{location}: expected decimal-compatible value")
    try:
        decimal = Decimal(str(value))
    except InvalidOperation as error:
        raise DeliveryError(f"{location}: invalid decimal") from error
    if not decimal.is_finite():
        raise DeliveryError(f"{location}: decimal must be finite")
    quantum = Decimal(1).scaleb(-field.type.scale)
    try:
        quantized = decimal.quantize(quantum)
    except InvalidOperation as error:
        raise DeliveryError(f"{location}: decimal exceeds {field.type}") from error
    if decimal != quantized:
        raise DeliveryError(f"{location}: decimal exceeds declared scale")
    digits = format(quantized.copy_abs(), "f").replace(".", "").lstrip("0") or "0"
    if len(digits) > field.type.precision:
        raise DeliveryError(f"{location}: decimal exceeds {field.type}")
    return quantized


def _parse_timestamp(value: Any, location: str) -> datetime:
    if not isinstance(value, str) or OFFSET_PATTERN.search(value) is None:
        raise DeliveryError(f"{location}: timestamp requires Z or numeric UTC offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DeliveryError(f"{location}: invalid timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DeliveryError(f"{location}: timestamp is timezone-naive")
    return parsed.astimezone(UTC)


def _convert_record(
    record: Any,
    *,
    schema_contract: dict[str, Any],
    schema: pa.Schema,
    location: str,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise DeliveryError(f"{location}: record must be an object")
    if set(record) != set(schema.names):
        missing = sorted(set(schema.names) - set(record))
        unexpected = sorted(set(record) - set(schema.names))
        raise DeliveryError(f"{location}: missing={missing}, unexpected={unexpected}")
    by_name = {column["name"]: column for column in schema_contract["columns"]}
    converted: dict[str, Any] = {}
    for field in schema:
        value = record[field.name]
        column = by_name[field.name]
        field_location = f"{location}.{field.name}"
        if value is None:
            if not field.nullable:
                raise DeliveryError(f"{field_location}: null is forbidden")
            converted[field.name] = None
        elif pa.types.is_string(field.type):
            if not isinstance(value, str):
                raise DeliveryError(f"{field_location}: expected string")
            if value == "" and column["empty_as_null"]:
                converted[field.name] = None
            else:
                domain = column.get("domain")
                if domain is not None and value not in domain:
                    raise DeliveryError(f"{field_location}: value outside declared domain")
                converted[field.name] = value
        elif pa.types.is_decimal(field.type):
            converted[field.name] = _parse_decimal(value, field, field_location)
        elif pa.types.is_timestamp(field.type):
            converted[field.name] = _parse_timestamp(value, field_location)
        else:  # pragma: no cover - contract parser prevents this branch
            raise DeliveryError(f"{field_location}: unsupported type")
    return converted


def _cache_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    raw = _read_bounded(path, label="cache index")
    value = _parse_json(raw, label="cache index")
    if not isinstance(value, dict):
        raise ContractError("cache index root must be an object")
    _exact_keys(value, required={"version", "entries"}, label="cache index")
    if value["version"] != CACHE_VERSION or not isinstance(value["entries"], dict):
        raise ContractError("unsupported or invalid cache index")
    entries: dict[str, dict[str, Any]] = {}
    for url, entry in value["entries"].items():
        if not isinstance(url, str) or not isinstance(entry, dict):
            raise ContractError("cache index entries must map URLs to objects")
        _exact_keys(entry, required={"sha256", "bytes"}, label=f"cache entry {url!r}")
        if not isinstance(entry["sha256"], str) or not SHA256_PATTERN.fullmatch(entry["sha256"]):
            raise ContractError(f"cache entry has invalid sha256: {url!r}")
        if type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise ContractError(f"cache entry has invalid byte count: {url!r}")
        entries[url] = entry
    return entries


def _blob_path(raw_dir: Path, digest: str) -> Path:
    if not SHA256_PATTERN.fullmatch(digest):
        raise ContractError("invalid raw blob digest")
    return raw_dir / "blobs" / f"{digest}.json"


def _put_blob(raw_dir: Path, body: bytes) -> tuple[str, Path]:
    digest = sha256_bytes(body)
    path = _blob_path(raw_dir, digest)
    if not path.is_file() or sha256_file(path) != digest:
        _atomic_write(path, body)
    return digest, path


def _read_cached_or_fetch(
    url: str,
    *,
    raw_dir: Path,
    cache_index: dict[str, dict[str, Any]],
    fetch_page: PageFetcher,
    refresh: bool,
    max_page_bytes: int,
) -> tuple[bytes, bool, dict[str, Any]]:
    entry = cache_index.get(url)
    if not refresh and entry is not None:
        path = _blob_path(raw_dir, entry["sha256"])
        if (
            path.is_file()
            and path.stat().st_size == entry["bytes"]
            and sha256_file(path) == entry["sha256"]
        ):
            return path.read_bytes(), True, dict(entry)
    body = fetch_page(url)
    if len(body) > max_page_bytes:
        raise DeliveryError(f"page exceeds max_page_bytes={max_page_bytes}")
    digest, _ = _put_blob(raw_dir, body)
    return body, False, {"sha256": digest, "bytes": len(body)}


def _parse_page(
    body: bytes,
    *,
    url: str,
    position: int,
    delivery: dict[str, Any],
    schema_contract: dict[str, Any],
    schema: pa.Schema,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = _parse_json(body, label=f"page {position}")
    except ContractError as error:
        raise DeliveryError(str(error)) from error
    if not isinstance(payload, dict):
        raise DeliveryError(f"page {position}: root must be an object")
    source = delivery["source"]
    expected_fields = {
        source["items_field"],
        source["next_field"],
        source["page_number_field"],
    }
    if set(payload) != expected_fields:
        missing = sorted(expected_fields - set(payload))
        unexpected = sorted(set(payload) - expected_fields)
        raise DeliveryError(f"page {position}: missing={missing}, unexpected={unexpected}")
    if payload[source["page_number_field"]] != position:
        raise DeliveryError(f"page {position}: page number does not match chain position")
    items = payload[source["items_field"]]
    if not isinstance(items, list):
        raise DeliveryError(f"page {position}: items must be a list")
    records = [
        _convert_record(
            item,
            schema_contract=schema_contract,
            schema=schema,
            location=f"page[{position}].items[{item_position}]",
        )
        for item_position, item in enumerate(items, start=1)
    ]
    next_value = payload[source["next_field"]]
    if next_value is None:
        return records, None
    if not isinstance(next_value, str) or not next_value.strip():
        raise DeliveryError(f"page {position}: next must be a non-empty string or null")
    next_url = urljoin(url, next_value)
    origin = _origin(source["allowed_origin"])
    try:
        validated_next = _validate_url(next_url, origin=origin, label="next URL")
    except ContractError as error:
        raise DeliveryError(str(error)) from error
    return records, validated_next


def _schema_manifest(schema: pa.Schema) -> list[dict[str, Any]]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in schema
    ]


def _add_derived_columns(table: pa.Table, layout: dict[str, Any]) -> pa.Table:
    result = table
    for rule in layout["derived_columns"]:
        if rule["source"] not in result.column_names:
            raise ContractError(f"derived source is absent: {rule['source']}")
        source = result[rule["source"]]
        if not pa.types.is_timestamp(source.type):
            raise ContractError(f"derived source must be timestamp: {rule['source']}")
        format_string = "%Y-%m" if rule["transform"] == "utc_month" else "%Y-%m-%d"
        result = result.append_column(rule["name"], pc.strftime(source, format=format_string))
    return result


def _selected_partition_by(layout: dict[str, Any]) -> list[str]:
    for candidate in layout["candidates"]:
        if candidate["name"] == layout["selected"]:
            return candidate["partition_by"]
    raise ContractError("selected layout candidate is absent")


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _canonical_rows(table: pa.Table, grain: list[str]) -> list[dict[str, Any]]:
    rows = [
        {key: _canonical_value(value) for key, value in row.items()} for row in table.to_pylist()
    ]
    return sorted(rows, key=lambda row: tuple(str(row[name]) for name in grain))


def _filter_table(table: pa.Table, filters: dict[str, str]) -> pa.Table:
    expression = None
    for name, value in sorted(filters.items()):
        if name not in table.column_names:
            raise ContractError(f"workload filter refers to unknown column: {name}")
        predicate = pc.equal(table[name], pa.scalar(value, type=table[name].type))
        expression = predicate if expression is None else pc.and_(expression, predicate)
    return table.filter(expression)


def _workload_evidence(table: pa.Table, layout: dict[str, Any]) -> dict[str, Any]:
    grain = layout["source"].get("grain", ["order_id"])
    return {
        query["name"]: {
            "filters": query["filters"],
            "rows": _filter_table(table, query["filters"]).num_rows,
            "grain_values": [
                [row[name] for name in grain]
                for row in _canonical_rows(_filter_table(table, query["filters"]), grain)
            ],
        }
        for query in layout["workload"]
    }


def _contract_manifest(
    delivery: dict[str, Any],
    delivery_digest: str,
    schema_contract: dict[str, Any],
    schema_digest: str,
    layout: dict[str, Any],
    layout_digest: str,
) -> dict[str, Any]:
    return {
        "delivery": {"version": delivery["version"], "sha256": delivery_digest},
        "schema": {"version": schema_contract["version"], "sha256": schema_digest},
        "layout": {"version": layout["version"], "sha256": layout_digest},
    }


def _build_manifest(
    *,
    run_id: str,
    delivery: dict[str, Any],
    contracts: dict[str, Any],
    snapshot: dict[str, Any],
    table: pa.Table,
    layout: dict[str, Any],
    staging: Path,
) -> dict[str, Any]:
    files = sorted((staging / "data").rglob("*.parquet"))
    return {
        "manifest_version": MANIFEST_VERSION,
        "run_id": run_id,
        "pipeline_version": delivery["pipeline_version"],
        "snapshot": snapshot,
        "contracts": contracts,
        "dataset": {
            "rows": table.num_rows,
            "grain": layout["source"].get("grain", ["order_id"]),
            "partition_by": _selected_partition_by(layout),
            "schema": _schema_manifest(table.schema),
            "files": {
                path.relative_to(staging).as_posix(): {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in files
            },
        },
        "workload": _workload_evidence(table, layout),
        "checks": {
            "raw_blobs_verified": True,
            "file_checksums_verified": True,
            "semantic_roundtrip_verified": True,
            "workload_results_verified": True,
        },
    }


def _load_manifest(path: Path) -> dict[str, Any]:
    raw = _read_bounded(path, label="version manifest")
    value = _parse_json(raw, label="version manifest")
    if not isinstance(value, dict):
        raise DeliveryError("version manifest root must be an object")
    _exact_keys(
        value,
        required={
            "manifest_version",
            "run_id",
            "pipeline_version",
            "snapshot",
            "contracts",
            "dataset",
            "workload",
            "checks",
        },
        label="version manifest",
    )
    if value["manifest_version"] != MANIFEST_VERSION:
        raise DeliveryError("unsupported version manifest")
    return value


def _verify_package(
    package_dir: Path,
    *,
    expected_manifest: dict[str, Any],
    expected_table: pa.Table,
    layout: dict[str, Any],
) -> None:
    manifest_path = package_dir / "manifest.json"
    observed = _load_manifest(manifest_path) if manifest_path.is_file() else expected_manifest
    if observed != expected_manifest:
        raise DeliveryError("version manifest does not match current snapshot and contracts")
    declared_files = observed["dataset"].get("files")
    if not isinstance(declared_files, dict) or not declared_files:
        raise DeliveryError("version manifest must declare Parquet files")
    actual_files = {
        path.relative_to(package_dir).as_posix()
        for path in (package_dir / "data").rglob("*.parquet")
    }
    if set(declared_files) != actual_files:
        raise DeliveryError("manifest file list differs from package contents")
    for relative, metadata in declared_files.items():
        path = package_dir / relative
        if (
            not isinstance(metadata, dict)
            or set(metadata) != {"bytes", "sha256"}
            or path.stat().st_size != metadata["bytes"]
            or sha256_file(path) != metadata["sha256"]
        ):
            raise DeliveryError(f"checksum verification failed for {relative}")
    partition_schema = pa.schema(
        [expected_table.schema.field(name) for name in _selected_partition_by(layout)]
    )
    dataset = ds.dataset(
        package_dir / "data",
        format="parquet",
        partitioning=ds.partitioning(partition_schema, flavor="hive"),
    )
    try:
        observed_table = dataset.to_table(columns=expected_table.column_names)
    except (pa.ArrowInvalid, pa.ArrowTypeError, KeyError) as error:
        raise DeliveryError(f"cannot read logical dataset: {error}") from error
    grain = observed["dataset"]["grain"]
    if _schema_manifest(observed_table.schema) != _schema_manifest(expected_table.schema):
        raise DeliveryError("logical dataset schema differs from expected schema")
    if _canonical_rows(observed_table, grain) != _canonical_rows(expected_table, grain):
        raise DeliveryError("logical dataset values differ from validated source")
    if _workload_evidence(observed_table, layout) != observed["workload"]:
        raise DeliveryError("logical dataset workload results differ from manifest")


def _publish_or_reuse_version(
    table: pa.Table,
    *,
    versions_dir: Path,
    run_id: str,
    delivery: dict[str, Any],
    contracts: dict[str, Any],
    snapshot: dict[str, Any],
    schema_contract: dict[str, Any],
    layout: dict[str, Any],
) -> tuple[Path, dict[str, Any], bool]:
    logical_table = _add_derived_columns(table, layout)
    version_dir = versions_dir / run_id
    if version_dir.exists() and not version_dir.is_dir():
        raise DeliveryError("immutable version path is not a directory")
    partition_by = _selected_partition_by(layout)
    if any(name not in logical_table.column_names for name in partition_by):
        raise ContractError("selected partition columns are absent from logical table")
    versions_dir.mkdir(parents=True, exist_ok=True)
    if version_dir.is_dir():
        manifest = _load_manifest(version_dir / "manifest.json")
        expected = _build_manifest(
            run_id=run_id,
            delivery=delivery,
            contracts=contracts,
            snapshot=snapshot,
            table=logical_table,
            layout=layout,
            staging=version_dir,
        )
        expected["dataset"]["files"] = manifest["dataset"].get("files")
        _verify_package(
            version_dir,
            expected_manifest=expected,
            expected_table=logical_table,
            layout=layout,
        )
        return version_dir, manifest, True

    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{run_id[:12]}.",
            suffix=".staging",
            dir=versions_dir,
        )
    )
    try:
        writer = schema_contract["writer"]
        partition_schema = pa.schema([logical_table.schema.field(name) for name in partition_by])
        ds.write_dataset(
            logical_table,
            staging / "data",
            format="parquet",
            partitioning=ds.partitioning(partition_schema, flavor="hive"),
            basename_template="part-{i}.parquet",
            file_options=ds.ParquetFileFormat().make_write_options(
                compression=writer["compression"],
                write_statistics=writer["write_statistics"],
            ),
            max_rows_per_group=writer["row_group_size"],
        )
        manifest = _build_manifest(
            run_id=run_id,
            delivery=delivery,
            contracts=contracts,
            snapshot=snapshot,
            table=logical_table,
            layout=layout,
            staging=staging,
        )
        _atomic_write_json(staging / "manifest.json", manifest)
        _verify_package(
            staging,
            expected_manifest=manifest,
            expected_table=logical_table,
            layout=layout,
        )
        try:
            staging.rename(version_dir)
        except FileExistsError:
            _verify_package(
                version_dir,
                expected_manifest=manifest,
                expected_table=logical_table,
                layout=layout,
            )
            return version_dir, manifest, True
        return version_dir, manifest, False
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _validate_input_paths(output: Path, inputs: list[Path]) -> None:
    if output.exists() and not output.is_dir():
        raise ContractError("output-dir must be a directory path")
    resolved_output = output.resolve()
    for path in inputs:
        resolved = path.resolve()
        if resolved == resolved_output or resolved.is_relative_to(resolved_output):
            raise ContractError("input contracts must not be stored inside output-dir")


def run_loader(
    output_dir: str | Path,
    delivery_contract_path: str | Path,
    schema_contract_path: str | Path,
    layout_contract_path: str | Path,
    fetch_page: PageFetcher,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    output = Path(output_dir)
    delivery_path = Path(delivery_contract_path)
    schema_path = Path(schema_contract_path)
    layout_path = Path(layout_contract_path)
    _validate_input_paths(output, [delivery_path, schema_path, layout_path])
    delivery, delivery_digest = load_delivery_contract(delivery_path)
    schema_contract, schema, schema_digest = load_schema_contract(schema_path)
    layout, layout_digest = load_layout_contract(layout_path)
    raw_dir = output / "raw"
    cache_path = raw_dir / "cache_index.json"
    cache_index = _cache_index(cache_path)
    new_cache = dict(cache_index)
    origin = _origin(delivery["source"]["allowed_origin"])
    url: str | None = _validate_url(
        delivery["source"]["start_url"],
        origin=origin,
        label="start_url",
    )
    visited: set[str] = set()
    pages: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    reused_pages = 0
    while url is not None:
        if len(pages) >= delivery["source"]["max_pages"]:
            raise DeliveryError("max_pages reached before next=null")
        if url in visited:
            raise DeliveryError("pagination cycle detected")
        visited.add(url)
        body, reused, entry = _read_cached_or_fetch(
            url,
            raw_dir=raw_dir,
            cache_index=cache_index,
            fetch_page=fetch_page,
            refresh=refresh,
            max_page_bytes=delivery["http"]["max_page_bytes"],
        )
        page_number = len(pages) + 1
        page_records, next_url = _parse_page(
            body,
            url=url,
            position=page_number,
            delivery=delivery,
            schema_contract=schema_contract,
            schema=schema,
        )
        pages.append(
            {
                "url": url,
                "sha256": entry["sha256"],
                "bytes": entry["bytes"],
                "items": len(page_records),
            }
        )
        records.extend(page_records)
        new_cache[url] = entry
        reused_pages += int(reused)
        url = next_url

    if not records and not schema_contract["allow_empty"]:
        raise DeliveryError("empty source is forbidden by schema contract")
    grain = schema_contract["grain"]
    grain_values = [tuple(record[name] for name in grain) for record in records]
    if len(grain_values) != len(set(grain_values)):
        raise DeliveryError("source grain is not unique")
    table = pa.Table.from_pylist(records, schema=schema)
    snapshot_material = {
        "start_url": delivery["source"]["start_url"],
        "pages": pages,
    }
    snapshot = {
        "id": sha256_bytes(_canonical_bytes(snapshot_material)),
        **snapshot_material,
    }
    contracts = _contract_manifest(
        delivery,
        delivery_digest,
        schema_contract,
        schema_digest,
        layout,
        layout_digest,
    )
    run_material = {
        "pipeline_version": delivery["pipeline_version"],
        "snapshot_id": snapshot["id"],
        "contracts": contracts,
    }
    run_id = sha256_bytes(_canonical_bytes(run_material))
    version_dir, manifest, reused_version = _publish_or_reuse_version(
        table,
        versions_dir=output / "datasets",
        run_id=run_id,
        delivery=delivery,
        contracts=contracts,
        snapshot=snapshot,
        schema_contract=schema_contract,
        layout=layout,
    )
    _atomic_write_json(
        cache_path,
        {"version": CACHE_VERSION, "entries": new_cache},
    )
    current = {
        "run_id": run_id,
        "snapshot_id": snapshot["id"],
        "dataset": (Path("datasets") / run_id / "data").as_posix(),
        "manifest": (Path("datasets") / run_id / "manifest.json").as_posix(),
        "manifest_sha256": sha256_file(version_dir / "manifest.json"),
    }
    _atomic_write_json(output / "current.json", current)
    return {
        "run_id": run_id,
        "snapshot_id": snapshot["id"],
        "source": {
            "pages": len(pages),
            "rows": table.num_rows,
            "reused_pages": reused_pages,
            "fetched_pages": len(pages) - reused_pages,
        },
        "dataset": {
            "reused_version": reused_version,
            "partition_by": manifest["dataset"]["partition_by"],
            "files": manifest["dataset"]["files"],
        },
        "current": current,
        "checks": manifest["checks"],
        "summary": {"valid": True, "current_updated": True},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay raw pages and publish one verified immutable dataset version"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--layout-contract", required=True, type=Path)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--refresh", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        delivery, _ = load_delivery_contract(args.contract)
        fetcher: Any = (
            LocalPageFetcher(args.source_dir)
            if args.source_dir is not None
            else RequestsPageFetcher(delivery)
        )
        try:
            report = run_loader(
                args.output_dir,
                args.contract,
                args.schema,
                args.layout_contract,
                fetcher,
                refresh=args.refresh,
            )
        finally:
            close = getattr(fetcher, "close", None)
            if close is not None:
                close()
    except ContractError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except DeliveryError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
