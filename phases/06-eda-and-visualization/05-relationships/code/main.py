from __future__ import annotations

import json
from collections import defaultdict


def grouped_rate(rows: list[dict[str, object]]) -> dict[int, float]:
    groups: dict[int, list[bool]] = defaultdict(list)
    for row in rows:
        groups[int(row["sessions"])].append(bool(row["activated"]))
    return {sessions: sum(values) / len(values) for sessions, values in sorted(groups.items())}


def main() -> None:
    rows = [
        {"sessions": 1, "activated": False},
        {"sessions": 2, "activated": False},
        {"sessions": 4, "activated": True},
        {"sessions": 5, "activated": True},
    ]
    print(json.dumps(grouped_rate(rows), indent=2))


if __name__ == "__main__":
    main()
