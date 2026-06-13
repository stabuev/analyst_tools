from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "window_metrics.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("window_metrics", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manual_u001 = [
        {"order_id": "O1001", "number": 1, "cumulative": 1200.0},
        {"order_id": "O1005", "number": 2, "cumulative": 2700.0},
    ]
    report = load_artifact().build_window_metrics(DATA)
    print(json.dumps({"manual_u001": manual_u001, "duckdb": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
