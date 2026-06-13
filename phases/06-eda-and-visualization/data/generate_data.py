from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

SAMPLE_USERS = 20_000
SAMPLE_SEED = 20_260_613
START_DATE = date(2026, 1, 5)
OBSERVATION_END = date(2026, 4, 5)
RELEASE_DATE = date(2026, 3, 2)
MOSCOW = timezone(timedelta(hours=3))

COLUMNS = (
    "user_id",
    "registered_at",
    "cohort_week",
    "platform",
    "app_version",
    "country",
    "acquisition_channel",
    "plan",
    "observed_days",
    "onboarding_seconds",
    "sessions_7d",
    "activated_7d",
    "first_order_amount_rub",
    "support_tickets_7d",
)

TINY_VALUES = [
    (
        "J001",
        "2026-01-05T09:00:00+03:00",
        "2026-01-05",
        "web",
        "",
        "RU",
        "organic",
        "basic",
        "7",
        "90",
        "5",
        "true",
        "1200.00",
        "0",
    ),
    (
        "J002",
        "2026-01-05T11:00:00+03:00",
        "2026-01-05",
        "ios",
        "5.1",
        "KZ",
        "search",
        "premium",
        "7",
        "110",
        "4",
        "true",
        "2400.00",
        "0",
    ),
    (
        "J003",
        "2026-01-06T10:00:00+03:00",
        "2026-01-05",
        "android",
        "2.3",
        "RU",
        "organic",
        "basic",
        "7",
        "130",
        "5",
        "true",
        "900.00",
        "0",
    ),
    (
        "J004",
        "2026-01-07T12:00:00+03:00",
        "2026-01-05",
        "android",
        "2.3",
        "AM",
        "paid_social",
        "trial",
        "7",
        "200",
        "2",
        "false",
        "",
        "1",
    ),
    (
        "J005",
        "2026-01-12T09:30:00+03:00",
        "2026-01-12",
        "web",
        "",
        "RU",
        "organic",
        "basic",
        "7",
        "80",
        "6",
        "true",
        "1500.00",
        "0",
    ),
    (
        "J006",
        "2026-01-12T13:00:00+03:00",
        "2026-01-12",
        "ios",
        "5.1",
        "RU",
        "search",
        "premium",
        "7",
        "100",
        "5",
        "true",
        "3200.00",
        "0",
    ),
    (
        "J007",
        "2026-01-13T15:00:00+03:00",
        "2026-01-12",
        "android",
        "2.3",
        "KZ",
        "partner",
        "basic",
        "7",
        "160",
        "3",
        "true",
        "800.00",
        "1",
    ),
    (
        "J008",
        "2026-01-14T18:00:00+03:00",
        "2026-01-12",
        "web",
        "",
        "RU",
        "paid_social",
        "trial",
        "7",
        "240",
        "1",
        "false",
        "",
        "1",
    ),
    (
        "J009",
        "2026-01-19T10:00:00+03:00",
        "2026-01-19",
        "ios",
        "5.1",
        "DE",
        "organic",
        "premium",
        "7",
        "70",
        "7",
        "true",
        "50000.00",
        "0",
    ),
    (
        "J010",
        "2026-01-20T09:00:00+03:00",
        "2026-01-19",
        "android",
        "2.3",
        "RU",
        "search",
        "basic",
        "7",
        "145",
        "4",
        "true",
        "1000.00",
        "0",
    ),
    (
        "J011",
        "2026-01-21T14:00:00+03:00",
        "2026-01-19",
        "web",
        "",
        "KZ",
        "partner",
        "basic",
        "7",
        "-1",
        "3",
        "false",
        "",
        "1",
    ),
    (
        "J012",
        "2026-01-22T16:00:00+03:00",
        "2026-01-19",
        "ios",
        "5.1",
        "RU",
        "paid_social",
        "trial",
        "7",
        "300",
        "2",
        "false",
        "",
        "2",
    ),
    (
        "J013",
        "2026-03-02T09:00:00+03:00",
        "2026-03-02",
        "android",
        "2.4",
        "RU",
        "paid_social",
        "basic",
        "7",
        "260",
        "2",
        "false",
        "",
        "2",
    ),
    (
        "J014",
        "2026-03-02T12:00:00+03:00",
        "2026-03-02",
        "android",
        "2.4",
        "KZ",
        "organic",
        "premium",
        "7",
        "210",
        "3",
        "false",
        "",
        "1",
    ),
    (
        "J015",
        "2026-03-03T10:00:00+03:00",
        "2026-03-02",
        "ios",
        "5.2",
        "",
        "paid_social",
        "trial",
        "7",
        "190",
        "2",
        "false",
        "",
        "1",
    ),
    (
        "J016",
        "2026-03-04T17:00:00+03:00",
        "2026-03-02",
        "web",
        "",
        "RU",
        "paid_social",
        "basic",
        "7",
        "150",
        "3",
        "true",
        "1100.00",
        "0",
    ),
    (
        "J017",
        "2026-03-09T11:00:00+03:00",
        "2026-03-09",
        "android",
        "2.4",
        "RU",
        "paid_social",
        "trial",
        "7",
        "420",
        "1",
        "false",
        "",
        "2",
    ),
    (
        "J018",
        "2026-03-09T14:00:00+03:00",
        "2026-03-09",
        "ios",
        "5.2",
        "RU",
        "organic",
        "premium",
        "7",
        "85",
        "6",
        "true",
        "2800.00",
        "0",
    ),
    (
        "J019",
        "2026-03-10T09:00:00+03:00",
        "2026-03-09",
        "web",
        "",
        "AM",
        "search",
        "basic",
        "7",
        "95",
        "5",
        "true",
        "1300.00",
        "0",
    ),
    (
        "J020",
        "2026-03-11T19:00:00+03:00",
        "2026-03-09",
        "android",
        "2.4",
        "KZ",
        "partner",
        "basic",
        "7",
        "3600",
        "2",
        "false",
        "",
        "3",
    ),
    (
        "J021",
        "2026-03-16T10:00:00+03:00",
        "2026-03-16",
        "android",
        "2.4",
        "RU",
        "paid_social",
        "basic",
        "7",
        "280",
        "2",
        "false",
        "",
        "1",
    ),
    (
        "J022",
        "2026-03-16T15:00:00+03:00",
        "2026-03-16",
        "ios",
        "5.2",
        "RU",
        "paid_social",
        "basic",
        "7",
        "170",
        "3",
        "true",
        "900.00",
        "0",
    ),
    (
        "J023",
        "2026-04-01T10:00:00+03:00",
        "2026-03-30",
        "web",
        "",
        "RU",
        "paid_social",
        "trial",
        "5",
        "100",
        "",
        "",
        "",
        "",
    ),
    (
        "J024",
        "2026-04-04T18:00:00+03:00",
        "2026-03-30",
        "android",
        "2.4",
        "KZ",
        "organic",
        "basic",
        "2",
        "200",
        "",
        "",
        "",
        "",
    ),
    (
        "J018",
        "2026-03-09T14:00:00+03:00",
        "2026-03-09",
        "ios",
        "5.2",
        "RU",
        "organic",
        "premium",
        "7",
        "85",
        "6",
        "true",
        "2800.00",
        "0",
    ),
]


def tiny_rows() -> list[dict[str, str]]:
    return [dict(zip(COLUMNS, values, strict=True)) for values in TINY_VALUES]


def weighted_channel(rng: random.Random, registered: date) -> str:
    channels = ["organic", "search", "paid_social", "partner"]
    weights = [50, 30, 10, 10] if registered < RELEASE_DATE else [25, 20, 45, 10]
    return rng.choices(channels, weights=weights, k=1)[0]


def app_version(platform: str, registered: date) -> str:
    if platform == "web":
        return ""
    if platform == "android":
        return "2.3" if registered < RELEASE_DATE else "2.4"
    return "5.1" if registered < RELEASE_DATE else "5.2"


def sample_rows() -> list[dict[str, str]]:
    rng = random.Random(SAMPLE_SEED)
    rows: list[dict[str, str]] = []
    channel_activation = {
        "organic": 0.66,
        "search": 0.60,
        "paid_social": 0.40,
        "partner": 0.54,
    }
    for index in range(1, SAMPLE_USERS + 1):
        registered_date = START_DATE + timedelta(
            days=rng.randrange((OBSERVATION_END - START_DATE).days + 1)
        )
        registered_at = datetime.combine(
            registered_date,
            time(hour=rng.randrange(8, 20), minute=rng.choice([0, 15, 30, 45])),
            tzinfo=MOSCOW,
        )
        cohort_week = registered_date - timedelta(days=registered_date.weekday())
        platform = rng.choices(["web", "ios", "android"], weights=[34, 31, 35], k=1)[0]
        channel = weighted_channel(rng, registered_date)
        observed_days = min(7, (OBSERVATION_END - registered_date).days + 1)
        onboarding = int(round(rng.lognormvariate(math.log(120), 0.55)))
        if platform == "android" and registered_date >= RELEASE_DATE:
            onboarding += 75
        if index == 137:
            onboarding = -1
        elif index % 997 == 0:
            onboarding = 3600

        sessions = max(0, int(round(rng.gauss(3.7, 2.1))))
        activation_probability = channel_activation[channel]
        activation_probability += {"web": 0.0, "ios": 0.04, "android": -0.02}[platform]
        activation_probability += min(sessions, 6) * 0.035
        activation_probability -= max(sessions - 8, 0) * 0.01
        if platform == "android" and registered_date >= RELEASE_DATE:
            activation_probability -= 0.12
        if onboarding > 240:
            activation_probability -= 0.06
        activation_probability = min(0.92, max(0.05, activation_probability))

        if observed_days < 7:
            sessions_value = ""
            activated_value = ""
            amount_value = ""
            tickets_value = ""
        else:
            activated = rng.random() < activation_probability
            sessions_value = str(sessions)
            activated_value = str(activated).lower()
            if activated and rng.random() < 0.55:
                amount = rng.lognormvariate(math.log(1400), 0.85)
                if index % 701 == 0:
                    amount = 75_000
                amount_value = f"{amount:.2f}"
            else:
                amount_value = ""
            ticket_mean = 0.3 + (0.55 if not activated else 0.0)
            if platform == "android" and registered_date >= RELEASE_DATE:
                ticket_mean += 0.35
            tickets_value = str(max(0, int(round(rng.gauss(ticket_mean, 0.65)))))

        country = ""
        if index % 97 != 0:
            country = rng.choices(["RU", "KZ", "AM", "DE"], weights=[62, 20, 10, 8], k=1)[0]
        row = {
            "user_id": f"J{index:05d}",
            "registered_at": registered_at.isoformat(),
            "cohort_week": cohort_week.isoformat(),
            "platform": platform,
            "app_version": app_version(platform, registered_date),
            "country": country,
            "acquisition_channel": channel,
            "plan": rng.choices(["trial", "basic", "premium"], weights=[35, 50, 15], k=1)[0],
            "observed_days": str(observed_days),
            "onboarding_seconds": str(onboarding),
            "sessions_7d": sessions_value,
            "activated_7d": activated_value,
            "first_order_amount_rub": amount_value,
            "support_tickets_7d": tickets_value,
        }
        rows.append(row)
    rows.append(dict(rows[777]))
    return rows


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate(profile: str, output_dir: Path) -> dict[str, Any]:
    rows = tiny_rows() if profile == "tiny" else sample_rows()
    output_dir.mkdir(parents=True, exist_ok=True)
    data_path = output_dir / "user_journeys.csv"
    write_csv(data_path, rows)
    contract_path = Path(__file__).parent / "contract.json"
    manifest: dict[str, Any] = {
        "version": "1.0.0",
        "profile": profile,
        "generated_by": "generate_data.py",
        "seed": None if profile == "tiny" else SAMPLE_SEED,
        "contract_sha256": sha256_file(contract_path),
        "files": {
            data_path.name: {
                "rows": len(rows),
                "unique_users": len({row["user_id"] for row in rows}),
                "bytes": data_path.stat().st_size,
                "sha256": sha256_file(data_path),
            }
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def check_committed() -> None:
    committed = Path(__file__).parent / "tiny"
    with TemporaryDirectory() as directory:
        generated = Path(directory)
        generate("tiny", generated)
        for filename in ("user_journeys.csv", "manifest.json"):
            if (committed / filename).read_bytes() != (generated / filename).read_bytes():
                raise SystemExit(f"Committed tiny data is stale: {filename}")
    print("Committed phase 06 tiny data is reproducible.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic EDA phase data")
    parser.add_argument("--profile", choices=("tiny", "sample"), default="tiny")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check_committed()
        return
    output = args.output or Path(__file__).parent / args.profile
    manifest = generate(args.profile, output)
    file_meta = manifest["files"]["user_journeys.csv"]
    print(f"Generated {file_meta['rows']} rows in {output}")


if __name__ == "__main__":
    main()
