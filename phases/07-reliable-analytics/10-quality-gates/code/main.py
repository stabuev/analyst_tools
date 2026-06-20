from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.reliable_order_pipeline import run_pipeline


def main() -> None:
    lesson_root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory() as directory:
        root = Path(directory)
        config = {
            "config_version": "1.0.0",
            "input_dir": str(lesson_root.parent / "data" / "tiny"),
            "output_dir": str(root / "delivery"),
            "timezone": "Europe/Moscow",
            "batch_date": "2026-06-10",
            "schema_version": "1.0.0",
            "thresholds": {
                "freshness_hours": 24,
                "min_orders": 1,
                "max_orders": 100,
                "max_null_rate": 0.0,
                "max_duplicate_rate": 0.0,
            },
        }
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        report = run_pipeline(
            config_path,
            datetime.fromisoformat("2026-06-10T12:00:00+03:00"),
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
