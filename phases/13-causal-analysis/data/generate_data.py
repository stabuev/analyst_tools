from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SAMPLE_SEED = 20_260_625
MOSCOW = timezone(timedelta(hours=3))
PROGRAM_ID = "assisted_onboarding_v1"
CUTOFF = 60

USERS_COLUMNS = (
    "user_id",
    "registered_at",
    "platform",
    "device_tier",
    "acquisition_channel",
    "region_id",
    "language",
    "is_test_user",
    "eligible_for_program",
)
BASELINE_COLUMNS = (
    "user_id",
    "time_zero",
    "friction_score",
    "network_quality",
    "app_crashes_before_time_zero",
    "onboarding_steps_before_time_zero",
    "sessions_before_time_zero",
    "specialist_capacity",
    "activation_14d_pre",
    "signup_cohort",
)
ASSISTANCE_COLUMNS = (
    "program_id",
    "user_id",
    "time_zero",
    "friction_score",
    "eligibility_cutoff",
    "offered_assistance",
    "received_assistance",
    "offered_at",
    "started_at",
    "region_id",
    "specialist_capacity",
    "assignment_reason",
)
OUTCOME_COLUMNS = (
    "user_id",
    "activation_14d",
    "paid_subscription_30d",
    "cancelled_subscription_30d",
    "refund_amount_30d",
    "support_minutes_14d",
    "onboarding_completed_48h",
    "opened_support_chat_after_offer",
    "telemetry_complete_30d",
    "followup_end_at",
)
ENCOURAGEMENT_COLUMNS = (
    "encouragement_id",
    "user_id",
    "encouraged",
    "assigned_at",
    "instrument_version",
)
ROLLOUT_COLUMNS = (
    "region_id",
    "rollout_version",
    "rollout_start",
    "rollout_end",
    "eligibility_rule",
)
PANEL_COLUMNS = (
    "region_id",
    "week_start",
    "rollout_active",
    "eligible_users",
    "assisted_users",
    "activation_rate_14d",
    "paid_subscription_rate_30d",
    "mean_friction_score",
)
SCENARIO_COLUMNS = (
    "scenario_id",
    "design",
    "treatment",
    "outcome",
    "estimand",
    "unit",
    "identification_strategy",
)


def boolean(value: bool) -> str:
    return str(value).lower()


def logistic(value: float) -> float:
    return 1 / (1 + math.exp(-value))


def rows(columns: tuple[str, ...], values: list[tuple[Any, ...]]) -> list[dict[str, str]]:
    return [
        {column: str(value) for column, value in zip(columns, record, strict=True)}
        for record in values
    ]


def tiny_records() -> dict[str, list[dict[str, str]]]:
    registered = [
        "2026-07-01T09:00:00+03:00",
        "2026-07-01T09:20:00+03:00",
        "2026-07-02T10:00:00+03:00",
        "2026-07-02T10:30:00+03:00",
        "2026-07-03T11:00:00+03:00",
        "2026-07-03T11:30:00+03:00",
        "2026-07-04T12:00:00+03:00",
        "2026-07-04T12:30:00+03:00",
        "2026-07-05T13:00:00+03:00",
        "2026-07-05T13:30:00+03:00",
        "2026-07-06T14:00:00+03:00",
        "2026-07-06T14:30:00+03:00",
        "2026-07-06T15:00:00+03:00",
    ]
    users = rows(
        USERS_COLUMNS,
        [
            (
                "U001",
                registered[0],
                "android",
                "low",
                "paid_social",
                "north",
                "ru",
                "false",
                "true",
            ),
            ("U002", registered[1], "android", "low", "organic", "north", "ru", "false", "true"),
            ("U003", registered[2], "ios", "mid", "paid_search", "north", "ru", "false", "true"),
            ("U004", registered[3], "android", "mid", "referral", "south", "ru", "false", "true"),
            ("U005", registered[4], "web", "high", "organic", "north", "en", "false", "true"),
            (
                "U006",
                registered[5],
                "android",
                "low",
                "paid_social",
                "south",
                "ru",
                "false",
                "true",
            ),
            ("U007", registered[6], "ios", "mid", "organic", "south", "ru", "false", "true"),
            ("U008", registered[7], "web", "high", "referral", "north", "en", "false", "true"),
            ("U009", registered[8], "ios", "high", "organic", "south", "ru", "false", "true"),
            (
                "U010",
                registered[9],
                "android",
                "mid",
                "paid_search",
                "north",
                "ru",
                "false",
                "true",
            ),
            ("U011", registered[10], "web", "mid", "organic", "south", "en", "false", "true"),
            ("U012", registered[11], "android", "low", "referral", "north", "ru", "false", "true"),
            ("U999", registered[12], "web", "high", "internal", "north", "ru", "true", "false"),
        ],
    )
    scores = [82, 76, 71, 66, 61, 58, 55, 49, 45, 73, 64, 52, 90]
    capacities = [2, 2, 2, 1, 2, 1, 1, 2, 1, 2, 1, 2, 3]
    baseline_values: list[tuple[Any, ...]] = []
    for index, user in enumerate(users):
        time_zero = datetime.fromisoformat(user["registered_at"]) + timedelta(hours=1)
        baseline_values.append(
            (
                user["user_id"],
                time_zero.isoformat(),
                scores[index],
                ["poor", "fair", "good"][index % 3],
                [3, 2, 1, 2, 0, 3, 1, 0, 0, 2, 1, 2, 0][index],
                [1, 2, 3, 2, 4, 2, 3, 5, 5, 2, 3, 2, 6][index],
                [0, 1, 1, 0, 2, 0, 1, 3, 2, 1, 2, 0, 5][index],
                capacities[index],
                boolean(
                    [
                        False,
                        False,
                        True,
                        False,
                        True,
                        False,
                        True,
                        True,
                        True,
                        False,
                        True,
                        False,
                        True,
                    ][index]
                ),
                time_zero.date().isoformat(),
            )
        )
    baseline = rows(BASELINE_COLUMNS, baseline_values)

    received = [True, True, True, True, False, True, False, False, False, True, False, False, False]
    offered = [True, True, True, True, True, True, False, False, False, True, True, False, False]
    reasons = [
        "score_threshold",
        "score_threshold",
        "score_threshold",
        "score_threshold",
        "score_threshold_capacity_full",
        "manual_override",
        "below_cutoff",
        "below_target_population",
        "below_target_population",
        "score_threshold",
        "score_threshold_capacity_full",
        "below_cutoff",
        "test_user_excluded",
    ]
    assistance_values: list[tuple[Any, ...]] = []
    for index, user in enumerate(users):
        time_zero = datetime.fromisoformat(baseline[index]["time_zero"])
        offered_at = time_zero + timedelta(minutes=15) if offered[index] else ""
        started_at = time_zero + timedelta(hours=4 + index % 6) if received[index] else ""
        assistance_values.append(
            (
                PROGRAM_ID,
                user["user_id"],
                time_zero.isoformat(),
                scores[index],
                CUTOFF,
                boolean(offered[index]),
                boolean(received[index]),
                offered_at.isoformat() if offered_at else "",
                started_at.isoformat() if started_at else "",
                user["region_id"],
                capacities[index],
                reasons[index],
            )
        )
    assistance = rows(ASSISTANCE_COLUMNS, assistance_values)

    activation = [True, True, False, False, True, True, True, True, True, True, False, True, True]
    paid = [True, True, False, False, True, False, True, True, False, True, False, False, True]
    outcome_values: list[tuple[Any, ...]] = []
    for index, user in enumerate(users):
        time_zero = datetime.fromisoformat(baseline[index]["time_zero"])
        completed = activation[index] or received[index]
        opened_chat = offered[index] and (not activation[index] or scores[index] >= 70)
        outcome_values.append(
            (
                user["user_id"],
                boolean(activation[index]),
                boolean(paid[index]),
                boolean(index in {3, 10}),
                "490.00" if index == 3 else "0.00",
                [15, 10, 45, 60, 0, 35, 5, 0, 0, 20, 25, 10, 0][index],
                boolean(completed),
                boolean(opened_chat),
                "true",
                (time_zero + timedelta(days=30)).isoformat(),
            )
        )
    outcomes = rows(OUTCOME_COLUMNS, outcome_values)

    target_ids = ["U001", "U002", "U003", "U004", "U005", "U006", "U007", "U010", "U011", "U012"]
    encouraged_ids = {"U001", "U002", "U003", "U005", "U010"}
    encouragement_values = []
    baseline_by_id = {row["user_id"]: row for row in baseline}
    for index, user_id in enumerate(target_ids, start=1):
        assigned_at = datetime.fromisoformat(baseline_by_id[user_id]["time_zero"]) - timedelta(
            minutes=10
        )
        encouragement_values.append(
            (
                f"ENC{index:03d}",
                user_id,
                boolean(user_id in encouraged_ids),
                assigned_at.isoformat(),
                "capacity_lottery_v1",
            )
        )
    encouragement = rows(ENCOURAGEMENT_COLUMNS, encouragement_values)

    rollout = rows(
        ROLLOUT_COLUMNS,
        [
            ("north", "north_wave_1", "2026-07-06", "2026-12-31", "friction_score >= 60"),
            ("south", "south_wave_1", "2026-07-20", "2026-12-31", "friction_score >= 60"),
        ],
    )
    panel_values: list[tuple[Any, ...]] = []
    starts = [date(2026, 6, 15) + timedelta(days=7 * index) for index in range(8)]
    for region in ("north", "south"):
        rollout_start = date(2026, 7, 6) if region == "north" else date(2026, 7, 20)
        for index, week_start in enumerate(starts):
            active = week_start >= rollout_start
            baseline_rate = 0.44 + 0.01 * index + (0.02 if region == "north" else 0.0)
            treatment_lift = 0.08 if active else 0.0
            panel_values.append(
                (
                    region,
                    week_start.isoformat(),
                    boolean(active),
                    50 + index * 2,
                    (18 + index) if active else 0,
                    f"{baseline_rate + treatment_lift:.6f}",
                    f"{0.18 + 0.005 * index + (0.04 if active else 0):.6f}",
                    f"{63 + (2 if region == 'north' else -1) + index * 0.2:.2f}",
                )
            )
    panel = rows(PANEL_COLUMNS, panel_values)
    scenarios = rows(
        SCENARIO_COLUMNS,
        [
            (
                "adjustment_ate",
                "backdoor_adjustment",
                "received_assistance",
                "activation_14d",
                "ATE",
                "user_id",
                "conditional_exchangeability",
            ),
            (
                "regional_did",
                "difference_in_differences",
                "rollout_active",
                "activation_rate_14d",
                "ATT",
                "region_week",
                "parallel_trends",
            ),
            (
                "score_rdd",
                "regression_discontinuity",
                "offered_assistance",
                "activation_14d",
                "local_ATE",
                "user_id",
                "continuity_at_cutoff",
            ),
            (
                "capacity_iv",
                "instrumental_variables",
                "received_assistance",
                "activation_14d",
                "LATE",
                "user_id",
                "encouragement_as_instrument",
            ),
        ],
    )
    return {
        "users": users,
        "pre_treatment_behavior": baseline,
        "onboarding_assistance": assistance,
        "outcomes": outcomes,
        "encouragement_assignments": encouragement,
        "rollout_calendar": rollout,
        "region_week_panel": panel,
        "causal_scenarios": scenarios,
    }


def sample_records(user_count: int = 2000) -> dict[str, list[dict[str, str]]]:
    if user_count < 100:
        raise ValueError("sample profile requires at least 100 users")
    rng = random.Random(SAMPLE_SEED)
    regions = {
        "north": date(2026, 7, 6),
        "south": date(2026, 7, 20),
        "east": date(2026, 8, 3),
        "west": date(2026, 8, 17),
    }
    users: list[dict[str, str]] = []
    baseline: list[dict[str, str]] = []
    assistance: list[dict[str, str]] = []
    outcomes: list[dict[str, str]] = []
    encouragement: list[dict[str, str]] = []
    weekly: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
    start = datetime(2026, 6, 15, 9, tzinfo=MOSCOW)

    for index in range(1, user_count + 1):
        user_id = f"U{index:05d}"
        region = rng.choice(list(regions))
        platform = rng.choices(["android", "ios", "web"], weights=[0.5, 0.25, 0.25], k=1)[0]
        device_tier = rng.choices(["low", "mid", "high"], weights=[0.35, 0.45, 0.2], k=1)[0]
        registered_at = start + timedelta(minutes=index * 95)
        time_zero = registered_at + timedelta(hours=1)
        week_start = time_zero.date() - timedelta(days=time_zero.weekday())
        latent_motivation = rng.gauss(0, 1)
        friction = int(
            min(
                99,
                max(
                    5,
                    rng.gauss(58, 13)
                    + (10 if platform == "android" else 0)
                    + (8 if device_tier == "low" else 0)
                    - 4 * latent_motivation,
                ),
            )
        )
        capacity = rng.choice([0, 1, 1, 2, 2, 3])
        rollout_active = time_zero.date() >= regions[region]
        encouraged = friction >= 50 and rng.random() < 0.5
        offer_probability = logistic(
            -3.0 + 0.055 * friction + 0.45 * capacity + 1.0 * rollout_active + 0.6 * encouraged
        )
        offered = rng.random() < offer_probability and friction >= 45
        receive_probability = logistic(-0.8 + 0.7 * offered + 0.5 * encouraged + 0.2 * capacity)
        received = offered and rng.random() < receive_probability
        offered_at = time_zero + timedelta(minutes=rng.randint(5, 90)) if offered else None
        started_at = time_zero + timedelta(hours=rng.randint(2, 22)) if received else None

        base_logit = (
            -0.2
            + 0.75 * latent_motivation
            - 0.025 * (friction - 55)
            + (0.25 if platform == "web" else 0)
            - (0.25 if device_tier == "low" else 0)
        )
        treatment_effect_logit = 0.85 + 0.008 * max(0, friction - 60)
        p0 = logistic(base_logit)
        p1 = logistic(base_logit + treatment_effect_logit)
        activation = rng.random() < (p1 if received else p0)
        paid_probability = logistic(
            -1.6 + 1.35 * activation + 0.3 * latent_motivation + 0.3 * received
        )
        paid = rng.random() < paid_probability
        completed = rng.random() < logistic(-0.3 + 1.1 * received + 0.5 * latent_motivation)
        opened_chat = rng.random() < logistic(-1.5 + 0.9 * received + 0.025 * friction)
        telemetry_complete = rng.random() < logistic(3.0 - 0.018 * friction + 0.25 * received)

        users.append(
            {
                "user_id": user_id,
                "registered_at": registered_at.isoformat(),
                "platform": platform,
                "device_tier": device_tier,
                "acquisition_channel": rng.choice(
                    ["organic", "paid_search", "paid_social", "referral"]
                ),
                "region_id": region,
                "language": rng.choice(["ru", "ru", "ru", "en"]),
                "is_test_user": "false",
                "eligible_for_program": "true",
            }
        )
        baseline.append(
            {
                "user_id": user_id,
                "time_zero": time_zero.isoformat(),
                "friction_score": str(friction),
                "network_quality": rng.choice(["poor", "fair", "good"]),
                "app_crashes_before_time_zero": str(
                    max(0, int(rng.gauss(1.2 + friction / 60, 1.1)))
                ),
                "onboarding_steps_before_time_zero": str(rng.randint(0, 5)),
                "sessions_before_time_zero": str(rng.randint(0, 3)),
                "specialist_capacity": str(capacity),
                "activation_14d_pre": boolean(
                    rng.random() < logistic(-0.6 + 0.4 * latent_motivation)
                ),
                "signup_cohort": time_zero.date().isoformat(),
            }
        )
        assistance.append(
            {
                "program_id": PROGRAM_ID,
                "user_id": user_id,
                "time_zero": time_zero.isoformat(),
                "friction_score": str(friction),
                "eligibility_cutoff": str(CUTOFF),
                "offered_assistance": boolean(offered),
                "received_assistance": boolean(received),
                "offered_at": offered_at.isoformat() if offered_at else "",
                "started_at": started_at.isoformat() if started_at else "",
                "region_id": region,
                "specialist_capacity": str(capacity),
                "assignment_reason": (
                    "score_threshold"
                    if friction >= CUTOFF and offered
                    else "manual_or_capacity_rule"
                    if offered
                    else "not_offered"
                ),
            }
        )
        outcomes.append(
            {
                "user_id": user_id,
                "activation_14d": boolean(activation),
                "paid_subscription_30d": boolean(paid),
                "cancelled_subscription_30d": boolean(paid and rng.random() < 0.08),
                "refund_amount_30d": f"{490.0 if paid and rng.random() < 0.04 else 0.0:.2f}",
                "support_minutes_14d": str(
                    max(0, int(rng.gauss(5 + friction / 3 + 8 * received, 12)))
                ),
                "onboarding_completed_48h": boolean(completed),
                "opened_support_chat_after_offer": boolean(opened_chat),
                "telemetry_complete_30d": boolean(telemetry_complete),
                "followup_end_at": (time_zero + timedelta(days=30)).isoformat(),
            }
        )
        if friction >= 50:
            encouragement.append(
                {
                    "encouragement_id": f"ENC{index:05d}",
                    "user_id": user_id,
                    "encouraged": boolean(encouraged),
                    "assigned_at": (time_zero - timedelta(minutes=10)).isoformat(),
                    "instrument_version": "capacity_lottery_v1",
                }
            )
        weekly[(region, week_start)].append(
            {
                "eligible": friction >= 50,
                "received": received,
                "activation": activation,
                "paid": paid,
                "friction": friction,
                "rollout_active": rollout_active,
            }
        )

    panel: list[dict[str, str]] = []
    for (region, week_start), records in sorted(weekly.items()):
        eligible_records = [record for record in records if record["eligible"]]
        denominator = len(eligible_records)
        panel.append(
            {
                "region_id": region,
                "week_start": week_start.isoformat(),
                "rollout_active": boolean(week_start >= regions[region]),
                "eligible_users": str(denominator),
                "assisted_users": str(sum(record["received"] for record in eligible_records)),
                "activation_rate_14d": (
                    f"{sum(record['activation'] for record in eligible_records) / denominator:.6f}"
                    if denominator
                    else ""
                ),
                "paid_subscription_rate_30d": (
                    f"{sum(record['paid'] for record in eligible_records) / denominator:.6f}"
                    if denominator
                    else ""
                ),
                "mean_friction_score": (
                    f"{sum(record['friction'] for record in eligible_records) / denominator:.2f}"
                    if denominator
                    else ""
                ),
            }
        )
    rollout = [
        {
            "region_id": region,
            "rollout_version": f"{region}_wave_1",
            "rollout_start": rollout_start.isoformat(),
            "rollout_end": "2026-12-31",
            "eligibility_rule": "friction_score >= 60",
        }
        for region, rollout_start in regions.items()
    ]
    scenarios = tiny_records()["causal_scenarios"]
    return {
        "users": users,
        "pre_treatment_behavior": baseline,
        "onboarding_assistance": assistance,
        "outcomes": outcomes,
        "encouragement_assignments": encouragement,
        "rollout_calendar": rollout,
        "region_week_panel": panel,
        "causal_scenarios": scenarios,
    }


def write_csv(path: Path, fieldnames: tuple[str, ...], records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_profile(profile: str, output_root: Path, sample_users: int) -> None:
    records = tiny_records() if profile == "tiny" else sample_records(sample_users)
    columns = {
        "users": USERS_COLUMNS,
        "pre_treatment_behavior": BASELINE_COLUMNS,
        "onboarding_assistance": ASSISTANCE_COLUMNS,
        "outcomes": OUTCOME_COLUMNS,
        "encouragement_assignments": ENCOURAGEMENT_COLUMNS,
        "rollout_calendar": ROLLOUT_COLUMNS,
        "region_week_panel": PANEL_COLUMNS,
        "causal_scenarios": SCENARIO_COLUMNS,
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
        manifest["files"][path.name] = {"sha256": checksum(path)}
    (profile_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic phase 13 causal data")
    parser.add_argument("--profile", choices=["tiny", "sample", "all"], default="tiny")
    parser.add_argument("--output-root", type=Path, default=ROOT)
    parser.add_argument("--sample-users", type=int, default=2000)
    args = parser.parse_args()
    profiles = ["tiny", "sample"] if args.profile == "all" else [args.profile]
    for profile in profiles:
        write_profile(profile, args.output_root, args.sample_users)
    print(f"Generated phase 13 profiles: {', '.join(profiles)}")


if __name__ == "__main__":
    main()
