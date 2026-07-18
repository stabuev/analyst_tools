from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

LESSON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LESSON_ROOT / "outputs"))

from array_structure_auditor import (  # noqa: E402
    aligned_order_report,
    combine_report,
    unique_report,
)


def main() -> None:
    first_batch = np.array([[101, 120], [102, 80]], dtype=np.int64)
    second_batch = np.array([[103, 120], [104, 95]], dtype=np.int64)
    combined = combine_report(
        [first_batch, second_batch],
        mode="concatenate",
        axis=0,
        axis_names=("order", "field"),
    )

    ordered = aligned_order_report(
        [120, 80, 120, 95],
        {"order_id": [101, 102, 103, 104], "segment": ["A", "B", "C", "A"]},
    )
    segments = unique_report(["A", "B", "C", "A"])

    print("Сборка:", combined["output"])
    print("Единая перестановка:", ordered["permutation"])
    print("Заказы после сортировки:", ordered["sorted_payloads"]["order_id"])
    print("Частоты сегментов:", segments["counts"])


if __name__ == "__main__":
    main()
