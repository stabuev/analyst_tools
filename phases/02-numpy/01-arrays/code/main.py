from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "array_inspector.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("array_inspector", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    inspector = load_artifact()
    order_counts = [[12, 15, 9], [10, 11, 14]]
    report = inspector.inspect_values(order_counts)
    print(inspector.render_markdown(report), end="")


if __name__ == "__main__":
    main()
