from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.golden_regression import compare_with_golden


def main() -> None:
    lesson_root = Path(__file__).resolve().parents[1]
    data_dir = lesson_root.parent / "data" / "tiny"
    golden = lesson_root / "outputs" / "orders_golden.json"
    print(json.dumps(compare_with_golden(data_dir, golden), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
