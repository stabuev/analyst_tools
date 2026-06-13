from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outputs.grain_key_audit import audit_dataset


def manual_key_audit(
    rows: list[dict[str, str | None]],
    keys: list[str],
) -> dict[str, Any]:
    key_values = [tuple(row.get(key) or None for key in keys) for row in rows]
    counts = Counter(key for key in key_values if all(value is not None for value in key))
    duplicates = [
        {"key": list(key), "row_count": count} for key, count in sorted(counts.items()) if count > 1
    ]
    return {
        "rows": len(rows),
        "keys": keys,
        "null_key_rows": sum(any(value is None for value in key) for key in key_values),
        "duplicate_groups": len(duplicates),
        "duplicates": duplicates,
    }


def load_csv(path: Path) -> list[dict[str, str | None]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def main() -> None:
    lesson_root = Path(__file__).resolve().parents[1]
    data_root = lesson_root.parent / "data"
    tiny_root = data_root / "tiny"
    manual = manual_key_audit(load_csv(tiny_root / "events.csv"), ["event_id"])
    duckdb_report = audit_dataset(tiny_root, data_root / "contract.json")
    print(
        json.dumps(
            {
                "manual_events_key_check": manual,
                "duckdb_summary": duckdb_report["summary"],
                "duckdb_event_key_check": duckdb_report["tables"]["events"]["primary_key"],
                "orders_users_relationship": next(
                    relationship
                    for relationship in duckdb_report["relationships"]
                    if relationship["child_table"] == "orders"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
