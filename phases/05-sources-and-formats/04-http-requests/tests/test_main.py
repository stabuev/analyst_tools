from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "http_download.py"
BODY = (ROOT.parent / "data" / "tiny" / "http_orders.json").read_bytes()
MODULE_SPEC = importlib.util.spec_from_file_location("http_download", ARTIFACT)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DOWNLOADER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(DOWNLOADER)


class FakeResponse:
    def __init__(
        self,
        body: bytes = BODY,
        *,
        status: int = 200,
        content_type: str = "application/json; charset=utf-8",
        content_length: str | None = None,
    ) -> None:
        self.body = body
        self.status_code = status
        self.url = "https://api.example.test/orders"
        self.history: list[object] = []
        self.headers = {"Content-Type": content_type}
        self.headers["Content-Length"] = content_length or str(len(body))
        self.closed = False

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.kwargs = None

    def get(self, url: str, **kwargs):
        self.kwargs = kwargs
        return self.response

    def close(self) -> None:
        pass


class HttpDownloadTest(unittest.TestCase):
    def test_streams_with_timeout_and_sha256(self) -> None:
        response = FakeResponse()
        session = FakeSession(response)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            report = DOWNLOADER.download(
                "https://api.example.test/orders",
                output,
                session=session,
                chunk_size=17,
            )
            self.assertEqual(output.read_bytes(), BODY)
        self.assertEqual(session.kwargs["timeout"], (3.05, 30.0))
        self.assertTrue(session.kwargs["stream"])
        self.assertEqual(report["output"]["sha256"], hashlib.sha256(BODY).hexdigest())
        self.assertTrue(response.closed)

    def test_content_type_is_checked_before_writing(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            report = DOWNLOADER.download(
                "https://api.example.test/orders",
                output,
                session=FakeSession(FakeResponse(content_type="text/html")),
            )
            self.assertFalse(report["summary"]["valid"])
            self.assertFalse(output.exists())

    def test_non_2xx_status_is_not_saved(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "error.json"
            report = DOWNLOADER.download(
                "https://api.example.test/orders",
                output,
                session=FakeSession(FakeResponse(status=503)),
            )
            self.assertFalse(report["checks"]["status_2xx"])
            self.assertFalse(output.exists())

    def test_size_limit_removes_partial_file(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            with self.assertRaises(DOWNLOADER.HttpDownloadError):
                DOWNLOADER.download(
                    "https://api.example.test/orders",
                    output,
                    session=FakeSession(FakeResponse()),
                    max_bytes=20,
                    chunk_size=10,
                )
            self.assertFalse(output.exists())
            self.assertFalse((output.parent / ".orders.json.part").exists())

    def test_content_length_mismatch_fails_atomically(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            report = DOWNLOADER.download(
                "https://api.example.test/orders",
                output,
                session=FakeSession(FakeResponse(content_length="999")),
            )
            self.assertFalse(report["checks"]["content_length_matches"])
            self.assertFalse(output.exists())

    def test_http_requires_explicit_opt_in(self) -> None:
        with (
            TemporaryDirectory() as directory,
            self.assertRaises(DOWNLOADER.HttpDownloadError),
        ):
            DOWNLOADER.download(
                "http://api.example.test/orders",
                Path(directory) / "orders.json",
                session=FakeSession(FakeResponse()),
            )

    def test_declared_charset_is_reported(self) -> None:
        with TemporaryDirectory() as directory:
            report = DOWNLOADER.download(
                "https://api.example.test/orders",
                Path(directory) / "orders.json",
                session=FakeSession(FakeResponse()),
            )
        self.assertEqual(report["response"]["declared_charset"], "utf-8")

    def test_cli_uses_the_same_checked_download_path(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "orders.json"
            stdout = io.StringIO()
            argv = [
                "http_download.py",
                "--url",
                "https://api.example.test/orders",
                "--output",
                str(output),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(
                    DOWNLOADER.requests,
                    "Session",
                    return_value=FakeSession(FakeResponse()),
                ),
                redirect_stdout(stdout),
            ):
                DOWNLOADER.main()
            self.assertTrue(json.loads(stdout.getvalue())["summary"]["valid"])
            self.assertEqual(output.read_bytes(), BODY)


if __name__ == "__main__":
    unittest.main()
