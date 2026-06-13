from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "aggregate_model.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("aggregate_model", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manual_paid_revenue(path: Path) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    with path.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if row["status"].strip().lower() == "paid" and row["amount"]:
                totals[row["currency"].strip().upper()] += float(row["amount"])
    return dict(sorted(totals.items()))


def main() -> None:
    report = load_artifact().build_aggregates(DATA)
    print(
        json.dumps(
            {"manual_paid_revenue": manual_paid_revenue(DATA), "duckdb": report},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
