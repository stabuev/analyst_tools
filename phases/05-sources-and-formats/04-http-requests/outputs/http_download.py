from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


class HttpDownloadError(RuntimeError):
    """Raised when a request cannot be completed or safely stored."""


def media_type(headers: Any) -> str:
    value = headers.get("Content-Type", "")
    return value.split(";", 1)[0].strip().lower()


def charset(headers: Any) -> str | None:
    value = headers.get("Content-Type", "")
    for part in value.split(";")[1:]:
        name, separator, raw_value = part.strip().partition("=")
        if separator and name.lower() == "charset":
            return raw_value.strip().strip('"').lower()
    return None


def download(
    url: str,
    output_path: str | Path,
    *,
    expected_content_types: tuple[str, ...] = ("application/json",),
    timeout: tuple[float, float] = (3.05, 30.0),
    max_bytes: int = 10_000_000,
    chunk_size: int = 64 * 1024,
    allow_http: bool = False,
    session: Any | None = None,
) -> dict[str, Any]:
    scheme = urlparse(url).scheme.lower()
    if scheme not in ({"https", "http"} if allow_http else {"https"}):
        raise HttpDownloadError("URL must use HTTPS; use allow_http only for local tests")
    if any(value <= 0 for value in timeout):
        raise HttpDownloadError("connect and read timeout must be positive")
    if max_bytes <= 0 or chunk_size <= 0:
        raise HttpDownloadError("max_bytes and chunk_size must be positive")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.part")
    owns_session = session is None
    client = session or requests.Session()
    response = None
    try:
        response = client.get(
            url,
            stream=True,
            timeout=timeout,
            allow_redirects=True,
            headers={"Accept": ", ".join(expected_content_types)},
        )
        status_valid = 200 <= response.status_code < 300
        actual_type = media_type(response.headers)
        content_type_valid = actual_type in {value.lower() for value in expected_content_types}
        checks = {
            "status_2xx": status_valid,
            "content_type_expected": content_type_valid,
            "content_length_matches": True,
            "within_size_limit": True,
        }
        report: dict[str, Any] = {
            "request": {
                "url": url,
                "timeout": list(timeout),
                "stream": True,
                "allow_redirects": True,
            },
            "response": {
                "final_url": getattr(response, "url", url),
                "status_code": response.status_code,
                "content_type": actual_type,
                "declared_charset": charset(response.headers),
                "content_length": response.headers.get("Content-Length"),
                "redirects": len(getattr(response, "history", [])),
            },
            "output": {"path": str(output), "bytes": 0, "sha256": None, "written": False},
            "checks": checks,
            "summary": {"valid": False, "failed_checks": 0},
        }
        if not status_valid or not content_type_valid:
            checks["content_length_matches"] = False
            report["summary"]["failed_checks"] = sum(not value for value in checks.values())
            return report

        digest = hashlib.sha256()
        written = 0
        try:
            with temporary.open("wb") as target:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > max_bytes:
                        checks["within_size_limit"] = False
                        raise HttpDownloadError(
                            f"response exceeded max_bytes={max_bytes} after {written} bytes"
                        )
                    target.write(chunk)
                    digest.update(chunk)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        declared_length = response.headers.get("Content-Length")
        if declared_length is not None:
            try:
                checks["content_length_matches"] = int(declared_length) == written
            except ValueError:
                checks["content_length_matches"] = False
        if not all(checks.values()):
            temporary.unlink(missing_ok=True)
        else:
            os.replace(temporary, output)
            report["output"].update(
                {
                    "bytes": written,
                    "sha256": digest.hexdigest(),
                    "written": True,
                }
            )
        report["summary"] = {
            "valid": all(checks.values()),
            "failed_checks": sum(not value for value in checks.values()),
        }
        return report
    except requests.RequestException as error:
        temporary.unlink(missing_ok=True)
        raise HttpDownloadError(f"request failed: {error}") from error
    finally:
        if response is not None:
            response.close()
        if owns_session:
            client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely stream an HTTP response to disk")
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--content-type", action="append", dest="content_types")
    parser.add_argument("--connect-timeout", type=float, default=3.05)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    parser.add_argument("--max-bytes", type=int, default=10_000_000)
    parser.add_argument("--allow-http", action="store_true")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()
    try:
        report = download(
            args.url,
            args.output,
            expected_content_types=tuple(args.content_types or ["application/json"]),
            timeout=(args.connect_timeout, args.read_timeout),
            max_bytes=args.max_bytes,
            allow_http=args.allow_http,
        )
    except HttpDownloadError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(2) from error
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if not report["summary"]["valid"] and not args.allow_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
