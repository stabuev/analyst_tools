from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.quality_monitor import monitor_batch


def main() -> None:
    lesson_root = Path(__file__).resolve().parents[1]
    data_dir = lesson_root.parent / "data" / "tiny"
    thresholds = json.loads(
        (lesson_root / "outputs" / "example_thresholds.json").read_text(encoding="utf-8")
    )
    observed_at = datetime.fromisoformat("2026-06-10T12:00:00+03:00")
    report = monitor_batch(data_dir, thresholds, observed_at)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
