from __future__ import annotations

import importlib.util
from pathlib import Path
from pprint import pprint

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
    items = pd.read_csv(DATA / "order_items.csv")

    print("До нормализации:")
    print(items["category"].value_counts(dropna=False).to_string())

    contracted = text.categorize_text(
        items["category"],
        categories=["add_on", "subscription", "service"],
        aliases={"addon": "add_on"},
        unknown="other",
    )
    normalized_items = items.assign(category=contracted.values)

    print("\nПосле нормализации:")
    print(normalized_items["category"].value_counts(dropna=False).to_string())
    print("\nАудит преобразования:")
    pprint(contracted.audit, sort_dicts=False)


if __name__ == "__main__":
    main()
