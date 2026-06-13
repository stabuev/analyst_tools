from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import requests

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class PaginationError(RuntimeError):
    """Raised when a paginated API cannot be loaded safely."""


def retry_delay(
    retry_after: str | None,
    *,
    attempt: int,
    backoff_factor: float,
    max_backoff: float,
    now: datetime | None = None,
) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), max_backoff)
        except ValueError:
            try:
                target = parsedate_to_datetime(retry_after)
                current = now or datetime.now(UTC)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=UTC)
                return min(max((target - current).total_seconds(), 0.0), max_backoff)
            except (TypeError, ValueError, OverflowError):
                pass
    return min(backoff_factor * (2**attempt), max_backoff)


def fetch_all(
    start_url: str,
    *,
    session: Any | None = None,
    timeout: tuple[float, float] = (3.05, 30.0),
    max_pages: int = 100,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    max_backoff: float = 30.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if max_pages <= 0 or max_retries < 0:
        raise PaginationError("max_pages must be positive and max_retries non-negative")
    owns_session = session is None
    client = session or requests.Session()
    url: str | None = start_url
    visited: set[str] = set()
    records: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    retries: list[dict[str, Any]] = []
    try:
        while url is not None:
            if len(pages) >= max_pages:
                raise PaginationError(f"max_pages={max_pages} reached before next became null")
            if url in visited:
                raise PaginationError(f"pagination cycle detected at {url}")
            visited.add(url)

            response = None
            for attempt in range(max_retries + 1):
                try:
                    response = client.get(
                        url,
                        timeout=timeout,
                        headers={"Accept": "application/json"},
                    )
                except requests.RequestException as error:
                    if attempt >= max_retries:
                        raise PaginationError(f"request failed after retries: {error}") from error
                    delay = retry_delay(
                        None,
                        attempt=attempt,
                        backoff_factor=backoff_factor,
                        max_backoff=max_backoff,
                    )
                    retries.append(
                        {
                            "url": url,
                            "attempt": attempt + 1,
                            "delay": delay,
                            "reason": "network",
                        }
                    )
                    sleep_fn(delay)
                    continue

                if 200 <= response.status_code < 300:
                    break
                retryable = response.status_code in RETRYABLE_STATUSES
                if not retryable or attempt >= max_retries:
                    status = response.status_code
                    response.close()
                    raise PaginationError(f"HTTP {status} is not recoverable for {url}")
                delay = retry_delay(
                    response.headers.get("Retry-After"),
                    attempt=attempt,
                    backoff_factor=backoff_factor,
                    max_backoff=max_backoff,
                )
                retries.append(
                    {
                        "url": url,
                        "attempt": attempt + 1,
                        "delay": delay,
                        "reason": f"HTTP {response.status_code}",
                    }
                )
                response.close()
                response = None
                sleep_fn(delay)

            if response is None:
                raise PaginationError(f"no response received for {url}")
            try:
                media_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if media_type != "application/json":
                    raise PaginationError(f"unexpected content type: {media_type or '<missing>'}")
                payload = response.json()
            except (ValueError, requests.JSONDecodeError) as error:
                raise PaginationError(f"invalid JSON page: {url}") from error
            finally:
                response.close()
            if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                raise PaginationError("each page must be an object with an items list")
            next_url = payload.get("next")
            if next_url is not None and not isinstance(next_url, str):
                raise PaginationError("next must be a string or null")
            records.extend(payload["items"])
            pages.append({"url": url, "items": len(payload["items"]), "next": next_url})
            url = next_url
    finally:
        if owns_session:
            client.close()

    ids = [record.get("order_id") for record in records]
    duplicate_ids = sorted({value for value in ids if value is not None and ids.count(value) > 1})
    return {
        "records": records,
        "pages": pages,
        "retries": retries,
        "checks": {
            "terminated_by_null": bool(pages) and pages[-1]["next"] is None,
            "order_id_unique": not duplicate_ids,
        },
        "summary": {
            "valid": bool(pages) and pages[-1]["next"] is None and not duplicate_ids,
            "page_count": len(pages),
            "record_count": len(records),
            "retry_count": len(retries),
        },
    }


def export_result(result: dict[str, Any], output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "orders.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in result["records"]),
        encoding="utf-8",
    )
    report = {key: value for key, value in result.items() if key != "records"}
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Load all pages from a JSON API")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--backoff-factor", type=float, default=0.5)
    args = parser.parse_args()
    try:
        result = fetch_all(
            args.url,
            max_pages=args.max_pages,
            max_retries=args.max_retries,
            backoff_factor=args.backoff_factor,
        )
        export_result(result, args.output_dir)
    except PaginationError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    json.dump(
        {key: value for key, value in result.items() if key != "records"},
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")
    if not result["summary"]["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
