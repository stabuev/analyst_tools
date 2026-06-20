from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.sql_quality_checks import run_checks


def main() -> None:
    lesson_root = Path(__file__).resolve().parents[1]
    data_dir = lesson_root.parent / "data" / "tiny"
    print(json.dumps(run_checks(data_dir), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
