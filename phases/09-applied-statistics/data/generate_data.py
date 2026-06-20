from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SAMPLE_SEED = 20_260_619
MOSCOW = timezone(timedelta(hours=3))

POPULATION_COLUMNS = (
    "user_id",
    "registered_at",
    "platform",
    "acquisition_channel",
    "country",
    "plan",
    "device_tier",
    "is_test_user",
    "eligible_for_analysis",
    "true_observed_days",
    "true_sessions_7d",
    "true_activated_7d",
    "true_onboarding_seconds",
    "true_first_order_amount_rub",
    "true_support_tickets_7d",
)
FRAME_COLUMNS = (
    "user_id",
    "frame_source",
    "frame_version",
    "inclusion_probability",
    "response_probability",
    "sample_weight",
    "frame_reason",
)
SAMPLE_COLUMNS = (
    "user_id",
    "registered_at",
    "platform",
    "acquisition_channel",
    "country",
    "plan",
    "device_tier",
    "inclusion_probability",
    "response_probability",
    "sample_weight",
    "outcome_observed",
    "observed_days",
    "sessions_7d",
    "activated_7d",
    "onboarding_seconds",
    "first_order_amount_rub",
    "support_tickets_7d",
)
SEGMENT_COLUMNS = (
    "segment_id",
    "dimension",
    "level",
    "expected_population_share",
    "min_frame_coverage_rate",
    "min_response_rate",
)

TINY_POPULATION = [
    (
        "U001",
        "2026-06-01T09:00:00+03:00",
        "web",
        "organic",
        "RU",
        "basic",
        "high",
        "false",
        "true",
        "7",
        "5",
        "true",
        "420",
        "990.00",
        "0",
    ),
    (
        "U002",
        "2026-06-01T10:10:00+03:00",
        "ios",
        "paid_search",
        "RU",
        "premium",
        "high",
        "false",
        "true",
        "7",
        "4",
        "true",
        "360",
        "1490.00",
        "0",
    ),
    (
        "U003",
        "2026-06-02T11:20:00+03:00",
        "android",
        "referral",
        "KZ",
        "basic",
        "mid",
        "false",
        "true",
        "7",
        "3",
        "true",
        "900",
        "0.00",
        "1",
    ),
    (
        "U004",
        "2026-06-03T12:30:00+03:00",
        "android",
        "organic",
        "AM",
        "basic",
        "low",
        "false",
        "true",
        "7",
        "2",
        "false",
        "1300",
        "0.00",
        "1",
    ),
    (
        "U005",
        "2026-06-04T13:40:00+03:00",
        "web",
        "organic",
        "DE",
        "basic",
        "high",
        "false",
        "true",
        "7",
        "1",
        "false",
        "520",
        "450.00",
        "0",
    ),
    (
        "U006",
        "2026-06-05T14:50:00+03:00",
        "android",
        "paid_social",
        "RU",
        "basic",
        "low",
        "false",
        "true",
        "7",
        "1",
        "false",
        "1800",
        "0.00",
        "2",
    ),
    (
        "U007",
        "2026-06-06T15:00:00+03:00",
        "android",
        "paid_search",
        "RU",
        "premium",
        "mid",
        "false",
        "true",
        "7",
        "4",
        "true",
        "740",
        "990.00",
        "1",
    ),
    (
        "U008",
        "2026-06-06T15:40:00+03:00",
        "ios",
        "referral",
        "KZ",
        "basic",
        "mid",
        "false",
        "true",
        "7",
        "3",
        "true",
        "610",
        "0.00",
        "0",
    ),
    (
        "U999",
        "2026-06-06T16:00:00+03:00",
        "web",
        "internal",
        "RU",
        "staff",
        "high",
        "true",
        "false",
        "7",
        "10",
        "true",
        "120",
        "0.00",
        "0",
    ),
]

TINY_FRAME = [
    ("U001", "activation_export", "2026-06-12", "0.500000", "0.950000", "2.000000", "eligible"),
    ("U002", "activation_export", "2026-06-12", "0.500000", "0.950000", "2.000000", "eligible"),
    ("U003", "activation_export", "2026-06-12", "0.400000", "0.750000", "2.500000", "eligible"),
    ("U004", "activation_export", "2026-06-12", "0.400000", "0.550000", "2.500000", "eligible"),
    ("U005", "activation_export", "2026-06-12", "0.600000", "0.900000", "1.666667", "eligible"),
    ("U007", "activation_export", "2026-06-12", "0.400000", "0.700000", "2.500000", "eligible"),
    ("U008", "activation_export", "2026-06-12", "0.500000", "0.900000", "2.000000", "eligible"),
]

TINY_SAMPLE = [
    (
        "U001",
        "2026-06-01T09:00:00+03:00",
        "web",
        "organic",
        "RU",
        "basic",
        "high",
        "0.500000",
        "0.950000",
        "2.000000",
        "true",
        "7",
        "5",
        "true",
        "420",
        "990.00",
        "0",
    ),
    (
        "U002",
        "2026-06-01T10:10:00+03:00",
        "ios",
        "paid_search",
        "RU",
        "premium",
        "high",
        "0.500000",
        "0.950000",
        "2.000000",
        "true",
        "7",
        "4",
        "true",
        "360",
        "1490.00",
        "0",
    ),
    (
        "U003",
        "2026-06-02T11:20:00+03:00",
        "android",
        "referral",
        "KZ",
        "basic",
        "mid",
        "0.400000",
        "0.750000",
        "2.500000",
        "true",
        "7",
        "3",
        "true",
        "900",
        "0.00",
        "1",
    ),
    (
        "U004",
        "2026-06-03T12:30:00+03:00",
        "android",
        "organic",
        "AM",
        "basic",
        "low",
        "0.400000",
        "0.550000",
        "2.500000",
        "false",
        "7",
        "",
        "",
        "",
        "",
        "",
    ),
    (
        "U005",
        "2026-06-04T13:40:00+03:00",
        "web",
        "organic",
        "DE",
        "basic",
        "high",
        "0.600000",
        "0.900000",
        "1.666667",
        "true",
        "7",
        "1",
        "false",
        "520",
        "450.00",
        "0",
    ),
    (
        "U007",
        "2026-06-06T15:00:00+03:00",
        "android",
        "paid_search",
        "RU",
        "premium",
        "mid",
        "0.400000",
        "0.700000",
        "2.500000",
        "true",
        "7",
        "4",
        "true",
        "740",
        "990.00",
        "1",
    ),
]

TINY_SEGMENTS = [
    ("platform:web", "platform", "web", "0.250000", "0.850000", "0.800000"),
    ("platform:ios", "platform", "ios", "0.250000", "0.850000", "0.800000"),
    ("platform:android", "platform", "android", "0.500000", "0.850000", "0.800000"),
    ("device_tier:high", "device_tier", "high", "0.250000", "0.850000", "0.800000"),
    ("device_tier:mid", "device_tier", "mid", "0.375000", "0.850000", "0.800000"),
    ("device_tier:low", "device_tier", "low", "0.250000", "0.850000", "0.800000"),
]


def rows(columns: tuple[str, ...], values: list[tuple[str, ...]]) -> list[dict[str, str]]:
    return [dict(zip(columns, row, strict=True)) for row in values]


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
        "population_users": rows(POPULATION_COLUMNS, TINY_POPULATION),
        "sampling_frame": rows(FRAME_COLUMNS, TINY_FRAME),
        "sample_observations": rows(SAMPLE_COLUMNS, TINY_SAMPLE),
        "segment_reference": rows(SEGMENT_COLUMNS, TINY_SEGMENTS),
    }


def sample_records() -> dict[str, list[dict[str, str]]]:
    rng = random.Random(SAMPLE_SEED)
    start = datetime(2026, 6, 1, 9, tzinfo=MOSCOW)
    population: list[dict[str, str]] = []
    frame: list[dict[str, str]] = []
    sample: list[dict[str, str]] = []
    platforms = ["web", "ios", "android"]
    channels = ["organic", "paid_search", "paid_social", "referral"]
    tiers = {"web": ["high", "mid"], "ios": ["high", "mid"], "android": ["mid", "low"]}

    for index in range(1, 401):
        platform = rng.choices(platforms, weights=[0.25, 0.25, 0.50], k=1)[0]
        tier = rng.choice(tiers[platform])
        channel = rng.choice(channels)
        user_id = f"U{index:05d}"
        registered_at = start + timedelta(minutes=index * 17)
        is_low_android = platform == "android" and tier == "low"
        activated = rng.random() < (0.42 if is_low_android else 0.58)
        sessions = max(0, int(rng.gauss(3.5 if activated else 1.6, 1.0)))
        onboarding = max(120, int(rng.gauss(1050 if is_low_android else 620, 170)))
        revenue = rng.choice(["0.00", "490.00", "990.00", "1490.00"]) if activated else "0.00"
        tickets = str(rng.choice([0, 0, 0, 1, 2]) if is_low_android else rng.choice([0, 0, 0, 0, 1]))
        record = {
            "user_id": user_id,
            "registered_at": registered_at.isoformat(),
            "platform": platform,
            "acquisition_channel": channel,
            "country": rng.choice(["RU", "KZ", "AM", "DE"]),
            "plan": rng.choice(["basic", "premium"]),
            "device_tier": tier,
            "is_test_user": "false",
            "eligible_for_analysis": "true",
            "true_observed_days": "7",
            "true_sessions_7d": str(sessions),
            "true_activated_7d": str(activated).lower(),
            "true_onboarding_seconds": str(onboarding),
            "true_first_order_amount_rub": revenue,
            "true_support_tickets_7d": tickets,
        }
        population.append(record)
        if is_low_android and rng.random() < 0.45:
            continue
        inclusion = 0.35 if platform == "android" else 0.55
        response = 0.62 if is_low_android else 0.88
        frame_record = {
            "user_id": user_id,
            "frame_source": "activation_export",
            "frame_version": "2026-06-12",
            "inclusion_probability": f"{inclusion:.6f}",
            "response_probability": f"{response:.6f}",
            "sample_weight": f"{1 / inclusion:.6f}",
            "frame_reason": "eligible",
        }
        frame.append(frame_record)
        if rng.random() < inclusion:
            observed = rng.random() < response
            sample_record = {
                "user_id": user_id,
                "registered_at": record["registered_at"],
                "platform": platform,
                "acquisition_channel": channel,
                "country": record["country"],
                "plan": record["plan"],
                "device_tier": tier,
                "inclusion_probability": frame_record["inclusion_probability"],
                "response_probability": frame_record["response_probability"],
                "sample_weight": frame_record["sample_weight"],
                "outcome_observed": str(observed).lower(),
                "observed_days": "7",
                "sessions_7d": record["true_sessions_7d"] if observed else "",
                "activated_7d": record["true_activated_7d"] if observed else "",
                "onboarding_seconds": record["true_onboarding_seconds"] if observed else "",
                "first_order_amount_rub": record["true_first_order_amount_rub"] if observed else "",
                "support_tickets_7d": record["true_support_tickets_7d"] if observed else "",
            }
            sample.append(sample_record)

    segment_reference = rows(SEGMENT_COLUMNS, TINY_SEGMENTS)
    return {
        "population_users": population,
        "sampling_frame": frame,
        "sample_observations": sample,
        "segment_reference": segment_reference,
    }


def write_profile(profile: str, output_root: Path) -> None:
    records = tiny_records() if profile == "tiny" else sample_records()
    columns = {
        "population_users": POPULATION_COLUMNS,
        "sampling_frame": FRAME_COLUMNS,
        "sample_observations": SAMPLE_COLUMNS,
        "segment_reference": SEGMENT_COLUMNS,
    }
    profile_root = output_root / profile
    for table, table_records in records.items():
        write_csv(profile_root / f"{table}.csv", columns[table], table_records)
    manifest = {
        "profile": profile,
        "seed": SAMPLE_SEED if profile == "sample" else None,
        "files": {},
        "rows": {table: len(table_records) for table, table_records in records.items()},
    }
    for table in records:
        path = profile_root / f"{table}.csv"
        manifest["files"][f"{table}.csv"] = {"sha256": checksum(path)}
    (profile_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic phase 09 data")
    parser.add_argument("--profile", choices=["tiny", "sample", "all"], default="tiny")
    parser.add_argument("--output-root", type=Path, default=ROOT)
    args = parser.parse_args()
    profiles = ["tiny", "sample"] if args.profile == "all" else [args.profile]
    for profile in profiles:
        write_profile(profile, args.output_root)
    print(f"Generated phase 09 profiles: {', '.join(profiles)}")


if __name__ == "__main__":
    main()
