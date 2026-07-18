from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ARTIFACT = Path(__file__).resolve().parents[1] / "outputs" / "selection_contract.py"
SPEC = importlib.util.spec_from_file_location("selection_contract", ARTIFACT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {ARTIFACT}")
SELECTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTION)


if __name__ == "__main__":
    orders = np.array(
        [
            [101, 1, 1200, 2],
            [102, 3, 4500, 7],
            [103, 2, np.nan, 4],
            [104, 2, 3200, 3],
            [105, 5, 8000, 1],
        ],
        dtype=np.float64,
    )

    amount_ok = SELECTION.build_range_mask(
        orders[:, 2],
        lower=1000,
        upper=5000,
    )
    delivered_quickly = orders[:, 3] <= 5
    row_mask = amount_ok & delivered_quickly
    selected = SELECTION.select_rows(
        orders,
        row_mask,
        columns=[0, 2, 3],
    )

    print("row mask:", row_mask)
    print("selected shape:", selected.shape)
    print(selected)
    print("shares memory:", np.shares_memory(orders, selected))
    print("memory demo:", SELECTION.memory_report(orders))
