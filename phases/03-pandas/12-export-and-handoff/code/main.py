from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "mart_builder.py"
DATA = ROOT.parent / "data" / "tiny"
BUSINESS_TIMEZONE = "Europe/Moscow"


def load_artifact():
    spec = importlib.util.spec_from_file_location("mart_builder", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_source(name: str) -> pd.DataFrame:
    return pd.read_csv(
        DATA / name,
        dtype="string",
        keep_default_na=False,
        encoding="utf-8",
    )


def main() -> None:
    builder = load_artifact()
    mart, quality = builder.build_order_mart(
        read_source("users.csv"),
        read_source("orders.csv"),
        read_source("order_items.csv"),
        business_timezone=BUSINESS_TIMEZONE,
    )
    source_paths = {
        "users": DATA / "users.csv",
        "orders": DATA / "orders.csv",
        "order_items": DATA / "order_items.csv",
    }
    with TemporaryDirectory() as directory:
        output_dir = Path(directory)
        manifest = builder.export_delivery(
            mart,
            quality,
            output_dir,
            source_paths,
            business_timezone=BUSINESS_TIMEZONE,
        )
        verification = builder.verify_delivery(output_dir)
        print("Publish status:", manifest["publish_status"])
        print("Warnings:")
        for name, check in quality["checks"].items():
            if check["status"] == "warning":
                print(f"- {name}: {check}")
        print("Recipient verification:", verification)
        print(mart[["order_id", "user_found", "item_total"]].to_string(index=False))


if __name__ == "__main__":
    main()
