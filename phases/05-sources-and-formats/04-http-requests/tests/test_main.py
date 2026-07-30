from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "http_download.py"
BODY = (ROOT.parent / "data" / "tiny" / "http_orders.json").read_bytes()
LARGE_BODY = BODY * 8
GZIP_BODY = gzip.compress(BODY)
MODULE_SPEC = importlib.util.spec_from_file_location("http_download", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DOWNLOADER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(DOWNLOADER)


class LocalHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def send_body(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/ok":
            self.send_body(BODY, content_type="application/json; charset=utf-8")
        elif self.path == "/gzip":
            self.send_body(
                GZIP_BODY,
                headers={"Content-Encoding": "gzip"},
            )
        elif self.path == "/wrong-type":
            self.send_body(b"<html>gateway</html>", content_type="text/html")
        elif self.path == "/status-503":
            self.send_body(b"<html>unavailable</html>", status=503, content_type="text/html")
        elif self.path == "/status-204":
            self.send_body(b"", status=204)
        elif self.path == "/invalid-utf8":
            self.send_body(b'{"message": "\xff"}')
        elif self.path == "/wrong-charset":
            self.send_body(BODY, content_type="application/json; charset=iso-8859-1")
        elif self.path == "/large":
            self.send_body(LARGE_BODY)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif self.path == "/redirect-loop":
            self.send_response(302)
            self.send_header("Location", "/redirect-loop")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_body(b"not found", status=404, content_type="text/plain")

    def log_message(self, format: str, *args: object) -> None:
        pass


class FakeResponse:
    def __init__(
        self,
        body: bytes = BODY,
        *,
        status: int = 200,
        url: str = "https://api.example.test/orders",
        headers: dict[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.body = body
        self.status_code = status
        self.url = url
        self.headers = headers or {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body)),
        }
        self.error = error
        self.closed = False
        self.iterated = False

    def iter_content(self, chunk_size: int):
        self.iterated = True
        if self.error is not None:
            raise self.error
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, responses: FakeResponse | list[FakeResponse]) -> None:
        self.responses = list(responses) if isinstance(responses, list) else [responses]
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.closed = False
        self.trust_env = True

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


class HttpDownloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), LocalHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_real_http_download_streams_and_hashes_saved_bytes(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            report = DOWNLOADER.download(
                f"{self.base_url}/ok",
                output,
                allow_http=True,
                chunk_size=17,
            )
            self.assertEqual(output.read_bytes(), BODY)
        self.assertTrue(report["summary"]["valid"])
        self.assertEqual(report["output"]["bytes"], len(BODY))
        self.assertEqual(
            report["output"]["sha256"],
            hashlib.sha256(BODY).hexdigest(),
        )
        self.assertEqual(report["request"]["expected_statuses"], [200])
        self.assertFalse(report["request"]["trust_env"])

    def test_gzip_content_length_is_not_compared_with_decoded_body(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            report = DOWNLOADER.download(
                f"{self.base_url}/gzip",
                output,
                allow_http=True,
            )
            self.assertEqual(output.read_bytes(), BODY)
        self.assertTrue(report["summary"]["valid"])
        self.assertEqual(report["response"]["content_encoding"], "gzip")
        self.assertEqual(
            int(report["response"]["declared_content_length"]),
            len(GZIP_BODY),
        )
        self.assertEqual(report["response"]["decoded_bytes_read"], len(BODY))

    def test_exact_status_policy_rejects_204(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            report = DOWNLOADER.download(
                f"{self.base_url}/status-204",
                output,
                allow_http=True,
            )
            self.assertFalse(output.exists())
        self.assertFalse(report["checks"]["status_expected"])
        self.assertIn("body_encoding_valid", report["summary"]["not_run_checks"])

    def test_content_type_is_checked_before_reading_body(self) -> None:
        response = FakeResponse(
            headers={
                "Content-Type": "text/html",
                "Content-Length": str(len(BODY)),
            }
        )
        with TemporaryDirectory() as directory:
            report = DOWNLOADER.download(
                "https://api.example.test/orders",
                Path(directory) / "orders.json",
                session=FakeSession(response),
            )
        self.assertFalse(report["checks"]["content_type_expected"])
        self.assertFalse(response.iterated)
        self.assertTrue(response.closed)

    def test_status_error_is_checked_before_reading_body(self) -> None:
        response = FakeResponse(status=503)
        with TemporaryDirectory() as directory:
            report = DOWNLOADER.download(
                "https://api.example.test/orders",
                Path(directory) / "orders.json",
                session=FakeSession(response),
            )
        self.assertFalse(report["checks"]["status_expected"])
        self.assertFalse(response.iterated)

    def test_declared_charset_must_match_expected_encoding(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            report = DOWNLOADER.download(
                f"{self.base_url}/wrong-charset",
                output,
                allow_http=True,
            )
            self.assertFalse(output.exists())
        self.assertFalse(report["checks"]["declared_charset_compatible"])
        self.assertEqual(report["response"]["declared_charset"], "iso-8859-1")

    def test_body_must_decode_as_utf8_even_without_charset_parameter(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            report = DOWNLOADER.download(
                f"{self.base_url}/invalid-utf8",
                output,
                allow_http=True,
                chunk_size=3,
            )
            self.assertFalse(output.exists())
        self.assertFalse(report["checks"]["body_encoding_valid"])

    def test_size_limit_is_a_reported_response_failure(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            report = DOWNLOADER.download(
                f"{self.base_url}/large",
                output,
                allow_http=True,
                max_bytes=len(BODY) + 1,
                chunk_size=11,
            )
            self.assertFalse(output.exists())
            self.assertEqual(list(Path(directory).glob("*.part")), [])
        self.assertFalse(report["checks"]["within_size_limit"])
        self.assertFalse(report["summary"]["valid"])

    def test_valid_same_host_redirect_is_followed_manually(self) -> None:
        with TemporaryDirectory() as directory:
            report = DOWNLOADER.download(
                f"{self.base_url}/redirect",
                Path(directory) / "orders.json",
                allow_http=True,
            )
        self.assertTrue(report["summary"]["valid"])
        self.assertEqual(len(report["response"]["redirect_chain"]), 1)
        self.assertTrue(report["checks"]["redirect_policy_valid"])

    def test_redirect_cycle_is_rejected_without_second_request(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            report = DOWNLOADER.download(
                f"{self.base_url}/redirect-loop",
                output,
                allow_http=True,
            )
            self.assertFalse(output.exists())
        self.assertFalse(report["checks"]["redirect_policy_valid"])
        self.assertEqual(len(report["response"]["redirect_chain"]), 1)

    def test_https_to_http_redirect_is_rejected_before_following(self) -> None:
        response = FakeResponse(
            status=302,
            headers={
                "Location": "http://api.example.test/orders",
                "Content-Length": "0",
            },
        )
        session = FakeSession(response)
        with TemporaryDirectory() as directory:
            report = DOWNLOADER.download(
                "https://api.example.test/orders",
                Path(directory) / "orders.json",
                session=session,
            )
        self.assertFalse(report["checks"]["redirect_policy_valid"])
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(response.closed)

    def test_cross_host_redirect_needs_an_explicit_allowlist(self) -> None:
        response = FakeResponse(
            status=302,
            headers={
                "Location": "https://cdn.example.test/orders",
                "Content-Length": "0",
            },
        )
        with TemporaryDirectory() as directory:
            report = DOWNLOADER.download(
                "https://api.example.test/orders",
                Path(directory) / "orders.json",
                session=FakeSession(response),
            )
        self.assertFalse(report["checks"]["redirect_policy_valid"])
        self.assertEqual(
            report["response"]["rejected_redirect_target"],
            "https://cdn.example.test/orders",
        )

    def test_allowed_cross_host_redirect_strips_sensitive_headers(self) -> None:
        redirect = FakeResponse(
            status=302,
            headers={
                "Location": "https://cdn.example.test/orders",
                "Content-Length": "0",
            },
        )
        final = FakeResponse(url="https://cdn.example.test/orders")
        session = FakeSession([redirect, final])
        with TemporaryDirectory() as directory:
            report = DOWNLOADER.download(
                "https://api.example.test/orders",
                Path(directory) / "orders.json",
                allowed_redirect_hosts=("cdn.example.test",),
                session=session,
            )
        self.assertTrue(report["summary"]["valid"])
        _, second_request = session.calls[1]
        self.assertIsNone(second_request["headers"]["Authorization"])
        self.assertIsNone(second_request["headers"]["Proxy-Authorization"])

    def test_public_http_is_rejected_even_with_allow_http(self) -> None:
        with (
            TemporaryDirectory() as directory,
            self.assertRaisesRegex(
                DOWNLOADER.HttpDownloadError,
                "restricted to loopback",
            ),
        ):
            DOWNLOADER.download(
                "http://api.example.test/orders",
                Path(directory) / "orders.json",
                allow_http=True,
                session=FakeSession(FakeResponse()),
            )

    def test_credentials_in_url_are_rejected(self) -> None:
        with (
            TemporaryDirectory() as directory,
            self.assertRaisesRegex(
                DOWNLOADER.HttpDownloadError,
                "credentials are forbidden",
            ),
        ):
            DOWNLOADER.download(
                "https://token@example.test/orders",
                Path(directory) / "orders.json",
                session=FakeSession(FakeResponse()),
            )

    def test_existing_valid_output_is_preserved_on_response_failure(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            output.write_bytes(b"previous-valid")
            report = DOWNLOADER.download(
                f"{self.base_url}/wrong-type",
                output,
                allow_http=True,
            )
            self.assertEqual(output.read_bytes(), b"previous-valid")
        self.assertTrue(report["output"]["previous_file_existed"])
        self.assertFalse(report["output"]["written"])

    def test_success_atomically_replaces_an_existing_file(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            output.write_bytes(b"previous-valid")
            report = DOWNLOADER.download(
                f"{self.base_url}/ok",
                output,
                allow_http=True,
            )
            self.assertEqual(output.read_bytes(), BODY)
        self.assertTrue(report["output"]["replaced_previous_file"])

    def test_output_directory_is_a_controlled_configuration_error(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            output.mkdir()
            with self.assertRaisesRegex(
                DOWNLOADER.HttpDownloadError,
                "not a regular file",
            ):
                DOWNLOADER.download(
                    "https://api.example.test/orders",
                    output,
                    session=FakeSession(FakeResponse()),
                )
            self.assertEqual(list(Path(directory).glob("*.part")), [])

    def test_read_timeout_is_a_controlled_transport_error(self) -> None:
        response = FakeResponse(error=requests.ReadTimeout("read stalled"))
        with (
            TemporaryDirectory() as directory,
            self.assertRaisesRegex(DOWNLOADER.HttpDownloadError, "request failed"),
        ):
            DOWNLOADER.download(
                "https://api.example.test/orders",
                Path(directory) / "orders.json",
                session=FakeSession(response),
            )
        self.assertTrue(response.closed)

    def test_request_policy_uses_stream_timeout_and_manual_redirects(self) -> None:
        response = FakeResponse()
        session = FakeSession(response)
        with TemporaryDirectory() as directory:
            DOWNLOADER.download(
                "https://api.example.test/orders",
                Path(directory) / "orders.json",
                session=session,
            )
        _, kwargs = session.calls[0]
        self.assertEqual(kwargs["timeout"], (3.05, 30.0))
        self.assertTrue(kwargs["stream"])
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["headers"]["Accept"], "application/json")

    def test_owned_session_ignores_environment_by_default_and_closes(self) -> None:
        session = FakeSession(FakeResponse())
        with (
            TemporaryDirectory() as directory,
            patch.object(DOWNLOADER.requests, "Session", return_value=session),
        ):
            DOWNLOADER.download(
                "https://api.example.test/orders",
                Path(directory) / "orders.json",
            )
        self.assertFalse(session.trust_env)
        self.assertTrue(session.closed)

    def test_cli_works_against_the_real_local_server(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--url",
                    f"{self.base_url}/ok",
                    "--output",
                    output,
                    "--allow-http",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["summary"]["valid"])
            self.assertEqual(output.read_bytes(), BODY)

    def test_cli_returns_one_for_response_policy_failure(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--url",
                    f"{self.base_url}/status-503",
                    "--output",
                    output,
                    "--allow-http",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(json.loads(result.stdout)["summary"]["valid"])

    def test_cli_allow_failures_never_publishes_invalid_body(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--url",
                    f"{self.base_url}/invalid-utf8",
                    "--output",
                    output,
                    "--allow-http",
                    "--allow-failures",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(output.exists())
            self.assertFalse(json.loads(result.stdout)["output"]["written"])

    def test_cli_returns_two_for_configuration_error_without_traceback(self) -> None:
        with TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    ARTIFACT,
                    "--url",
                    "http://public.example.test/orders",
                    "--output",
                    Path(directory) / "orders.json",
                    "--allow-http",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("loopback", json.loads(result.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
