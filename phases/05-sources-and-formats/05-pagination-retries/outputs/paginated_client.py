from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
SENSITIVE_QUERY_NAMES = frozenset(
    {"access_token", "api_key", "apikey", "authorization", "key", "signature", "token"}
)
JSON_CHUNK_SIZE = 64 * 1024


class PaginationError(RuntimeError):
    """A complete paginated snapshot cannot be delivered safely."""

    def __init__(self, kind: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.kind = kind
        self.details = details

    def as_report(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "summary": {"valid": False, "published": False},
            "error": {"kind": self.kind, "message": str(self), "details": self.details},
        }


def redact_url(url: str) -> str:
    """Keep a URL useful for diagnostics without exposing query values or user info."""

    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    query = urlencode(
        [
            (name, "<redacted>" if name.lower() in SENSITIVE_QUERY_NAMES else "<value>")
            for name, _ in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parsed.scheme, host, parsed.path, query, ""))


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    try:
        port = parsed.port
    except ValueError as error:
        raise PaginationError("configuration", "page URL contains an invalid port") from error
    if port is None:
        port = {"http": 80, "https": 443}.get(scheme)
    return scheme, (parsed.hostname or "").lower(), port


def _is_loopback(host: str) -> bool:
    return host.lower() in {"127.0.0.1", "::1", "localhost"}


def validate_page_url(
    url: str,
    *,
    expected_origin: tuple[str, str, int | None] | None = None,
    allow_http: bool = False,
) -> str:
    parsed = urlsplit(url)
    try:
        parsed_port = parsed.port
    except ValueError as error:
        raise PaginationError("configuration", "page URL contains an invalid port") from error
    if parsed.username is not None or parsed.password is not None:
        raise PaginationError("configuration", "credentials are not allowed in page URLs")
    if parsed.fragment:
        raise PaginationError("pagination", "page URLs must not contain fragments")
    if not parsed.hostname:
        raise PaginationError("configuration", "page URL must contain a host")
    if parsed.scheme == "http":
        if not allow_http or not _is_loopback(parsed.hostname):
            raise PaginationError(
                "configuration",
                "HTTP is allowed only for loopback fixtures with allow_http=True",
            )
    elif parsed.scheme != "https":
        raise PaginationError("configuration", "page URL must use HTTPS")
    if expected_origin is not None and _origin(url) != expected_origin:
        raise PaginationError(
            "pagination",
            "next points outside the initial API origin",
            next_url=redact_url(url),
        )
    _ = parsed_port
    return url


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse RFC 9110 delay-seconds or HTTP-date; return None for an invalid value."""

    if value is None:
        return None
    stripped = value.strip()
    if stripped.isascii() and stripped.isdigit():
        return float(int(stripped))
    try:
        target = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    return max((target - current).total_seconds(), 0.0)


def retry_delay(
    retry_after: str | None,
    *,
    retry_number: int,
    backoff_factor: float,
    max_backoff: float,
    jitter_ratio: float,
    random_fn: Callable[[float, float], float] = random.uniform,
    now: datetime | None = None,
) -> tuple[float, str]:
    """Return a bounded delay and its source without retrying before Retry-After."""

    server_delay = parse_retry_after(retry_after, now=now)
    if server_delay is not None:
        if server_delay > max_backoff:
            raise PaginationError(
                "retry_budget",
                "Retry-After exceeds max_backoff; refusing to retry early",
                retry_after_seconds=server_delay,
                max_backoff=max_backoff,
            )
        return server_delay, "retry-after"

    ceiling = min(backoff_factor * (2 ** (retry_number - 1)), max_backoff)
    floor = ceiling * (1.0 - jitter_ratio)
    return random_fn(floor, ceiling), "backoff"


def _validate_limits(
    *,
    timeout: tuple[float, float],
    max_pages: int,
    max_page_bytes: int,
    max_retries_per_page: int,
    max_total_retries: int,
    backoff_factor: float,
    max_backoff: float,
    jitter_ratio: float,
) -> None:
    if len(timeout) != 2 or any(value <= 0 for value in timeout):
        raise PaginationError("configuration", "connect and read timeouts must be positive")
    if max_pages <= 0 or max_page_bytes <= 0:
        raise PaginationError("configuration", "max_pages and max_page_bytes must be positive")
    if max_retries_per_page < 0 or max_total_retries < 0:
        raise PaginationError("configuration", "retry limits must be non-negative")
    if backoff_factor < 0 or max_backoff < 0:
        raise PaginationError("configuration", "backoff values must be non-negative")
    if not 0.0 <= jitter_ratio <= 1.0:
        raise PaginationError("configuration", "jitter_ratio must be between 0 and 1")


def _media_type(headers: Any) -> tuple[str, str | None]:
    raw = str(headers.get("Content-Type", ""))
    parts = [part.strip() for part in raw.split(";")]
    media_type = parts[0].lower()
    charset = None
    for parameter in parts[1:]:
        name, separator, value = parameter.partition("=")
        if separator and name.strip().lower() == "charset":
            charset = value.strip().strip('"').lower()
    return media_type, charset


def _read_json_page(response: Any, *, url: str, max_page_bytes: int) -> dict[str, Any]:
    media_type, charset = _media_type(response.headers)
    if media_type != "application/json" and not (
        media_type.startswith("application/") and media_type.endswith("+json")
    ):
        raise PaginationError(
            "response_policy",
            "page response is not JSON",
            url=redact_url(url),
            content_type=media_type or "<missing>",
        )
    if charset not in {None, "utf-8", "utf8"}:
        raise PaginationError(
            "response_policy",
            "JSON page declares a non-UTF-8 charset",
            url=redact_url(url),
            charset=charset,
        )

    body = bytearray()
    for chunk in response.iter_content(chunk_size=JSON_CHUNK_SIZE):
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > max_page_bytes:
            raise PaginationError(
                "response_policy",
                "decoded JSON page exceeds max_page_bytes",
                url=redact_url(url),
                max_page_bytes=max_page_bytes,
            )
    try:
        text = bytes(body).decode("utf-8")
    except UnicodeDecodeError as error:
        raise PaginationError(
            "response_policy", "JSON page is not valid UTF-8", url=redact_url(url)
        ) from error
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise PaginationError(
            "response_policy", "page body is not valid JSON", url=redact_url(url)
        ) from error
    if not isinstance(payload, dict):
        raise PaginationError("page_contract", "each page must be a JSON object")
    return payload


def _validate_items(
    items: Any,
    *,
    record_id_field: str,
    seen_ids: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not isinstance(items, list):
        raise PaginationError("page_contract", "items must be a list")
    validated: list[dict[str, Any]] = []
    page_ids: list[str] = []
    local_ids: set[str] = set()
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            raise PaginationError(
                "page_contract", "every item must be an object", item_position=position
            )
        record_id = item.get(record_id_field)
        if not isinstance(record_id, str) or not record_id.strip():
            raise PaginationError(
                "grain",
                f"every item must have a non-empty string {record_id_field}",
                item_position=position,
            )
        if record_id in seen_ids or record_id in local_ids:
            raise PaginationError(
                "grain",
                f"duplicate {record_id_field} across the traversal",
                duplicate_id=record_id,
            )
        local_ids.add(record_id)
        page_ids.append(record_id)
        validated.append(item)
    return validated, page_ids


def _request_page(
    client: Any,
    url: str,
    *,
    timeout: tuple[float, float],
    max_page_bytes: int,
    max_retries_per_page: int,
    max_total_retries: int,
    total_retries: int,
    backoff_factor: float,
    max_backoff: float,
    jitter_ratio: float,
    sleep_fn: Callable[[float], None],
    random_fn: Callable[[float, float], float],
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    retry_events: list[dict[str, Any]] = []
    page_retries = 0
    while True:
        response = None
        retry_after = None
        try:
            response = client.get(
                url,
                timeout=timeout,
                headers={"Accept": "application/json"},
                stream=True,
                allow_redirects=False,
            )
            status = response.status_code
            if status == 200:
                payload = _read_json_page(response, url=url, max_page_bytes=max_page_bytes)
                return payload, retry_events, total_retries
            if status not in RETRYABLE_STATUSES:
                raise PaginationError(
                    "response_policy",
                    f"HTTP {status} is not an accepted page response",
                    url=redact_url(url),
                    status=status,
                )
            failure = f"HTTP {status}"
            retry_after = response.headers.get("Retry-After")
        except requests.RequestException as error:
            failure = f"transport:{type(error).__name__}"
        finally:
            if response is not None:
                response.close()

        if page_retries >= max_retries_per_page or total_retries >= max_total_retries:
            error_kind = "transport" if failure.startswith("transport:") else "retry_budget"
            raise PaginationError(
                error_kind,
                "retry budget exhausted before the page succeeded",
                url=redact_url(url),
                reason=failure,
                page_retries=page_retries,
                total_retries=total_retries,
            )

        page_retries += 1
        total_retries += 1
        try:
            delay, delay_source = retry_delay(
                retry_after,
                retry_number=page_retries,
                backoff_factor=backoff_factor,
                max_backoff=max_backoff,
                jitter_ratio=jitter_ratio,
                random_fn=random_fn,
            )
        except PaginationError as error:
            error.details.setdefault("url", redact_url(url))
            error.details.setdefault("reason", failure)
            error.details.setdefault("page_retries", page_retries)
            error.details.setdefault("total_retries", total_retries)
            raise
        retry_events.append(
            {
                "url": redact_url(url),
                "retry_number": page_retries,
                "total_retry_number": total_retries,
                "reason": failure,
                "delay_seconds": delay,
                "delay_source": delay_source,
            }
        )
        sleep_fn(delay)


def fetch_all(
    start_url: str,
    *,
    session: Any | None = None,
    timeout: tuple[float, float] = (3.05, 30.0),
    max_pages: int = 100,
    max_page_bytes: int = 5_000_000,
    max_retries_per_page: int = 3,
    max_total_retries: int = 10,
    backoff_factor: float = 0.5,
    max_backoff: float = 30.0,
    jitter_ratio: float = 0.2,
    record_id_field: str = "order_id",
    allow_http: bool = False,
    sleep_fn: Callable[[float], None] = time.sleep,
    random_fn: Callable[[float, float], float] = random.uniform,
) -> dict[str, Any]:
    """Load one complete traversal or raise without returning partial records."""

    _validate_limits(
        timeout=timeout,
        max_pages=max_pages,
        max_page_bytes=max_page_bytes,
        max_retries_per_page=max_retries_per_page,
        max_total_retries=max_total_retries,
        backoff_factor=backoff_factor,
        max_backoff=max_backoff,
        jitter_ratio=jitter_ratio,
    )
    if not record_id_field:
        raise PaginationError("configuration", "record_id_field must be non-empty")
    current_url = validate_page_url(start_url, allow_http=allow_http)
    initial_origin = _origin(current_url)

    owns_session = session is None
    client = session or requests.Session()
    if owns_session:
        client.trust_env = False

    visited: set[str] = set()
    seen_ids: set[str] = set()
    records: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    retries: list[dict[str, Any]] = []
    total_retries = 0
    try:
        while True:
            if current_url in visited:
                raise PaginationError(
                    "pagination",
                    "pagination cycle detected before a repeated request",
                    url=redact_url(current_url),
                    completed_pages=len(pages),
                )
            if len(pages) >= max_pages:
                raise PaginationError(
                    "pagination",
                    "max_pages reached before the documented end condition",
                    max_pages=max_pages,
                    buffered_records=len(records),
                )
            visited.add(current_url)
            try:
                payload, page_retries, total_retries = _request_page(
                    client,
                    current_url,
                    timeout=timeout,
                    max_page_bytes=max_page_bytes,
                    max_retries_per_page=max_retries_per_page,
                    max_total_retries=max_total_retries,
                    total_retries=total_retries,
                    backoff_factor=backoff_factor,
                    max_backoff=max_backoff,
                    jitter_ratio=jitter_ratio,
                    sleep_fn=sleep_fn,
                    random_fn=random_fn,
                )
            except PaginationError as error:
                error.details.setdefault("completed_pages", len(pages))
                error.details.setdefault("buffered_records", len(records))
                raise
            retries.extend(page_retries)

            try:
                if "next" not in payload:
                    raise PaginationError("page_contract", "page must contain next, including null")
                page_records, page_ids = _validate_items(
                    payload.get("items"), record_id_field=record_id_field, seen_ids=seen_ids
                )
                next_value = payload["next"]
                if next_value is not None and (
                    not isinstance(next_value, str) or not next_value.strip()
                ):
                    raise PaginationError(
                        "page_contract", "next must be a non-empty string or null"
                    )

                next_url = None
                if next_value is not None:
                    next_url = validate_page_url(
                        urljoin(current_url, next_value),
                        expected_origin=initial_origin,
                        allow_http=allow_http,
                    )
            except PaginationError as error:
                error.details.setdefault("completed_pages", len(pages))
                error.details.setdefault("buffered_records", len(records))
                raise

            seen_ids.update(page_ids)
            records.extend(page_records)
            pages.append(
                {
                    "page_number": len(pages) + 1,
                    "url": redact_url(current_url),
                    "record_count": len(page_records),
                    "next": redact_url(next_url) if next_url is not None else None,
                }
            )
            if next_url is None:
                break
            current_url = next_url
    finally:
        if owns_session:
            client.close()

    return {
        "schema_version": 1,
        "source": {"start_url": redact_url(start_url), "record_id_field": record_id_field},
        "policy": {
            "timeout": list(timeout),
            "max_pages": max_pages,
            "max_page_bytes": max_page_bytes,
            "max_retries_per_page": max_retries_per_page,
            "max_total_retries": max_total_retries,
            "backoff_factor": backoff_factor,
            "max_backoff": max_backoff,
            "jitter_ratio": jitter_ratio,
        },
        "records": records,
        "pages": pages,
        "retries": retries,
        "checks": {
            "terminated_by_next_null": pages[-1]["next"] is None,
            f"{record_id_field}_unique": len(seen_ids) == len(records),
            "same_origin_chain": True,
        },
        "summary": {
            "valid": True,
            "published": False,
            "page_count": len(pages),
            "record_count": len(records),
            "retry_count": len(retries),
        },
    }


def publish_snapshot(result: dict[str, Any], output: str | Path) -> Path:
    """Atomically replace one self-contained snapshot after all checks passed."""

    if not result.get("summary", {}).get("valid"):
        raise PaginationError("configuration", "an invalid result cannot be published")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    published = json.loads(json.dumps(result))
    published["summary"]["published"] = True
    payload = json.dumps(published, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".part", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return target


def download_snapshot(start_url: str, output: str | Path, **kwargs: Any) -> dict[str, Any]:
    result = fetch_all(start_url, **kwargs)
    publish_snapshot(result, output)
    result["summary"]["published"] = True
    return result


def _public_report(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "records"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish one complete paginated JSON snapshot")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--record-id-field", default="order_id")
    parser.add_argument("--connect-timeout", type=float, default=3.05)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--max-page-bytes", type=int, default=5_000_000)
    parser.add_argument("--max-retries-per-page", type=int, default=3)
    parser.add_argument("--max-total-retries", type=int, default=10)
    parser.add_argument("--backoff-factor", type=float, default=0.5)
    parser.add_argument("--max-backoff", type=float, default=30.0)
    parser.add_argument("--jitter-ratio", type=float, default=0.2)
    parser.add_argument("--bearer-token-env")
    parser.add_argument("--allow-http", action="store_true")
    parser.add_argument("--trust-env", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    session = requests.Session()
    session.trust_env = arguments.trust_env
    if arguments.bearer_token_env:
        token = os.environ.get(arguments.bearer_token_env)
        if not token:
            error = PaginationError(
                "configuration",
                f"environment variable {arguments.bearer_token_env} is missing or empty",
            )
            print(json.dumps(error.as_report(), ensure_ascii=False, indent=2))
            session.close()
            return 2
        session.headers["Authorization"] = f"Bearer {token}"

    try:
        result = download_snapshot(
            arguments.url,
            arguments.output,
            session=session,
            timeout=(arguments.connect_timeout, arguments.read_timeout),
            max_pages=arguments.max_pages,
            max_page_bytes=arguments.max_page_bytes,
            max_retries_per_page=arguments.max_retries_per_page,
            max_total_retries=arguments.max_total_retries,
            backoff_factor=arguments.backoff_factor,
            max_backoff=arguments.max_backoff,
            jitter_ratio=arguments.jitter_ratio,
            record_id_field=arguments.record_id_field,
            allow_http=arguments.allow_http,
        )
    except PaginationError as error:
        print(json.dumps(error.as_report(), ensure_ascii=False, indent=2))
        return 2 if error.kind in {"configuration", "transport"} else 1
    except OSError as error:
        report = PaginationError("filesystem", f"cannot publish snapshot: {error}").as_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    finally:
        session.close()

    print(json.dumps(_public_report(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
