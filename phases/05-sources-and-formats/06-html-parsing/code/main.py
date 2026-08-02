from __future__ import annotations

import importlib.util
from pathlib import Path

from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT.parent / "data" / "tiny" / "orders.html"
CONTRACT = ROOT.parent / "data" / "html_contract.json"
ARTIFACT = ROOT / "outputs" / "html_extractor.py"


def exactly_one(scope: Tag | BeautifulSoup, selector: str, label: str) -> Tag:
    matches = scope.select(selector)
    if len(matches) != 1:
        raise ValueError(f"{label}: expected one match, got {len(matches)}")
    return matches[0]


raw = HTML.read_bytes()
text = raw.decode("utf-8", errors="strict")
soup = BeautifulSoup(text, "html.parser")
container = exactly_one(soup, "[data-orders]", "orders container")

print("Как HTML превращается в две строки:")
for card in container.select("[data-order-card]"):
    user = exactly_one(card, "[data-field='user']", "user_id")
    amount = exactly_one(card, "[data-field='amount']", "amount")
    print(
        {
            "order_id": card.get("data-order-id"),
            "user_id": user.get_text(" ", strip=True),
            "amount": amount.get_text(" ", strip=True),
        }
    )

spec = importlib.util.spec_from_file_location("html_extractor", ARTIFACT)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT.name}")
extractor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extractor)
result = extractor.extract_html(HTML, CONTRACT)
print("\nПроверки самостоятельного артефакта:")
print(result["checks"])
