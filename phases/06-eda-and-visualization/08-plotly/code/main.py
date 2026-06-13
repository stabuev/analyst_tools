from __future__ import annotations

import json


def hover_record(row: dict[str, object]) -> dict[str, object]:
    return {
        "user_id": row["user_id"],
        "platform": row["platform"],
        "onboarding_seconds": row["onboarding_seconds"],
    }


def main() -> None:
    row = {"user_id": "J020", "platform": "android", "onboarding_seconds": 3600}
    print(json.dumps(hover_record(row), indent=2))


if __name__ == "__main__":
    main()
