from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "dataframe_inspector.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("dataframe_inspector", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    inspector = load_artifact()
    frame = inspector.load_table(DATA)
    report = inspector.inspect_dataframe(frame, ["order_id"])
    print(inspector.render_report(report), end="")


if __name__ == "__main__":
    main()
