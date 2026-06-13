from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT.parent / "data" / "tiny" / "orders.html"
soup = BeautifulSoup(HTML.read_text(encoding="utf-8"), "html.parser")

for card in soup.select("[data-order-card]"):
    print(
        {
            "order_id": card["data-order-id"],
            "user_id": card.select_one("[data-field='user']").get_text(strip=True),
            "amount": card.select_one("[data-field='amount']").get_text(strip=True),
        }
    )
