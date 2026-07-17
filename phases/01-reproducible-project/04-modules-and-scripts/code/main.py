from __future__ import annotations

import sys
from pathlib import Path


PROJECT = (
    Path(__file__).resolve().parents[1] / "outputs" / "order_metrics_project"
)
sys.path.insert(0, str(PROJECT / "src"))

from order_metrics import load_orders, summarize_orders  # noqa: E402


def main() -> None:
    summary = summarize_orders(load_orders(PROJECT / "data" / "orders.csv"))
    print(summary)


if __name__ == "__main__":
    main()
