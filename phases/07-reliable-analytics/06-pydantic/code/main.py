from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.pipeline_config import validate_json


def main() -> None:
    lesson_root = Path(__file__).resolve().parents[1]
    config = lesson_root / "outputs" / "example_config.json"
    report = validate_json(config.read_text(encoding="utf-8"))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
