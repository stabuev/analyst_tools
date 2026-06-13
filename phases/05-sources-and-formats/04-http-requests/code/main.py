import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
BODY = (ROOT.parent / "data" / "tiny" / "http_orders.json").read_bytes()
ARTIFACT = ROOT / "outputs" / "http_download.py"
SPEC = importlib.util.spec_from_file_location("http_download", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
DOWNLOADER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOWNLOADER)


class Response:
    status_code = 200
    url = "https://api.example.test/orders"
    history: list[object] = []
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(BODY)),
    }

    def iter_content(self, chunk_size: int):
        for start in range(0, len(BODY), chunk_size):
            yield BODY[start : start + chunk_size]

    def close(self):
        pass


class Session:
    def get(self, url: str, **kwargs):
        print("Request policy:", url, kwargs)
        return Response()


with TemporaryDirectory() as directory:
    report = DOWNLOADER.download(
        "https://api.example.test/orders",
        Path(directory) / "orders.json",
        session=Session(),
        chunk_size=32,
    )
    print("Download:", report["summary"], report["output"])
