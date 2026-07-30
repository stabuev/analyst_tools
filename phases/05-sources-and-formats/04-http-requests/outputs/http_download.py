from __future__ import annotations

import argparse
import codecs
import hashlib
import ipaddress
import json
import os
import sys
import tempfile
from contextlib import suppress
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
SENSITIVE_REDIRECT_HEADERS = {"Authorization": None, "Proxy-Authorization": None}


class HttpDownloadError(RuntimeError):
    """Raised when request configuration, transport, or filesystem handling fails."""


def parse_content_type(headers: Any) -> tuple[str, str | None]:
    raw_value = headers.get("Content-Type", "")
    if not raw_value:
        return "", None
    message = Message()
    message["content-type"] = raw_value
    media_type = message.get_content_type().strip().lower()
    raw_charset = message.get_param("charset")
    declared_charset = raw_charset.strip().lower() if isinstance(raw_charset, str) else None
    return media_type, declared_charset


def canonical_encoding(value: str) -> str:
    try:
        return codecs.lookup(value).name
    except LookupError as error:
        raise HttpDownloadError(f"unknown text encoding: {value}") from error


def is_loopback_host(hostname: str | None) -> bool:
    if hostname is None:
        return False
    normalized = hostname.rstrip(".").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_input_url(url: str, *, allow_http: bool) -> tuple[str, str]:
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname
    if not hostname:
        raise HttpDownloadError("URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise HttpDownloadError(
            "credentials are forbidden in URLs; configure authentication outside the URL"
        )
    if scheme == "https":
        return scheme, hostname.lower()
    if scheme == "http" and allow_http and is_loopback_host(hostname):
        return scheme, hostname.lower()
    if scheme == "http" and allow_http:
        raise HttpDownloadError("--allow-http is restricted to loopback hosts")
    raise HttpDownloadError("URL must use HTTPS; HTTP is allowed only for loopback tests")


def url_allowed(
    url: str,
    *,
    allowed_hosts: set[str],
    allow_http: bool,
) -> bool:
    parsed = urlparse(url)
    hostname = parsed.hostname
    if (
        hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or hostname.lower() not in allowed_hosts
    ):
        return False
    if parsed.scheme.lower() == "https":
        return True
    return parsed.scheme.lower() == "http" and allow_http and is_loopback_host(hostname)


def validate_policy(
    *,
    expected_content_types: tuple[str, ...],
    expected_statuses: tuple[int, ...],
    expected_encoding: str | None,
    timeout: tuple[float, float],
    max_bytes: int,
    chunk_size: int,
    max_redirects: int,
    allowed_redirect_hosts: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[int, ...], str | None, tuple[str, ...]]:
    if not expected_content_types:
        raise HttpDownloadError("at least one expected content type is required")
    normalized_types = tuple(value.strip().lower() for value in expected_content_types)
    if any(
        not value
        or "/" not in value
        or ";" in value
        or any(character.isspace() for character in value)
        for value in normalized_types
    ):
        raise HttpDownloadError(
            "expected content types must be bare media types such as application/json"
        )
    if (
        not expected_statuses
        or len(expected_statuses) != len(set(expected_statuses))
        or any(
            isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599
            for value in expected_statuses
        )
    ):
        raise HttpDownloadError("expected statuses must be unique HTTP status integers")
    if (
        not isinstance(timeout, tuple)
        or len(timeout) != 2
        or any(
            isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0
            for value in timeout
        )
    ):
        raise HttpDownloadError("connect and read timeout must be positive")
    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes <= 0
        or isinstance(chunk_size, bool)
        or not isinstance(chunk_size, int)
        or chunk_size <= 0
    ):
        raise HttpDownloadError("max_bytes and chunk_size must be positive integers")
    if isinstance(max_redirects, bool) or not isinstance(max_redirects, int) or max_redirects < 0:
        raise HttpDownloadError("max_redirects must be a non-negative integer")
    normalized_hosts = tuple(value.rstrip(".").lower() for value in allowed_redirect_hosts)
    if any(
        not value or "://" in value or "/" in value or ":" in value for value in normalized_hosts
    ):
        raise HttpDownloadError(
            "allowed redirect hosts must be hostnames without scheme, port, or path"
        )
    canonical = canonical_encoding(expected_encoding) if expected_encoding is not None else None
    return normalized_types, expected_statuses, canonical, normalized_hosts


def parsed_content_length(headers: Any) -> int | None:
    raw_value = headers.get("Content-Length")
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    failed = [name for name, value in report["checks"].items() if value is False]
    not_run = [name for name, value in report["checks"].items() if value is None]
    report["summary"] = {
        "valid": not failed and not not_run,
        "failed_checks": failed,
        "failed_check_count": len(failed),
        "not_run_checks": not_run,
    }
    return report


def response_report(
    *,
    url: str,
    output: Path,
    previous_output_existed: bool,
    response: Any,
    expected_content_types: tuple[str, ...],
    expected_statuses: tuple[int, ...],
    expected_encoding: str | None,
    timeout: tuple[float, float],
    max_bytes: int,
    max_redirects: int,
    allowed_hosts: set[str],
    allow_http: bool,
    trust_env: bool,
    redirect_chain: list[dict[str, Any]],
    redirect_policy_valid: bool,
    rejected_redirect_target: str | None = None,
) -> dict[str, Any]:
    media_type, declared_charset = parse_content_type(response.headers)
    declared_canonical: str | None = None
    declared_charset_compatible = True
    if declared_charset is not None:
        try:
            declared_canonical = canonical_encoding(declared_charset)
        except HttpDownloadError:
            declared_charset_compatible = False
        else:
            if expected_encoding is not None:
                declared_charset_compatible = declared_canonical == expected_encoding
    final_url = getattr(response, "url", url) or url
    redirect_policy_valid = redirect_policy_valid and url_allowed(
        final_url,
        allowed_hosts=allowed_hosts,
        allow_http=allow_http,
    )
    checks: dict[str, bool | None] = {
        "redirect_policy_valid": redirect_policy_valid,
        "status_expected": response.status_code in expected_statuses,
        "content_type_expected": media_type in expected_content_types,
        "declared_charset_compatible": declared_charset_compatible,
        "body_encoding_valid": None,
        "within_size_limit": None,
    }
    return {
        "request": {
            "url": url,
            "method": "GET",
            "expected_statuses": list(expected_statuses),
            "expected_content_types": list(expected_content_types),
            "expected_encoding": expected_encoding,
            "timeout": list(timeout),
            "stream": True,
            "max_bytes": max_bytes,
            "max_redirects": max_redirects,
            "allowed_hosts": sorted(allowed_hosts),
            "trust_env": trust_env,
        },
        "response": {
            "final_url": final_url,
            "status_code": response.status_code,
            "content_type": media_type,
            "declared_charset": declared_charset,
            "canonical_charset": declared_canonical,
            "content_encoding": (
                response.headers.get("Content-Encoding", "").strip().lower() or None
            ),
            "declared_content_length": response.headers.get("Content-Length"),
            "redirect_chain": redirect_chain,
            "rejected_redirect_target": rejected_redirect_target,
            "decoded_bytes_read": 0,
        },
        "output": {
            "path": str(output),
            "previous_file_existed": previous_output_existed,
            "written": False,
            "replaced_previous_file": False,
            "bytes": 0,
            "sha256": None,
        },
        "checks": checks,
        "summary": {
            "valid": False,
            "failed_checks": [],
            "failed_check_count": 0,
            "not_run_checks": [],
        },
    }


def download(
    url: str,
    output_path: str | Path,
    *,
    expected_content_types: tuple[str, ...] = ("application/json",),
    expected_statuses: tuple[int, ...] = (200,),
    expected_encoding: str | None = "utf-8",
    timeout: tuple[float, float] = (3.05, 30.0),
    max_bytes: int = 10_000_000,
    chunk_size: int = 64 * 1024,
    max_redirects: int = 5,
    allowed_redirect_hosts: tuple[str, ...] = (),
    allow_http: bool = False,
    trust_env: bool = False,
    session: Any | None = None,
) -> dict[str, Any]:
    _, original_host = validate_input_url(url, allow_http=allow_http)
    (
        normalized_types,
        normalized_statuses,
        canonical_expected_encoding,
        normalized_redirect_hosts,
    ) = validate_policy(
        expected_content_types=expected_content_types,
        expected_statuses=expected_statuses,
        expected_encoding=expected_encoding,
        timeout=timeout,
        max_bytes=max_bytes,
        chunk_size=chunk_size,
        max_redirects=max_redirects,
        allowed_redirect_hosts=allowed_redirect_hosts,
    )
    allowed_hosts = {original_host, *normalized_redirect_hosts}

    output = Path(output_path)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise HttpDownloadError(
            f"cannot create output directory {output.parent}: {error}"
        ) from error
    if output.exists() and not output.is_file():
        raise HttpDownloadError(f"output path is not a regular file: {output}")
    previous_output_existed = output.is_file()

    owns_session = session is None
    client = session or requests.Session()
    if owns_session:
        client.trust_env = trust_env
    actual_trust_env = bool(getattr(client, "trust_env", trust_env))
    response = None
    temporary_path: Path | None = None
    current_url = url
    previous_host = original_host
    visited = {url}
    redirect_chain: list[dict[str, Any]] = []
    report: dict[str, Any] | None = None
    try:
        while True:
            request_headers: dict[str, str | None] = {"Accept": ", ".join(normalized_types)}
            current_host = urlparse(current_url).hostname
            if current_host is not None and current_host.lower() != previous_host.lower():
                request_headers.update(SENSITIVE_REDIRECT_HEADERS)
            response = client.get(
                current_url,
                stream=True,
                timeout=timeout,
                allow_redirects=False,
                headers=request_headers,
            )
            if response.status_code not in REDIRECT_STATUSES:
                break
            location = response.headers.get("Location")
            if not location:
                break
            target = urljoin(current_url, location)
            redirect_event = {
                "from": current_url,
                "status_code": response.status_code,
                "to": target,
            }
            redirect_chain.append(redirect_event)
            redirect_allowed = (
                len(redirect_chain) <= max_redirects
                and target not in visited
                and url_allowed(
                    target,
                    allowed_hosts=allowed_hosts,
                    allow_http=allow_http,
                )
            )
            if not redirect_allowed:
                report = response_report(
                    url=url,
                    output=output,
                    previous_output_existed=previous_output_existed,
                    response=response,
                    expected_content_types=normalized_types,
                    expected_statuses=normalized_statuses,
                    expected_encoding=canonical_expected_encoding,
                    timeout=timeout,
                    max_bytes=max_bytes,
                    max_redirects=max_redirects,
                    allowed_hosts=allowed_hosts,
                    allow_http=allow_http,
                    trust_env=actual_trust_env,
                    redirect_chain=redirect_chain,
                    redirect_policy_valid=False,
                    rejected_redirect_target=target,
                )
                return finalize_report(report)
            response.close()
            response = None
            visited.add(target)
            previous_host = current_host or previous_host
            current_url = target

        report = response_report(
            url=url,
            output=output,
            previous_output_existed=previous_output_existed,
            response=response,
            expected_content_types=normalized_types,
            expected_statuses=normalized_statuses,
            expected_encoding=canonical_expected_encoding,
            timeout=timeout,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
            allowed_hosts=allowed_hosts,
            allow_http=allow_http,
            trust_env=actual_trust_env,
            redirect_chain=redirect_chain,
            redirect_policy_valid=True,
        )
        preflight_checks = {
            name: value
            for name, value in report["checks"].items()
            if name not in {"body_encoding_valid", "within_size_limit"}
        }
        if any(value is False for value in preflight_checks.values()):
            return finalize_report(report)

        content_encoding = report["response"]["content_encoding"]
        declared_length = parsed_content_length(response.headers)
        if (
            content_encoding in {None, "identity"}
            and declared_length is not None
            and declared_length > max_bytes
        ):
            report["checks"]["within_size_limit"] = False
            return finalize_report(report)

        decoder = (
            codecs.getincrementaldecoder(canonical_expected_encoding)(errors="strict")
            if canonical_expected_encoding is not None
            else None
        )
        digest = hashlib.sha256()
        decoded_bytes_read = 0
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=output.parent,
                prefix=f".{output.name}.",
                suffix=".part",
                delete=False,
            ) as target:
                temporary_path = Path(target.name)
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    decoded_bytes_read += len(chunk)
                    report["response"]["decoded_bytes_read"] = decoded_bytes_read
                    if decoded_bytes_read > max_bytes:
                        report["checks"]["within_size_limit"] = False
                        break
                    if decoder is not None:
                        try:
                            decoder.decode(chunk, final=False)
                        except UnicodeDecodeError:
                            report["checks"]["body_encoding_valid"] = False
                            break
                    target.write(chunk)
                    digest.update(chunk)
                else:
                    report["checks"]["within_size_limit"] = True
                    if decoder is not None:
                        try:
                            decoder.decode(b"", final=True)
                        except UnicodeDecodeError:
                            report["checks"]["body_encoding_valid"] = False
                        else:
                            report["checks"]["body_encoding_valid"] = True
                    else:
                        report["checks"]["body_encoding_valid"] = True
        except requests.RequestException:
            raise
        except OSError as error:
            raise HttpDownloadError(
                f"cannot write temporary output beside {output}: {error}"
            ) from error

        if not all(value is True for value in report["checks"].values()):
            return finalize_report(report)

        try:
            os.replace(temporary_path, output)
        except OSError as error:
            raise HttpDownloadError(f"cannot atomically publish {output}: {error}") from error
        temporary_path = None
        report["output"].update(
            {
                "written": True,
                "replaced_previous_file": previous_output_existed,
                "bytes": decoded_bytes_read,
                "sha256": digest.hexdigest(),
            }
        )
        return finalize_report(report)
    except requests.RequestException as error:
        raise HttpDownloadError(f"request failed: {error}") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
        if response is not None:
            response.close()
        if owns_session:
            client.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and atomically store one HTTP GET representation"
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--content-type", action="append", dest="content_types")
    parser.add_argument("--status", action="append", dest="statuses", type=int)
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--connect-timeout", type=float, default=3.05)
    parser.add_argument("--read-timeout", type=float, default=30.0)
    parser.add_argument("--max-bytes", type=int, default=10_000_000)
    parser.add_argument("--max-redirects", type=int, default=5)
    parser.add_argument(
        "--allow-redirect-host",
        action="append",
        dest="allowed_redirect_hosts",
    )
    parser.add_argument(
        "--allow-http",
        action="store_true",
        help="allow HTTP only for localhost and loopback addresses",
    )
    parser.add_argument(
        "--trust-env",
        action="store_true",
        help="allow Requests to use proxy, netrc, and CA settings from the environment",
    )
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()
    try:
        report = download(
            args.url,
            args.output,
            expected_content_types=tuple(args.content_types or ["application/json"]),
            expected_statuses=tuple(args.statuses or [200]),
            expected_encoding=args.encoding,
            timeout=(args.connect_timeout, args.read_timeout),
            max_bytes=args.max_bytes,
            max_redirects=args.max_redirects,
            allowed_redirect_hosts=tuple(args.allowed_redirect_hosts or []),
            allow_http=args.allow_http,
            trust_env=args.trust_env,
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
