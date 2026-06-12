from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "outputs" / "reshape_contract.py"
DATA = ROOT.parent / "data" / "tiny" / "orders.csv"


def load_artifact():
    spec = importlib.util.spec_from_file_location("reshape_contract", ARTIFACT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ARTIFACT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    reshape = load_artifact()
    long, wide = reshape.build_status_matrix(pd.read_csv(DATA))
    print(long.to_string(index=False))
    print(wide.to_string(index=False))


if __name__ == "__main__":
    main()
