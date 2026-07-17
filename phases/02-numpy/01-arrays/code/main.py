from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "array_contract.py"


def load_artifact():
    spec = importlib.util.spec_from_file_location("array_contract", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    contract = load_artifact()
    order_counts = [[12, 15, 9], [10, 11, 14]]

    report = contract.describe_array(order_counts, axes=("store", "day"))
    print(contract.format_contract(report))

    array = contract.require_numeric_array(
        order_counts,
        axes=("store", "day"),
    )
    doubled = array * 2

    print(f"Python list * 2: {order_counts * 2}")
    print(f"ndarray * 2:\n{doubled}")


if __name__ == "__main__":
    main()
