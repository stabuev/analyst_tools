from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "time_model.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("time_model", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manual_o1001 = {
        "source": "2026-01-05T10:00:00+03:00",
        "utc": "2026-01-05T07:00:00Z",
        "moscow": "2026-01-05 10:00:00",
    }
    report = load_artifact().normalize_order_times(DATA)
    print(
        json.dumps({"manual_o1001": manual_o1001, "duckdb": report}, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
