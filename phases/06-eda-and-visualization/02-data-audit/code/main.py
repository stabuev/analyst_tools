from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path


def main() -> None:
    data_path = Path(__file__).resolve().parents[2] / "data" / "tiny" / "user_journeys.csv"
    with data_path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))

    by_user: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_user[row["user_id"]].append(row)
    exact_duplicates = sorted(
        user_id
        for user_id, group in by_user.items()
        if len(group) > 1 and all(row == group[0] for row in group[1:])
    )
    conflicting_duplicates = sorted(
        user_id
        for user_id, group in by_user.items()
        if len(group) > 1 and any(row != group[0] for row in group[1:])
    )
    blank_keys = [line for line, row in enumerate(rows, start=2) if not row["user_id"].strip()]
    incomplete = [row["user_id"] for row in rows if int(row["observed_days"]) < 7]
    negative_sessions = [
        row["user_id"] for row in rows if row["sessions_7d"] and int(row["sessions_7d"]) < 0
    ]
    invalid_onboarding = [row["user_id"] for row in rows if int(row["onboarding_seconds"]) < 0]

    activation_blockers = []
    if blank_keys:
        activation_blockers.append("blank-key")
    if conflicting_duplicates:
        activation_blockers.append("conflicting-duplicate")
    if negative_sessions:
        activation_blockers.append("negative-sessions")
    print(
        json.dumps(
            {
                "source_rows": len(rows),
                "exact_duplicate_deliveries": exact_duplicates,
                "conflicting_duplicate_keys": conflicting_duplicates,
                "incomplete_windows_excluded_from_activation": incomplete,
                "activation_blockers": activation_blockers,
                "activation_requires_decision": bool(exact_duplicates),
                "onboarding_distribution_blockers": invalid_onboarding,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
