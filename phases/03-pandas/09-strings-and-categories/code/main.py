from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "text_categories.py"
DATA = ROOT.parent / "data" / "tiny"


def load_artifact():
    spec = importlib.util.spec_from_file_location("text_categories", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    text = load_artifact()
    users = text.normalize_users(pd.read_csv(DATA / "users.csv"))
    items = text.normalize_items(pd.read_csv(DATA / "order_items.csv"))
    print(text.category_report(users["plan"]))
    print(text.category_report(items["category"]))


if __name__ == "__main__":
    main()
