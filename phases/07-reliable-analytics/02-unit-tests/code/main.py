from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.order_stage_contracts import load_frames, run_contract_suite


def main() -> None:
    lesson_root = Path(__file__).resolve().parents[1]
    data_dir = lesson_root.parent / "data" / "tiny"
    users, orders, items = load_frames(data_dir)
    report = run_contract_suite(data_dir)
    report["input_shapes"] = {
        "users": list(users.shape),
        "orders": list(orders.shape),
        "order_items": list(items.shape),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
