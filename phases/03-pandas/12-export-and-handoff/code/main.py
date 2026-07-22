from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "mart_builder.py"
DATA = ROOT.parent / "data" / "tiny"


def load_artifact():
    spec = importlib.util.spec_from_file_location("mart_builder", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    builder = load_artifact()
    mart, checks = builder.build_order_mart(
        pd.read_csv(DATA / "users.csv"),
        pd.read_csv(DATA / "orders.csv"),
        pd.read_csv(DATA / "order_items.csv"),
    )
    with TemporaryDirectory() as directory:
        manifest = builder.export_mart(
            mart,
            checks,
            Path(directory),
            {
                "users": DATA / "users.csv",
                "orders": DATA / "orders.csv",
                "order_items": DATA / "order_items.csv",
            },
        )
        print(manifest["checks"])
        print(mart[["order_id", "user_found", "item_total"]].to_string(index=False))


if __name__ == "__main__":
    main()
