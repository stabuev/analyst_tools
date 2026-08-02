from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "paginated_client.py"
DATA = ROOT.parent / "data" / "tiny"
SPEC = importlib.util.spec_from_file_location("paginated_client", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)

URLS = [f"https://api.example.test/orders?page={number}" for number in (1, 2, 3)]
PAGES = {
    url: json.loads((DATA / f"api_page_{number}.json").read_text(encoding="utf-8"))
    for number, url in enumerate(URLS, start=1)
}


def transparent_walk(start_url: str, pages: dict[str, dict[str, Any]]) -> list[str]:
    """Small mechanism: follow next, prove termination, preserve one order_id grain."""

    url: str | None = start_url
    visited: set[str] = set()
    order_ids: list[str] = []
    while url is not None:
        if url in visited:
            raise RuntimeError(f"cycle at {url}")
        visited.add(url)
        payload = pages[url]
        if "next" not in payload:
            raise RuntimeError("next is missing: completion is not proven")
        for item in payload["items"]:
            if item["order_id"] in order_ids:
                raise RuntimeError(f"duplicate order_id: {item['order_id']}")
            order_ids.append(item["order_id"])
        print(
            {
                "page": len(visited),
                "items": len(payload["items"]),
                "next": payload["next"],
            }
        )
        url = payload["next"]
    return order_ids


class Response:
    status_code = 200
    headers = {"Content-Type": "application/json; charset=utf-8"}

    def __init__(self, payload: dict[str, Any]) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        pass


class Session:
    def get(self, url: str, **kwargs: Any) -> Response:
        return Response(PAGES[url])


print("Прозрачный обход:")
manual_ids = transparent_walk(URLS[0], PAGES)
print({"terminated": True, "order_ids": manual_ids})

print("\nТот же контракт в самостоятельном клиенте:")
result = CLIENT.fetch_all(
    URLS[0],
    session=Session(),
    sleep_fn=lambda delay: None,
    random_fn=lambda low, high: high,
)
print(result["summary"])
print(result["checks"])
print([record["order_id"] for record in result["records"]])
