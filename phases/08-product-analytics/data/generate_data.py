from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parent
SAMPLE_SEED = 20_260_619
SAMPLE_USERS = 250
MOSCOW = timezone(timedelta(hours=3))

USER_COLUMNS = (
    "user_id",
    "registered_at",
    "country",
    "acquisition_channel",
    "platform",
    "is_test_user",
)
SESSION_COLUMNS = ("session_id", "user_id", "started_at", "ended_at", "platform")
EVENT_COLUMNS = (
    "event_id",
    "user_id",
    "anonymous_id",
    "session_id",
    "event_name",
    "event_version",
    "occurred_at",
    "received_at",
    "platform",
    "app_version",
    "properties_json",
)
SUBSCRIPTION_COLUMNS = (
    "subscription_id",
    "user_id",
    "started_at",
    "ended_at",
    "status",
    "plan",
    "price_rub",
)
ORDER_COLUMNS = ("order_id", "user_id", "ordered_at", "status", "currency", "amount_rub")
TICKET_COLUMNS = ("ticket_id", "user_id", "created_at", "category", "status")
RELEASE_COLUMNS = ("release_id", "released_at", "platform", "app_version", "change")

TINY_USERS = [
    ("U001", "2026-06-01T09:00:00+03:00", "RU", "organic", "web", "false"),
    ("U002", "2026-06-01T10:10:00+03:00", "RU", "paid_search", "ios", "false"),
    ("U003", "2026-06-02T11:20:00+03:00", "KZ", "referral", "android", "false"),
    ("U004", "2026-06-03T12:30:00+03:00", "AM", "organic", "android", "false"),
    ("U005", "2026-06-04T13:40:00+03:00", "RU", "paid_search", "ios", "false"),
    ("U006", "2026-06-05T14:50:00+03:00", "DE", "organic", "web", "false"),
    ("U007", "2026-06-08T15:00:00+03:00", "RU", "paid_social", "android", "false"),
    ("U999", "2026-06-08T16:00:00+03:00", "RU", "internal", "web", "true"),
]

TINY_SESSIONS = [
    ("S001", "U001", "2026-06-01T09:00:00+03:00", "2026-06-01T09:32:00+03:00", "web"),
    ("S002", "U002", "2026-06-01T10:10:00+03:00", "2026-06-01T10:24:00+03:00", "ios"),
    ("S003", "U003", "2026-06-02T11:20:00+03:00", "2026-06-02T11:48:00+03:00", "android"),
    ("S004", "U004", "2026-06-03T12:30:00+03:00", "2026-06-03T12:41:00+03:00", "android"),
    ("S005", "U005", "2026-06-04T13:40:00+03:00", "2026-06-04T14:08:00+03:00", "ios"),
    ("S006", "U006", "2026-06-05T14:50:00+03:00", "2026-06-05T15:04:00+03:00", "web"),
    ("S007", "U007", "2026-06-08T15:00:00+03:00", "2026-06-08T15:19:00+03:00", "android"),
    ("S999", "U999", "2026-06-08T16:00:00+03:00", "2026-06-08T16:11:00+03:00", "web"),
]

TINY_SUBSCRIPTIONS = [
    ("SUB001", "U001", "2026-06-01T09:20:00+03:00", "", "active", "basic", "990.00"),
    ("SUB002", "U002", "2026-06-01T10:22:00+03:00", "", "active", "premium", "1490.00"),
    ("SUB003", "U005", "2026-06-04T13:58:00+03:00", "2026-06-09T08:00:00+03:00", "cancelled", "premium", "1490.00"),
    ("SUB004", "U007", "2026-06-08T15:12:00+03:00", "", "trial", "basic", "0.00"),
]

TINY_ORDERS = [
    ("O001", "U001", "2026-06-01T09:20:00+03:00", "paid", "RUB", "990.00"),
    ("O002", "U002", "2026-06-01T10:22:00+03:00", "paid", "RUB", "1490.00"),
    ("O003", "U005", "2026-06-04T13:58:00+03:00", "refunded", "RUB", "1490.00"),
    ("O004", "U006", "2026-06-05T15:01:00+03:00", "paid", "RUB", "450.00"),
    ("O005", "U007", "2026-06-08T15:12:00+03:00", "pending", "RUB", "990.00"),
]

TINY_TICKETS = [
    ("T001", "U005", "2026-06-09T08:05:00+03:00", "billing", "open"),
    ("T002", "U007", "2026-06-08T15:17:00+03:00", "paywall", "open"),
    ("T003", "U003", "2026-06-03T10:00:00+03:00", "onboarding", "closed"),
]

TINY_RELEASES = [
    ("R001", "2026-06-01T08:00:00+03:00", "all", "2026.6.1", "new_onboarding_and_paywall"),
    ("R002", "2026-06-08T09:00:00+03:00", "android", "2026.6.2", "android_paywall_hotfix"),
]


def event(
    event_id: str,
    user_id: str,
    anonymous_id: str,
    session_id: str,
    event_name: str,
    occurred_at: str,
    platform: str,
    app_version: str,
    properties: dict[str, Any] | None = None,
    received_delay_seconds: int = 7,
) -> tuple[str, ...]:
    occurred = datetime.fromisoformat(occurred_at)
    received = occurred + timedelta(seconds=received_delay_seconds)
    return (
        event_id,
        user_id,
        anonymous_id,
        session_id,
        event_name,
        "1",
        occurred.isoformat(),
        received.isoformat(),
        platform,
        app_version,
        json.dumps(properties or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


TINY_EVENTS = [
    event("E001", "U001", "A001", "S001", "signup_started", "2026-06-01T09:01:00+03:00", "web", "", {"entry": "landing"}),
    event("E002", "U001", "A001", "S001", "account_created", "2026-06-01T09:04:00+03:00", "web", "", {"method": "email"}),
    event("E003", "U001", "A001", "S001", "onboarding_started", "2026-06-01T09:05:00+03:00", "web", "", {}),
    event("E004", "U001", "A001", "S001", "onboarding_completed", "2026-06-01T09:14:00+03:00", "web", "", {"steps": 4}),
    event("E005", "U001", "A001", "S001", "feature_value_seen", "2026-06-01T09:16:00+03:00", "web", "", {"feature": "weekly_plan"}),
    event("E006", "U001", "A001", "S001", "paywall_viewed", "2026-06-01T09:18:00+03:00", "web", "", {"variant": "new"}),
    event("E007", "U001", "A001", "S001", "trial_started", "2026-06-01T09:20:00+03:00", "web", "", {"plan": "basic"}),
    event("E008", "U001", "A001", "S001", "subscription_started", "2026-06-01T09:21:00+03:00", "web", "", {"plan": "basic"}),
    event("E009", "U002", "A002", "S002", "signup_started", "2026-06-01T10:11:00+03:00", "ios", "2026.6.1", {"entry": "ad"}),
    event("E010", "U002", "A002", "S002", "account_created", "2026-06-01T10:13:00+03:00", "ios", "2026.6.1", {"method": "apple"}),
    event("E011", "U002", "A002", "S002", "onboarding_started", "2026-06-01T10:14:00+03:00", "ios", "2026.6.1", {}),
    event("E012", "U002", "A002", "S002", "onboarding_completed", "2026-06-01T10:19:00+03:00", "ios", "2026.6.1", {"steps": 3}),
    event("E013", "U002", "A002", "S002", "paywall_viewed", "2026-06-01T10:21:00+03:00", "ios", "2026.6.1", {"variant": "new"}),
    event("E014", "U002", "A002", "S002", "subscription_started", "2026-06-01T10:22:00+03:00", "ios", "2026.6.1", {"plan": "premium"}),
    event("E015", "U003", "A003", "S003", "signup_started", "2026-06-02T11:21:00+03:00", "android", "2026.6.1", {"entry": "invite"}),
    event("E016", "U003", "A003", "S003", "account_created", "2026-06-02T11:24:00+03:00", "android", "2026.6.1", {"method": "email"}),
    event("E017", "U003", "A003", "S003", "onboarding_started", "2026-06-02T11:25:00+03:00", "android", "2026.6.1", {}),
    event("E018", "U003", "A003", "S003", "onboarding_completed", "2026-06-02T11:42:00+03:00", "android", "2026.6.1", {"steps": 4}),
    event("E019", "U003", "A003", "S003", "feature_value_seen", "2026-06-02T11:45:00+03:00", "android", "2026.6.1", {"feature": "weekly_plan"}),
    event("E020", "U004", "A004", "S004", "signup_started", "2026-06-03T12:31:00+03:00", "android", "2026.6.1", {"entry": "landing"}),
    event("E021", "U004", "A004", "S004", "account_created", "2026-06-03T12:34:00+03:00", "android", "2026.6.1", {"method": "email"}),
    event("E022", "U004", "A004", "S004", "onboarding_started", "2026-06-03T12:36:00+03:00", "android", "2026.6.1", {}),
    event("E023", "U005", "A005", "S005", "signup_started", "2026-06-04T13:41:00+03:00", "ios", "2026.6.1", {"entry": "ad"}),
    event("E024", "U005", "A005", "S005", "account_created", "2026-06-04T13:43:00+03:00", "ios", "2026.6.1", {"method": "apple"}),
    event("E025", "U005", "A005", "S005", "onboarding_started", "2026-06-04T13:44:00+03:00", "ios", "2026.6.1", {}),
    event("E026", "U005", "A005", "S005", "onboarding_completed", "2026-06-04T13:50:00+03:00", "ios", "2026.6.1", {"steps": 3}),
    event("E027", "U005", "A005", "S005", "paywall_viewed", "2026-06-04T13:56:00+03:00", "ios", "2026.6.1", {"variant": "new"}),
    event("E028", "U005", "A005", "S005", "subscription_started", "2026-06-04T13:58:00+03:00", "ios", "2026.6.1", {"plan": "premium"}),
    event("E029", "U005", "A005", "S005", "subscription_cancelled", "2026-06-09T08:00:00+03:00", "ios", "2026.6.1", {"reason": "billing"}),
    event("E030", "U006", "A006", "S006", "app_open", "2026-06-05T14:51:00+03:00", "web", "", {"source": "bookmark"}),
    event("E031", "U006", "A006", "S006", "feature_value_seen", "2026-06-05T14:56:00+03:00", "web", "", {"feature": "marketplace"}),
    event("E032", "U006", "A006", "S006", "order_paid", "2026-06-05T15:01:00+03:00", "web", "", {"order_id": "O004"}),
    event("E033", "U007", "A007", "S007", "signup_started", "2026-06-08T15:01:00+03:00", "android", "2026.6.2", {"entry": "ad"}),
    event("E034", "U007", "A007", "S007", "account_created", "2026-06-08T15:03:00+03:00", "android", "2026.6.2", {"method": "google"}),
    event("E035", "U007", "A007", "S007", "onboarding_started", "2026-06-08T15:04:00+03:00", "android", "2026.6.2", {}),
    event("E036", "U007", "A007", "S007", "onboarding_completed", "2026-06-08T15:10:00+03:00", "android", "2026.6.2", {"steps": 3}),
    event("E037", "U007", "A007", "S007", "paywall_viewed", "2026-06-08T15:11:00+03:00", "android", "2026.6.2", {"variant": "new"}),
    event("E038", "U007", "A007", "S007", "trial_started", "2026-06-08T15:12:00+03:00", "android", "2026.6.2", {"plan": "basic"}),
    event("E039", "U007", "A007", "S007", "support_ticket_created", "2026-06-08T15:17:00+03:00", "android", "2026.6.2", {"category": "paywall"}),
    event("E040", "U999", "A999", "S999", "signup_started", "2026-06-08T16:01:00+03:00", "web", "", {"entry": "internal"}),
    event("E041", "U999", "A999", "S999", "account_created", "2026-06-08T16:02:00+03:00", "web", "", {"method": "email"}),
]


def rows(columns: tuple[str, ...], values: list[tuple[str, ...]]) -> list[dict[str, str]]:
    return [dict(zip(columns, value, strict=True)) for value in values]


def write_csv(path: Path, fieldnames: tuple[str, ...], records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def tiny_records() -> dict[str, list[dict[str, str]]]:
    return {
        "users": rows(USER_COLUMNS, TINY_USERS),
        "sessions": rows(SESSION_COLUMNS, TINY_SESSIONS),
        "events": rows(EVENT_COLUMNS, TINY_EVENTS),
        "subscriptions": rows(SUBSCRIPTION_COLUMNS, TINY_SUBSCRIPTIONS),
        "orders": rows(ORDER_COLUMNS, TINY_ORDERS),
        "support_tickets": rows(TICKET_COLUMNS, TINY_TICKETS),
        "release_calendar": rows(RELEASE_COLUMNS, TINY_RELEASES),
    }


def sample_records() -> dict[str, list[dict[str, str]]]:
    rng = random.Random(SAMPLE_SEED)
    start = datetime(2026, 6, 1, 9, tzinfo=MOSCOW)
    users: list[dict[str, str]] = []
    sessions: list[dict[str, str]] = []
    events: list[dict[str, str]] = []
    subscriptions: list[dict[str, str]] = []
    orders: list[dict[str, str]] = []
    tickets: list[dict[str, str]] = []
    event_index = 1
    for index in range(1, SAMPLE_USERS + 1):
        platform = rng.choice(["web", "ios", "android"])
        registered_at = start + timedelta(minutes=index * 23)
        user_id = f"U{index:05d}"
        session_id = f"S{index:05d}"
        users.append(
            {
                "user_id": user_id,
                "registered_at": registered_at.isoformat(),
                "country": rng.choice(["RU", "KZ", "AM", "DE"]),
                "acquisition_channel": rng.choice(["organic", "paid_search", "paid_social", "referral"]),
                "platform": platform,
                "is_test_user": "false",
            }
        )
        sessions.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "started_at": registered_at.isoformat(),
                "ended_at": (registered_at + timedelta(minutes=rng.randint(6, 45))).isoformat(),
                "platform": platform,
            }
        )
        app_version = "" if platform == "web" else rng.choice(["2026.6.1", "2026.6.2"])
        flow = ["signup_started", "account_created", "onboarding_started"]
        if rng.random() < 0.78:
            flow.append("onboarding_completed")
        if rng.random() < 0.62:
            flow.append("feature_value_seen")
        if rng.random() < 0.55:
            flow.append("paywall_viewed")
        if rng.random() < 0.32:
            flow.append("trial_started")
            subscriptions.append(
                {
                    "subscription_id": f"SUB{index:05d}",
                    "user_id": user_id,
                    "started_at": (registered_at + timedelta(minutes=18)).isoformat(),
                    "ended_at": "",
                    "status": "trial",
                    "plan": rng.choice(["basic", "premium"]),
                    "price_rub": "0.00",
                }
            )
        for offset, event_name in enumerate(flow, start=1):
            events.append(
                dict(
                    zip(
                        EVENT_COLUMNS,
                        event(
                            f"E{event_index:07d}",
                            user_id,
                            f"A{index:05d}",
                            session_id,
                            event_name,
                            (registered_at + timedelta(minutes=offset)).isoformat(),
                            platform,
                            app_version,
                            {"generated": True},
                        ),
                        strict=True,
                    )
                )
            )
            event_index += 1
        if rng.random() < 0.18:
            orders.append(
                {
                    "order_id": f"O{index:05d}",
                    "user_id": user_id,
                    "ordered_at": (registered_at + timedelta(days=rng.randint(0, 10))).isoformat(),
                    "status": rng.choice(["paid", "paid", "refunded", "pending"]),
                    "currency": "RUB",
                    "amount_rub": f"{rng.choice([45000, 99000, 149000]) / 100:.2f}",
                }
            )
        if rng.random() < 0.08:
            tickets.append(
                {
                    "ticket_id": f"T{index:05d}",
                    "user_id": user_id,
                    "created_at": (registered_at + timedelta(days=rng.randint(0, 8))).isoformat(),
                    "category": rng.choice(["billing", "paywall", "onboarding"]),
                    "status": rng.choice(["open", "closed"]),
                }
            )
    return {
        "users": users,
        "sessions": sessions,
        "events": events,
        "subscriptions": subscriptions,
        "orders": orders,
        "support_tickets": tickets,
        "release_calendar": rows(RELEASE_COLUMNS, TINY_RELEASES),
    }


def write_profile(profile: str, output_root: Path) -> dict[str, Any]:
    records = tiny_records() if profile == "tiny" else sample_records()
    output_root.mkdir(parents=True, exist_ok=True)
    specs = {
        "users": ("users.csv", USER_COLUMNS),
        "sessions": ("sessions.csv", SESSION_COLUMNS),
        "events": ("events.csv", EVENT_COLUMNS),
        "subscriptions": ("subscriptions.csv", SUBSCRIPTION_COLUMNS),
        "orders": ("orders.csv", ORDER_COLUMNS),
        "support_tickets": ("support_tickets.csv", TICKET_COLUMNS),
        "release_calendar": ("release_calendar.csv", RELEASE_COLUMNS),
    }
    files: dict[str, dict[str, Any]] = {}
    for name, (filename, columns) in specs.items():
        path = output_root / filename
        write_csv(path, columns, records[name])
        files[filename] = {
            "rows": len(records[name]),
            "sha256": checksum(path),
        }
    manifest = {
        "profile": profile,
        "generator": "generate_data.py",
        "seed": SAMPLE_SEED if profile == "sample" else None,
        "files": files,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def check_tiny() -> None:
    expected_root = ROOT / "tiny"
    with TemporaryDirectory() as directory:
        actual_root = Path(directory) / "tiny"
        write_profile("tiny", actual_root)
        expected_files = sorted(path.name for path in expected_root.iterdir())
        actual_files = sorted(path.name for path in actual_root.iterdir())
        if expected_files != actual_files:
            raise SystemExit(
                f"tiny file set differs: expected={expected_files}, actual={actual_files}"
            )
        for filename in expected_files:
            if (expected_root / filename).read_bytes() != (actual_root / filename).read_bytes():
                raise SystemExit(f"tiny product dataset is stale: {filename}")
    print("Tiny product analytics dataset is reproducible.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate phase 08 product analytics datasets")
    parser.add_argument("--profile", choices=("tiny", "sample"), default="tiny")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check_tiny()
        return
    output_dir = args.output_dir or ROOT / args.profile
    manifest = write_profile(args.profile, output_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
