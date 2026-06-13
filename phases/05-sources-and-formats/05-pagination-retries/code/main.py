import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "paginated_client.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("paginated_client", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


class Response:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, page: int):
        self.page = page

    def json(self):
        return json.loads((DATA / f"api_page_{self.page}.json").read_text())

    def close(self):
        pass


class Session:
    def get(self, url: str, **kwargs):
        return Response(int(url.rsplit("=", 1)[-1]))


result = CLIENT.fetch_all(
    "https://api.example.test/orders?page=1",
    session=Session(),
    sleep_fn=lambda delay: None,
)
print(result["summary"])
print([record["order_id"] for record in result["records"]])
