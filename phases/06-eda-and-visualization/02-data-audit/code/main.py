from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    data_path = Path(__file__).resolve().parents[2] / "data" / "tiny" / "user_journeys.csv"
    with data_path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))

    user_counts = Counter(row["user_id"] for row in rows)
    duplicates = sorted(user_id for user_id, count in user_counts.items() if count > 1)
    incomplete = [row["user_id"] for row in rows if int(row["observed_days"]) < 7]
    invalid_onboarding = [row["user_id"] for row in rows if int(row["onboarding_seconds"]) < 0]
    structural_app_version_nulls = sum(
        row["platform"] == "web" and row["app_version"] == "" for row in rows
    )

    print(
        json.dumps(
            {
                "rows": len(rows),
                "unique_users": len(user_counts),
                "duplicate_user_ids": duplicates,
                "incomplete_windows": incomplete,
                "invalid_onboarding": invalid_onboarding,
                "structural_app_version_nulls": structural_app_version_nulls,
                "ready_for_activation": not duplicates
                and not incomplete
                and not invalid_onboarding,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
