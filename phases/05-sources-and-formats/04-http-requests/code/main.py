from __future__ import annotations

import hashlib
import importlib.util
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

ROOT = Path(__file__).resolve().parents[1]
BODY = (ROOT.parent / "data" / "tiny" / "http_orders.json").read_bytes()
ARTIFACT = ROOT / "outputs" / "http_download.py"
SPEC = importlib.util.spec_from_file_location("http_download", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DOWNLOADER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOWNLOADER)


class LabHandler(BaseHTTPRequestHandler):
    """Small local source used only to make the HTTP exchange observable."""

    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:
        if self.path == "/orders.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)
            return
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), LabHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
url = f"http://127.0.0.1:{server.server_port}/orders.json"

try:
    print("Локальный источник:", url)
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(
            url,
            headers={"Accept": "application/json"},
            timeout=(1.0, 2.0),
            stream=True,
            allow_redirects=False,
        )
        try:
            print("Status:", response.status_code)
            print("Content-Type:", response.headers["Content-Type"])
            chunks = list(response.iter_content(chunk_size=32))
        finally:
            response.close()
    observed = b"".join(chunks)
    print("Получено chunks:", [len(chunk) for chunk in chunks])
    print("SHA-256 декодированных bytes:", hashlib.sha256(observed).hexdigest())

    with TemporaryDirectory() as directory:
        output = Path(directory) / "orders.json"
        report = DOWNLOADER.download(
            url,
            output,
            allow_http=True,
            timeout=(1.0, 2.0),
            chunk_size=32,
        )
        print("Quality gate:", report["summary"])
        print("Published:", report["output"])
        print("Точное совпадение с fixture:", output.read_bytes() == BODY)
finally:
    server.shutdown()
    server.server_close()
    thread.join()
