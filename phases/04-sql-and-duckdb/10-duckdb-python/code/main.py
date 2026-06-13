from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "duckdb_runner.py"
SQL = ROOT / "outputs" / "paid_orders.sql"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("duckdb_runner", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    runner = load_artifact()
    frame, metadata = runner.execute_query(
        SQL.read_text(encoding="utf-8"),
        [str(DATA), 500],
        expected_columns=["order_id", "user_id", "currency", "amount"],
    )
    print(
        json.dumps(
            {"metadata": metadata, "records": frame.to_dict(orient="records")},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
