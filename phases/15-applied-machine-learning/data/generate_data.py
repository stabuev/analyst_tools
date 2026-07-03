from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


SNAPSHOT_ROWS = [
    # snapshot, user, prediction time, trial end, segment, plan, country, platform,
    # eligible, split group, churn label, split role, split order
    (
        "S001",
        "U001",
        "2026-05-10T09:00:00+03:00",
        "2026-05-17T09:00:00+03:00",
        "android_ru",
        "trial_basic",
        "RU",
        "android",
        True,
        "cohort_2026w19",
        True,
        "train",
        1,
    ),
    (
        "S002",
        "U002",
        "2026-05-10T09:00:00+03:00",
        "2026-05-17T09:00:00+03:00",
        "ios_ru",
        "trial_basic",
        "RU",
        "ios",
        True,
        "cohort_2026w19",
        False,
        "train",
        1,
    ),
    (
        "S003",
        "U003",
        "2026-05-10T09:00:00+03:00",
        "2026-05-17T09:00:00+03:00",
        "web_kz",
        "trial_pro",
        "KZ",
        "web",
        True,
        "cohort_2026w19",
        False,
        "train",
        1,
    ),
    (
        "S004",
        "U004",
        "2026-05-10T09:00:00+03:00",
        "2026-05-17T09:00:00+03:00",
        "android_ru",
        "trial_basic",
        "RU",
        "android",
        True,
        "cohort_2026w19",
        True,
        "train",
        1,
    ),
    (
        "S005",
        "U005",
        "2026-05-17T09:00:00+03:00",
        "2026-05-24T09:00:00+03:00",
        "ios_ru",
        "trial_basic",
        "RU",
        "ios",
        True,
        "cohort_2026w20",
        False,
        "validation",
        2,
    ),
    (
        "S006",
        "U006",
        "2026-05-17T09:00:00+03:00",
        "2026-05-24T09:00:00+03:00",
        "web_ru",
        "trial_pro",
        "RU",
        "web",
        True,
        "cohort_2026w20",
        True,
        "validation",
        2,
    ),
    (
        "S007",
        "U007",
        "2026-05-17T09:00:00+03:00",
        "2026-05-24T09:00:00+03:00",
        "android_kz",
        "trial_basic",
        "KZ",
        "android",
        True,
        "cohort_2026w20",
        False,
        "validation",
        2,
    ),
    (
        "S008",
        "U008",
        "2026-05-17T09:00:00+03:00",
        "2026-05-24T09:00:00+03:00",
        "ios_ru",
        "trial_basic",
        "RU",
        "ios",
        False,
        "cohort_2026w20",
        False,
        "exclude",
        0,
    ),
    (
        "S009",
        "U009",
        "2026-05-24T09:00:00+03:00",
        "2026-05-31T09:00:00+03:00",
        "android_ru",
        "trial_basic",
        "RU",
        "android",
        True,
        "cohort_2026w21",
        False,
        "test",
        3,
    ),
    (
        "S010",
        "U010",
        "2026-05-24T09:00:00+03:00",
        "2026-05-31T09:00:00+03:00",
        "ios_ru",
        "trial_basic",
        "RU",
        "ios",
        True,
        "cohort_2026w21",
        True,
        "test",
        3,
    ),
    (
        "S011",
        "U011",
        "2026-05-24T09:00:00+03:00",
        "2026-05-31T09:00:00+03:00",
        "web_kz",
        "trial_pro",
        "KZ",
        "web",
        True,
        "cohort_2026w21",
        False,
        "test",
        3,
    ),
    (
        "S012",
        "U012",
        "2026-05-24T09:00:00+03:00",
        "2026-05-31T09:00:00+03:00",
        "android_kz",
        "trial_basic",
        "KZ",
        "android",
        True,
        "cohort_2026w21",
        False,
        "test",
        3,
    ),
    (
        "S013",
        "U013",
        "2026-05-24T09:00:00+03:00",
        "2026-05-31T09:00:00+03:00",
        "web_ru",
        "trial_pro",
        "RU",
        "web",
        True,
        "cohort_2026w21",
        False,
        "test",
        3,
    ),
]


ROLE_BY_SPLIT = {
    "train": "fit_preprocessing_and_estimator",
    "validation": "model_selection_and_threshold_selection",
    "test": "final_once_only_evaluation",
}


SCORE_BY_SNAPSHOT = {
    "S001": 0.65,
    "S002": 0.45,
    "S003": 0.35,
    "S004": 0.58,
    "S005": 0.74,
    "S006": 0.60,
    "S007": 0.30,
    "S009": 0.61,
    "S010": 0.66,
    "S011": 0.40,
    "S012": 0.30,
    "S013": 0.20,
}


def label_observed_at(prediction_time: str) -> str:
    if prediction_time.startswith("2026-05-10"):
        return "2026-05-24T12:00:00+03:00"
    if prediction_time.startswith("2026-05-17"):
        return "2026-05-31T12:00:00+03:00"
    return "2026-06-07T12:00:00+03:00"


SNAPSHOTS = [
    {
        "snapshot_id": snapshot_id,
        "user_id": user_id,
        "prediction_time": prediction_time,
        "trial_end_at": trial_end_at,
        "segment_id": segment_id,
        "plan_id": plan_id,
        "country": country,
        "platform": platform,
        "eligible_for_offer": str(eligible).lower(),
        "days_until_trial_end": 7,
        "split_group": split_group,
    }
    for (
        snapshot_id,
        user_id,
        prediction_time,
        trial_end_at,
        segment_id,
        plan_id,
        country,
        platform,
        eligible,
        split_group,
        _churned,
        _split,
        _split_order,
    ) in SNAPSHOT_ROWS
]


LABELS = [
    {
        "snapshot_id": snapshot_id,
        "target_name": "churn_14d",
        "label_observed_at": label_observed_at(prediction_time),
        "churned_14d": str(churned).lower(),
        "label_window_complete": "true",
    }
    for (
        snapshot_id,
        _user_id,
        prediction_time,
        _trial_end_at,
        _segment_id,
        _plan_id,
        _country,
        _platform,
        _eligible,
        _split_group,
        churned,
        _split,
        _split_order,
    ) in SNAPSHOT_ROWS
]


SPLIT_MANIFEST = [
    {
        "snapshot_id": snapshot_id,
        "user_id": user_id,
        "prediction_time": prediction_time,
        "split": split,
        "split_order": split_order,
        "role": ROLE_BY_SPLIT[split],
        "assigned_by_policy": "chronological_group_holdout",
    }
    for (
        snapshot_id,
        user_id,
        prediction_time,
        _trial_end_at,
        _segment_id,
        _plan_id,
        _country,
        _platform,
        eligible,
        _split_group,
        _churned,
        split,
        split_order,
    ) in SNAPSHOT_ROWS
    if eligible
]


CV_FOLD_ROWS = [
    {
        "fold_id": "cv_fold_1",
        "fold_order": 1,
        "snapshot_id": "S001",
        "user_id": "U001",
        "prediction_time": "2026-05-10T09:00:00+03:00",
        "original_split": "train",
        "cv_role": "cv_train",
        "group_key": "U001",
        "label": "true",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
    {
        "fold_id": "cv_fold_1",
        "fold_order": 1,
        "snapshot_id": "S002",
        "user_id": "U002",
        "prediction_time": "2026-05-10T09:00:00+03:00",
        "original_split": "train",
        "cv_role": "cv_train",
        "group_key": "U002",
        "label": "false",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
    {
        "fold_id": "cv_fold_1",
        "fold_order": 1,
        "snapshot_id": "S003",
        "user_id": "U003",
        "prediction_time": "2026-05-10T09:00:00+03:00",
        "original_split": "train",
        "cv_role": "cv_validation",
        "group_key": "U003",
        "label": "false",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
    {
        "fold_id": "cv_fold_1",
        "fold_order": 1,
        "snapshot_id": "S004",
        "user_id": "U004",
        "prediction_time": "2026-05-10T09:00:00+03:00",
        "original_split": "train",
        "cv_role": "cv_validation",
        "group_key": "U004",
        "label": "true",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
    {
        "fold_id": "cv_fold_2",
        "fold_order": 2,
        "snapshot_id": "S001",
        "user_id": "U001",
        "prediction_time": "2026-05-10T09:00:00+03:00",
        "original_split": "train",
        "cv_role": "cv_train",
        "group_key": "U001",
        "label": "true",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
    {
        "fold_id": "cv_fold_2",
        "fold_order": 2,
        "snapshot_id": "S002",
        "user_id": "U002",
        "prediction_time": "2026-05-10T09:00:00+03:00",
        "original_split": "train",
        "cv_role": "cv_train",
        "group_key": "U002",
        "label": "false",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
    {
        "fold_id": "cv_fold_2",
        "fold_order": 2,
        "snapshot_id": "S003",
        "user_id": "U003",
        "prediction_time": "2026-05-10T09:00:00+03:00",
        "original_split": "train",
        "cv_role": "cv_train",
        "group_key": "U003",
        "label": "false",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
    {
        "fold_id": "cv_fold_2",
        "fold_order": 2,
        "snapshot_id": "S004",
        "user_id": "U004",
        "prediction_time": "2026-05-10T09:00:00+03:00",
        "original_split": "train",
        "cv_role": "cv_train",
        "group_key": "U004",
        "label": "true",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
    {
        "fold_id": "cv_fold_2",
        "fold_order": 2,
        "snapshot_id": "S005",
        "user_id": "U005",
        "prediction_time": "2026-05-17T09:00:00+03:00",
        "original_split": "validation",
        "cv_role": "cv_validation",
        "group_key": "U005",
        "label": "false",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
    {
        "fold_id": "cv_fold_2",
        "fold_order": 2,
        "snapshot_id": "S006",
        "user_id": "U006",
        "prediction_time": "2026-05-17T09:00:00+03:00",
        "original_split": "validation",
        "cv_role": "cv_validation",
        "group_key": "U006",
        "label": "true",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
    {
        "fold_id": "cv_fold_2",
        "fold_order": 2,
        "snapshot_id": "S007",
        "user_id": "U007",
        "prediction_time": "2026-05-17T09:00:00+03:00",
        "original_split": "validation",
        "cv_role": "cv_validation",
        "group_key": "U007",
        "label": "false",
        "assigned_by_policy": "predeclared_time_ordered_group_cv",
    },
]


SCORES = [
    {
        "snapshot_id": snapshot_id,
        "model_id": "candidate_risk_score_v0",
        "score": f"{SCORE_BY_SNAPSHOT[snapshot_id]:.2f}",
        "score_type": "churn_risk_probability",
        "trained_on_split": "train",
        "generated_at": "2026-06-08T09:00:00+03:00",
    }
    for (
        snapshot_id,
        _user_id,
        _prediction_time,
        _trial_end_at,
        _segment_id,
        _plan_id,
        _country,
        _platform,
        eligible,
        _split_group,
        _churned,
        _split,
        _split_order,
    ) in SNAPSHOT_ROWS
    if eligible
]


RAW_FEATURES = [
    {
        "snapshot_id": "S001",
        "sessions_14d": "8",
        "active_days_14d": "5",
        "support_tickets_14d": "0",
        "revenue_30d": "0",
        "days_since_signup": "6",
        "had_support_ticket_14d": "0",
        "plan_id": "trial_basic",
        "platform": "android",
        "country": "RU",
        "acquisition_channel": "organic",
    },
    {
        "snapshot_id": "S002",
        "sessions_14d": "4",
        "active_days_14d": "3",
        "support_tickets_14d": "1",
        "revenue_30d": "",
        "days_since_signup": "10",
        "had_support_ticket_14d": "1",
        "plan_id": "trial_basic",
        "platform": "ios",
        "country": "RU",
        "acquisition_channel": "paid_search",
    },
    {
        "snapshot_id": "S003",
        "sessions_14d": "2",
        "active_days_14d": "1",
        "support_tickets_14d": "0",
        "revenue_30d": "990",
        "days_since_signup": "4",
        "had_support_ticket_14d": "0",
        "plan_id": "trial_pro",
        "platform": "web",
        "country": "KZ",
        "acquisition_channel": "organic",
    },
    {
        "snapshot_id": "S004",
        "sessions_14d": "",
        "active_days_14d": "2",
        "support_tickets_14d": "2",
        "revenue_30d": "0",
        "days_since_signup": "8",
        "had_support_ticket_14d": "1",
        "plan_id": "trial_basic",
        "platform": "android",
        "country": "RU",
        "acquisition_channel": "referral",
    },
    {
        "snapshot_id": "S005",
        "sessions_14d": "5",
        "active_days_14d": "4",
        "support_tickets_14d": "0",
        "revenue_30d": "0",
        "days_since_signup": "7",
        "had_support_ticket_14d": "0",
        "plan_id": "trial_basic",
        "platform": "ios",
        "country": "RU",
        "acquisition_channel": "organic",
    },
    {
        "snapshot_id": "S006",
        "sessions_14d": "1",
        "active_days_14d": "",
        "support_tickets_14d": "3",
        "revenue_30d": "1290",
        "days_since_signup": "5",
        "had_support_ticket_14d": "1",
        "plan_id": "trial_pro",
        "platform": "web",
        "country": "RU",
        "acquisition_channel": "influencer",
    },
    {
        "snapshot_id": "S007",
        "sessions_14d": "9",
        "active_days_14d": "6",
        "support_tickets_14d": "0",
        "revenue_30d": "0",
        "days_since_signup": "11",
        "had_support_ticket_14d": "0",
        "plan_id": "trial_basic",
        "platform": "android",
        "country": "KZ",
        "acquisition_channel": "",
    },
    {
        "snapshot_id": "S009",
        "sessions_14d": "6",
        "active_days_14d": "4",
        "support_tickets_14d": "0",
        "revenue_30d": "0",
        "days_since_signup": "12",
        "had_support_ticket_14d": "0",
        "plan_id": "trial_basic",
        "platform": "android",
        "country": "RU",
        "acquisition_channel": "organic",
    },
    {
        "snapshot_id": "S010",
        "sessions_14d": "2",
        "active_days_14d": "1",
        "support_tickets_14d": "2",
        "revenue_30d": "0",
        "days_since_signup": "6",
        "had_support_ticket_14d": "1",
        "plan_id": "trial_basic",
        "platform": "ios",
        "country": "RU",
        "acquisition_channel": "partnership",
    },
    {
        "snapshot_id": "S011",
        "sessions_14d": "3",
        "active_days_14d": "2",
        "support_tickets_14d": "1",
        "revenue_30d": "1490",
        "days_since_signup": "5",
        "had_support_ticket_14d": "1",
        "plan_id": "trial_pro",
        "platform": "web",
        "country": "KZ",
        "acquisition_channel": "organic",
    },
    {
        "snapshot_id": "S012",
        "sessions_14d": "",
        "active_days_14d": "3",
        "support_tickets_14d": "0",
        "revenue_30d": "0",
        "days_since_signup": "9",
        "had_support_ticket_14d": "0",
        "plan_id": "trial_basic",
        "platform": "android",
        "country": "KZ",
        "acquisition_channel": "referral",
    },
    {
        "snapshot_id": "S013",
        "sessions_14d": "7",
        "active_days_14d": "5",
        "support_tickets_14d": "",
        "revenue_30d": "1290",
        "days_since_signup": "4",
        "had_support_ticket_14d": "0",
        "plan_id": "trial_pro",
        "platform": "web",
        "country": "RU",
        "acquisition_channel": "paid_search",
    },
]


FEATURE_SOURCES = [
    {
        "source_id": "user_profile",
        "source_table": "ml_users",
        "timing": "known_before_prediction_time",
        "available_at_policy": "created_at <= prediction_time",
        "max_observed_at": "",
        "allowed": "true",
        "reason": "stable account attributes known before scoring",
    },
    {
        "source_id": "subscription_snapshot",
        "source_table": "ml_scoring_snapshots",
        "timing": "known_before_prediction_time",
        "available_at_policy": "snapshot fields are materialized at prediction_time",
        "max_observed_at": "2026-05-10T09:00:00+03:00",
        "allowed": "true",
        "reason": "trial status at the scoring moment",
    },
    {
        "source_id": "events_lookback_14d",
        "source_table": "ml_events",
        "timing": "lookback_before_prediction_time",
        "available_at_policy": "event_time < prediction_time and ingested before scoring",
        "max_observed_at": "2026-05-10T08:40:00+03:00",
        "allowed": "true",
        "reason": "past product activity only",
    },
    {
        "source_id": "orders_lookback_30d",
        "source_table": "ml_orders",
        "timing": "lookback_before_prediction_time",
        "available_at_policy": "order_paid_at < prediction_time",
        "max_observed_at": "2026-05-09T21:15:00+03:00",
        "allowed": "true",
        "reason": "past purchase behavior only",
    },
    {
        "source_id": "support_tickets_before_prediction",
        "source_table": "ml_support_tickets",
        "timing": "lookback_before_prediction_time",
        "available_at_policy": "ticket_created_at < prediction_time",
        "max_observed_at": "2026-05-10T08:10:00+03:00",
        "allowed": "true",
        "reason": "support history before the scoring moment",
    },
    {
        "source_id": "calendar_trial_end",
        "source_table": "calendar",
        "timing": "known_before_prediction_time",
        "available_at_policy": "trial_end_at is known at account creation",
        "max_observed_at": "",
        "allowed": "true",
        "reason": "calendar fact known before scoring",
    },
    {
        "source_id": "cancellation_events_after_prediction",
        "source_table": "ml_events",
        "timing": "post_prediction_time",
        "available_at_policy": "event_time >= prediction_time",
        "max_observed_at": "2026-06-02T10:00:00+03:00",
        "allowed": "false",
        "reason": "future behavior and target leakage",
    },
    {
        "source_id": "retention_offer_outcomes",
        "source_table": "ml_offers",
        "timing": "intervention_after_prediction_time",
        "available_at_policy": "offer is sent after scoring",
        "max_observed_at": "2026-05-24T12:00:00+03:00",
        "allowed": "false",
        "reason": "post-score action outcome",
    },
    {
        "source_id": "churn_label",
        "source_table": "ml_labels",
        "timing": "label_after_prediction_time",
        "available_at_policy": "label_observed_at after target horizon",
        "max_observed_at": "2026-06-07T12:00:00+03:00",
        "allowed": "false",
        "reason": "the target itself",
    },
]


ML_FEATURE_AVAILABILITY = [
    {
        "feature_name": "sessions_14d",
        "source_id": "events_lookback_14d",
        "source_table": "ml_events",
        "feature_role": "delivery_model_feature",
        "timing": "lookback_before_prediction_time",
        "available_at_policy": "event_time < prediction_time and ingested before scoring",
        "max_observed_at": "prediction_time - 20m",
        "used_in_delivery_model": "true",
        "risk_type": "none",
        "notes": "past product activity only",
    },
    {
        "feature_name": "active_days_14d",
        "source_id": "events_lookback_14d",
        "source_table": "ml_events",
        "feature_role": "delivery_model_feature",
        "timing": "lookback_before_prediction_time",
        "available_at_policy": "event_time < prediction_time and ingested before scoring",
        "max_observed_at": "prediction_time - 20m",
        "used_in_delivery_model": "true",
        "risk_type": "none",
        "notes": "past product activity only",
    },
    {
        "feature_name": "support_tickets_14d",
        "source_id": "support_tickets_before_prediction",
        "source_table": "ml_support_tickets",
        "feature_role": "delivery_model_feature",
        "timing": "lookback_before_prediction_time",
        "available_at_policy": "ticket_created_at < prediction_time",
        "max_observed_at": "prediction_time - 50m",
        "used_in_delivery_model": "true",
        "risk_type": "none",
        "notes": "support history before scoring",
    },
    {
        "feature_name": "revenue_30d",
        "source_id": "orders_lookback_30d",
        "source_table": "ml_orders",
        "feature_role": "delivery_model_feature",
        "timing": "lookback_before_prediction_time",
        "available_at_policy": "order_paid_at < prediction_time",
        "max_observed_at": "prediction_time - 12h",
        "used_in_delivery_model": "true",
        "risk_type": "none",
        "notes": "past purchase behavior only",
    },
    {
        "feature_name": "days_since_signup",
        "source_id": "user_profile",
        "source_table": "ml_users",
        "feature_role": "delivery_model_feature",
        "timing": "known_before_prediction_time",
        "available_at_policy": "created_at <= prediction_time",
        "max_observed_at": "account_created_at",
        "used_in_delivery_model": "true",
        "risk_type": "none",
        "notes": "stable account attribute",
    },
    {
        "feature_name": "had_support_ticket_14d",
        "source_id": "support_tickets_before_prediction",
        "source_table": "ml_support_tickets",
        "feature_role": "delivery_model_feature",
        "timing": "lookback_before_prediction_time",
        "available_at_policy": "ticket_created_at < prediction_time",
        "max_observed_at": "prediction_time - 50m",
        "used_in_delivery_model": "true",
        "risk_type": "none",
        "notes": "binary summary of past support history",
    },
    {
        "feature_name": "plan_id",
        "source_id": "subscription_snapshot",
        "source_table": "ml_scoring_snapshots",
        "feature_role": "delivery_model_feature",
        "timing": "known_before_prediction_time",
        "available_at_policy": "snapshot fields are materialized at prediction_time",
        "max_observed_at": "prediction_time",
        "used_in_delivery_model": "true",
        "risk_type": "none",
        "notes": "trial plan at scoring moment",
    },
    {
        "feature_name": "platform",
        "source_id": "user_profile",
        "source_table": "ml_users",
        "feature_role": "delivery_model_feature",
        "timing": "known_before_prediction_time",
        "available_at_policy": "created_at <= prediction_time",
        "max_observed_at": "account_created_at",
        "used_in_delivery_model": "true",
        "risk_type": "none",
        "notes": "stable account attribute",
    },
    {
        "feature_name": "country",
        "source_id": "user_profile",
        "source_table": "ml_users",
        "feature_role": "delivery_model_feature",
        "timing": "known_before_prediction_time",
        "available_at_policy": "created_at <= prediction_time",
        "max_observed_at": "account_created_at",
        "used_in_delivery_model": "true",
        "risk_type": "none",
        "notes": "stable account attribute",
    },
    {
        "feature_name": "acquisition_channel",
        "source_id": "user_profile",
        "source_table": "ml_users",
        "feature_role": "delivery_model_feature",
        "timing": "known_before_prediction_time",
        "available_at_policy": "created_at <= prediction_time",
        "max_observed_at": "account_created_at",
        "used_in_delivery_model": "true",
        "risk_type": "none",
        "notes": "stable acquisition attribute with missing bucket",
    },
    {
        "feature_name": "churned_14d",
        "source_id": "churn_label",
        "source_table": "ml_labels",
        "feature_role": "known_bad_candidate",
        "timing": "label_after_prediction_time",
        "available_at_policy": "label_observed_at after target horizon",
        "max_observed_at": "prediction_time + 14d",
        "used_in_delivery_model": "false",
        "risk_type": "target_leakage",
        "notes": "target itself",
    },
    {
        "feature_name": "days_until_label_observed",
        "source_id": "churn_label",
        "source_table": "ml_labels",
        "feature_role": "known_bad_candidate",
        "timing": "label_after_prediction_time",
        "available_at_policy": "label_observed_at after target horizon",
        "max_observed_at": "prediction_time + 14d",
        "used_in_delivery_model": "false",
        "risk_type": "label_availability_leakage",
        "notes": "derived from future label timestamp",
    },
    {
        "feature_name": "cancelled_after_prediction",
        "source_id": "cancellation_events_after_prediction",
        "source_table": "ml_events",
        "feature_role": "known_bad_candidate",
        "timing": "post_prediction_time",
        "available_at_policy": "event_time >= prediction_time",
        "max_observed_at": "prediction_time + 9d",
        "used_in_delivery_model": "false",
        "risk_type": "future_behavior_leakage",
        "notes": "future behavior after scoring",
    },
    {
        "feature_name": "retention_offer_accepted",
        "source_id": "retention_offer_outcomes",
        "source_table": "ml_offers",
        "feature_role": "known_bad_candidate",
        "timing": "intervention_after_prediction_time",
        "available_at_policy": "offer is sent after scoring",
        "max_observed_at": "prediction_time + 2d",
        "used_in_delivery_model": "false",
        "risk_type": "post_intervention_outcome_leakage",
        "notes": "post-score action outcome",
    },
    {
        "feature_name": "segment_churn_rate_full_dataset",
        "source_id": "churn_label",
        "source_table": "ml_labels",
        "feature_role": "known_bad_candidate",
        "timing": "full_sample_label_aggregation",
        "available_at_policy": "computed after observing all labels",
        "max_observed_at": "test label horizon",
        "used_in_delivery_model": "false",
        "risk_type": "full_sample_target_encoding",
        "notes": "target encoding before split would see validation/test labels",
    },
]


ML_FEATURE_SELECTION_LOG = [
    {
        "selector_id": "predeclared_feature_contract",
        "selector_kind": "business_feature_contract",
        "scope": "predeclared_business_contract",
        "fit_split": "none",
        "uses_labels": "false",
        "uses_validation_labels": "false",
        "uses_test_labels": "false",
        "inside_pipeline": "true",
        "inside_cv": "true",
        "selected_for_delivery": "true",
        "status": "allowed_delivery_path",
        "notes": "explicit raw feature list is declared before model fitting",
    },
    {
        "selector_id": "select_k_best_all_rows",
        "selector_kind": "SelectKBest",
        "scope": "all_rows_before_split",
        "fit_split": "all_eligible",
        "uses_labels": "true",
        "uses_validation_labels": "true",
        "uses_test_labels": "true",
        "inside_pipeline": "false",
        "inside_cv": "false",
        "selected_for_delivery": "false",
        "status": "rejected_known_bad_example",
        "notes": "feature selector sees labels before train/test split",
    },
    {
        "selector_id": "validation_score_manual_pruning",
        "selector_kind": "manual_feature_pruning",
        "scope": "validation_before_cv",
        "fit_split": "validation",
        "uses_labels": "true",
        "uses_validation_labels": "true",
        "uses_test_labels": "false",
        "inside_pipeline": "false",
        "inside_cv": "false",
        "selected_for_delivery": "false",
        "status": "rejected_known_bad_example",
        "notes": "pruning features by validation score before CV creates selection bias",
    },
    {
        "selector_id": "future_rfecv_inside_pipeline",
        "selector_kind": "RFECV",
        "scope": "inside_cv_pipeline",
        "fit_split": "cv_train",
        "uses_labels": "true",
        "uses_validation_labels": "false",
        "uses_test_labels": "false",
        "inside_pipeline": "true",
        "inside_cv": "true",
        "selected_for_delivery": "false",
        "status": "allowed_future_pattern",
        "notes": "feature selection would be acceptable only inside each training fold",
    },
]


ML_MODEL_SELECTION_LOG = [
    {
        "candidate_id": "random_forest_depth2_unweighted",
        "candidate_family": "random_forest_classifier",
        "selection_stage": "imbalance_policy_validation",
        "selection_split": "validation",
        "validation_precision_at_budget": "0.0",
        "test_precision_at_budget": "0.0",
        "test_metric_visible_to_selector": "false",
        "selected_for_delivery": "false",
        "selection_rank": "2",
        "status": "evaluated_not_selected",
        "notes": "registered before test evaluation",
    },
    {
        "candidate_id": "random_forest_depth2_class_weight_balanced",
        "candidate_family": "random_forest_classifier",
        "selection_stage": "imbalance_policy_validation",
        "selection_split": "validation",
        "validation_precision_at_budget": "0.5",
        "test_precision_at_budget": "0.0",
        "test_metric_visible_to_selector": "false",
        "selected_for_delivery": "true",
        "selection_rank": "1",
        "status": "selected_on_validation",
        "notes": "selected before final holdout interpretation",
    },
    {
        "candidate_id": "calibrated_bin_map_v0",
        "candidate_family": "probability_calibrator",
        "selection_stage": "calibration_validation",
        "selection_split": "validation",
        "validation_precision_at_budget": "0.5",
        "test_precision_at_budget": "0.5",
        "test_metric_visible_to_selector": "false",
        "selected_for_delivery": "false",
        "selection_rank": "",
        "status": "calibration_handoff_not_model_selection",
        "notes": "calibration applies a predeclared validation bin map",
    },
    {
        "candidate_id": "leaky_test_best_threshold_0_5",
        "candidate_family": "threshold_policy",
        "selection_stage": "post_hoc_test_cherry_pick",
        "selection_split": "test",
        "validation_precision_at_budget": "1.0",
        "test_precision_at_budget": "1.0",
        "test_metric_visible_to_selector": "true",
        "selected_for_delivery": "false",
        "selection_rank": "",
        "status": "rejected_known_bad_example",
        "notes": "using test to choose threshold would be cherry-picking",
    },
]


def preprocessing_contract() -> dict[str, object]:
    return {
        "contract_id": "trial-churn-preprocessing-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "input_table": "ml_raw_features.csv",
        "key": "snapshot_id",
        "fit_split": "train",
        "transform_splits": ["train", "validation", "test"],
        "missing_value_policy": "explicit_impute",
        "unknown_category_policy": "bucket",
        "unknown_category_bucket": "__unknown__",
        "missing_category_bucket": "__missing__",
        "numeric_features": [
            {"name": "sessions_14d", "impute": {"strategy": "median"}, "scale": "standard"},
            {"name": "active_days_14d", "impute": {"strategy": "median"}, "scale": "standard"},
            {
                "name": "support_tickets_14d",
                "impute": {"strategy": "constant", "fill_value": 0.0},
                "scale": "standard",
            },
            {
                "name": "revenue_30d",
                "impute": {"strategy": "constant", "fill_value": 0.0},
                "scale": "standard",
            },
            {
                "name": "days_since_signup",
                "impute": {"strategy": "median"},
                "scale": "standard",
            },
        ],
        "categorical_features": [
            {
                "name": "plan_id",
                "impute": {"strategy": "constant", "fill_value": "__missing__"},
                "encode": "one_hot",
                "handle_unknown": "use_unknown_bucket",
            },
            {
                "name": "platform",
                "impute": {"strategy": "constant", "fill_value": "__missing__"},
                "encode": "one_hot",
                "handle_unknown": "use_unknown_bucket",
            },
            {
                "name": "country",
                "impute": {"strategy": "constant", "fill_value": "__missing__"},
                "encode": "one_hot",
                "handle_unknown": "use_unknown_bucket",
            },
            {
                "name": "acquisition_channel",
                "impute": {"strategy": "constant", "fill_value": "__missing__"},
                "encode": "one_hot",
                "handle_unknown": "use_unknown_bucket",
            },
        ],
        "forbidden_columns": [
            "churned_14d",
            "label_observed_at",
            "score",
            "split",
            "role",
        ],
        "output": {
            "feature_name_order": "numeric_then_categorical_contract_order",
            "matrix_file": "preprocessed_feature_matrix.csv",
            "state_file": "preprocessing_state.json",
        },
    }


def pipeline_spec() -> dict[str, object]:
    return {
        "pipeline_id": "trial-churn-sklearn-pipeline-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "preprocessing_contract_id": "trial-churn-preprocessing-v0",
        "fit_split": "train",
        "predict_splits": ["validation", "test"],
        "score_type": "churn_risk_probability",
        "preprocessing_location": "inside_pipeline",
        "steps": [
            {
                "name": "preprocess",
                "kind": "contract_preprocessor",
                "source": "preprocessing_contract.json",
            },
            {
                "name": "estimator",
                "kind": "logistic_regression",
                "params": {
                    "solver": "liblinear",
                    "C": 1.0,
                    "l1_ratio": 0.0,
                    "class_weight": None,
                    "max_iter": 200,
                    "random_state": 0,
                },
            },
        ],
        "audit_policy": {
            "require_single_pipeline_object": True,
            "fit_preprocessing_and_estimator_together": True,
            "forbid_external_preprocessed_matrix_input": True,
            "forbid_fit_on_validation_or_test": True,
            "prediction_output_splits": ["validation", "test"],
        },
        "output": {
            "prediction_file": "pipeline_predictions.csv",
            "report_file": "pipeline_report.json",
            "serialized_spec_file": "pipeline_serialized_spec.json",
        },
    }


def column_transformer_spec() -> dict[str, object]:
    categorical_categories = {
        "plan_id": ["trial_basic", "trial_pro", "__missing__", "__unknown__"],
        "platform": ["android", "ios", "web", "__missing__", "__unknown__"],
        "country": ["KZ", "RU", "__missing__", "__unknown__"],
        "acquisition_channel": [
            "organic",
            "paid_search",
            "referral",
            "__missing__",
            "__unknown__",
        ],
    }
    return {
        "column_transformer_id": "trial-churn-column-transformer-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "preprocessing_contract_id": "trial-churn-preprocessing-v0",
        "pipeline_id": "trial-churn-sklearn-pipeline-v0",
        "fit_split": "train",
        "predict_splits": ["validation", "test"],
        "score_type": "churn_risk_probability",
        "preprocessing_location": "inside_pipeline",
        "remainder": "drop",
        "sparse_output": False,
        "routes": [
            {
                "name": "numeric_median",
                "kind": "numeric",
                "columns": ["sessions_14d", "active_days_14d", "days_since_signup"],
                "steps": [
                    {"name": "imputer", "class": "SimpleImputer", "params": {"strategy": "median"}},
                    {
                        "name": "scaler",
                        "class": "StandardScaler",
                        "params": {"with_mean": True, "with_std": True},
                    },
                ],
            },
            {
                "name": "numeric_constant",
                "kind": "numeric",
                "columns": ["support_tickets_14d", "revenue_30d"],
                "steps": [
                    {
                        "name": "imputer",
                        "class": "SimpleImputer",
                        "params": {"strategy": "constant", "fill_value": 0.0},
                    },
                    {
                        "name": "scaler",
                        "class": "StandardScaler",
                        "params": {"with_mean": True, "with_std": True},
                    },
                ],
            },
            {
                "name": "categorical",
                "kind": "categorical",
                "columns": ["plan_id", "platform", "country", "acquisition_channel"],
                "allowed_categories": categorical_categories,
                "missing_category_bucket": "__missing__",
                "unknown_category_bucket": "__unknown__",
                "steps": [
                    {
                        "name": "unknown_bucket",
                        "class": "UnknownCategoryBucketer",
                        "params": {
                            "missing_value": "__missing__",
                            "unknown_value": "__unknown__",
                        },
                    },
                    {
                        "name": "one_hot",
                        "class": "OneHotEncoder",
                        "params": {
                            "categories": "from_column_transformer_spec",
                            "handle_unknown": "error",
                            "sparse_output": False,
                            "feature_name_combiner": "concat",
                        },
                    },
                ],
            },
            {
                "name": "binary",
                "kind": "binary",
                "columns": ["had_support_ticket_14d"],
                "steps": [
                    {
                        "name": "imputer",
                        "class": "SimpleImputer",
                        "params": {"strategy": "constant", "fill_value": 0.0},
                    }
                ],
            },
        ],
        "estimator": {
            "kind": "logistic_regression",
            "params": {
                "solver": "liblinear",
                "C": 1.0,
                "l1_ratio": 0.0,
                "class_weight": None,
                "max_iter": 200,
                "random_state": 0,
            },
        },
        "audit_policy": {
            "require_column_transformer_inside_pipeline": True,
            "require_explicit_column_routes": True,
            "forbid_remainder_passthrough": True,
            "require_feature_names_out": True,
            "require_unknown_category_bucket": True,
            "forbid_dropped_required_features": True,
            "forbid_fit_on_validation_or_test": True,
            "prediction_output_splits": ["validation", "test"],
        },
        "output": {
            "routing_file": "column_transformer_routing.csv",
            "feature_schema_file": "column_transformer_feature_schema.csv",
            "prediction_file": "column_transformer_predictions.csv",
            "report_file": "column_transformer_report.json",
            "serialized_spec_file": "column_transformer_serialized_spec.json",
        },
    }


def linear_baseline_spec() -> dict[str, object]:
    return {
        "linear_baseline_id": "trial-churn-linear-baseline-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "pipeline_id": "trial-churn-sklearn-pipeline-v0",
        "column_transformer_id": "trial-churn-column-transformer-v0",
        "fit_split": "train",
        "selection_split": "validation",
        "final_holdout_split": "test",
        "score_type": "churn_risk_probability",
        "preprocessing_location": "inside_pipeline",
        "comparison": {
            "primary_metric": "precision_at_budget",
            "higher_is_better": True,
            "tie_breakers": [
                {"metric": "error_cost_at_budget", "higher_is_better": False},
                {"metric": "average_precision", "higher_is_better": True},
                {"metric": "log_loss", "higher_is_better": False},
            ],
            "budget_source": "problem_spec.decision_budget.max_actions",
            "selection_data": "validation",
            "test_data_role": "final_once_only_evaluation",
        },
        "candidates": [
            {
                "model_id": "dummy_prior",
                "kind": "dummy_classifier",
                "role": "featureless_floor",
                "params": {"strategy": "prior", "random_state": 0},
            },
            {
                "model_id": "logistic_l2",
                "kind": "logistic_regression",
                "role": "primary_linear_baseline",
                "params": {
                    "solver": "liblinear",
                    "C": 1.0,
                    "l1_ratio": 0.0,
                    "class_weight": None,
                    "max_iter": 200,
                    "random_state": 0,
                },
                "regularization": {
                    "family": "l2",
                    "C": 1.0,
                    "l1_ratio": 0.0,
                    "note": (
                        "C is inverse regularization strength; smaller C means stronger "
                        "regularization."
                    ),
                },
            },
        ],
        "coefficient_policy": {
            "require_feature_schema": True,
            "top_n": 8,
            "interpretation_limits": [
                (
                    "coefficients describe the fitted transformed feature space, not raw causal "
                    "effects"
                ),
                "numeric coefficients depend on imputation and StandardScaler state",
                "one-hot coefficients are relative to the encoded category set and intercept",
                "regularization shrinks coefficients and may change signs on tiny samples",
                "validation/test metrics do not prove offer impact",
            ],
        },
        "audit_policy": {
            "require_dummy_baseline": True,
            "require_logistic_baseline": True,
            "require_validation_only_selection": True,
            "forbid_test_selection": True,
            "require_regularization_declared": True,
            "require_intercept_reported": True,
            "require_coefficients_join_feature_schema": True,
            "require_interpretation_limits": True,
            "forbid_fit_on_validation_or_test": True,
        },
        "output": {
            "comparison_file": "baseline_comparison.csv",
            "coefficient_file": "coefficient_table.csv",
            "prediction_file": "baseline_predictions.csv",
            "report_file": "baseline_report.json",
            "serialized_spec_file": "linear_baseline_serialized_spec.json",
        },
    }


def tree_diagnostic_spec() -> dict[str, object]:
    return {
        "tree_diagnostic_id": "trial-churn-tree-diagnostic-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "pipeline_id": "trial-churn-sklearn-pipeline-v0",
        "column_transformer_id": "trial-churn-column-transformer-v0",
        "linear_baseline_id": "trial-churn-linear-baseline-v0",
        "fit_split": "train",
        "diagnostic_splits": ["train", "validation"],
        "final_holdout_split": "test",
        "score_type": "churn_risk_probability",
        "diagnostic_role": "non_linear_shape_probe_not_production_promotion",
        "comparison": {
            "primary_metric": "precision_at_budget",
            "budget_source": "problem_spec.decision_budget.max_actions",
            "baseline_source": "linear_baseline.selected_model_id",
            "selection_data": "validation",
            "test_data_role": "final_once_only_evaluation",
        },
        "candidate": {
            "model_id": "decision_tree_depth2",
            "kind": "decision_tree_classifier",
            "role": "diagnostic_non_linear_baseline",
            "params": {
                "criterion": "gini",
                "max_depth": 2,
                "min_samples_split": 2,
                "min_samples_leaf": 1,
                "max_leaf_nodes": None,
                "class_weight": None,
                "ccp_alpha": 0.0,
                "random_state": 0,
            },
        },
        "overfit_policy": {
            "compare_split_pair": ["train", "validation"],
            "metrics": ["accuracy_at_0_5", "precision_at_budget", "log_loss"],
            "warning_thresholds": {
                "accuracy_at_0_5": 0.25,
                "precision_at_budget": 0.5,
                "log_loss": 1.0,
            },
        },
        "rule_export": {
            "method": "sklearn.tree.export_text",
            "max_depth": 3,
            "show_weights": True,
            "decimals": 3,
            "require_feature_names": True,
            "interpretation_limits": [
                "rules split transformed features produced by ColumnTransformer",
                "one-hot rules are not causal explanations of churn",
                "tiny train leaves can be pure by memorization",
                "tree diagnostics do not override validation/test split policy",
            ],
        },
        "audit_policy": {
            "require_linear_baseline_handoff": True,
            "require_depth_limit": True,
            "require_min_samples_leaf": True,
            "require_random_state": True,
            "require_train_validation_gap": True,
            "require_rule_export": True,
            "require_feature_schema_alignment": True,
            "forbid_fit_on_validation_or_test": True,
            "forbid_test_selection": True,
        },
        "output": {
            "prediction_file": "tree_predictions.csv",
            "overfit_file": "tree_overfit_report.csv",
            "node_file": "tree_node_report.csv",
            "rules_file": "tree_rules.txt",
            "report_file": "tree_report.json",
            "serialized_spec_file": "tree_serialized_spec.json",
        },
    }


def tree_ensemble_spec() -> dict[str, object]:
    return {
        "tree_ensemble_id": "trial-churn-tree-ensemble-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "pipeline_id": "trial-churn-sklearn-pipeline-v0",
        "column_transformer_id": "trial-churn-column-transformer-v0",
        "linear_baseline_id": "trial-churn-linear-baseline-v0",
        "tree_diagnostic_id": "trial-churn-tree-diagnostic-v0",
        "fit_split": "train",
        "selection_split": "validation",
        "stability_split": "validation",
        "final_holdout_split": "test",
        "score_type": "churn_risk_probability",
        "ensemble_role": "candidate_tree_ensemble_not_production_promotion",
        "comparison": {
            "primary_metric": "precision_at_budget",
            "higher_is_better": True,
            "budget_source": "problem_spec.decision_budget.max_actions",
            "baseline_sources": [
                "linear_baseline.selected_model_id",
                "tree_diagnostic.candidate.model_id",
            ],
            "selection_data": "validation",
            "test_data_role": "final_once_only_evaluation",
        },
        "candidate": {
            "model_id": "random_forest_depth2",
            "kind": "random_forest_classifier",
            "role": "variance_reduced_tree_ensemble_candidate",
            "params": {
                "n_estimators": 25,
                "criterion": "gini",
                "max_depth": 2,
                "min_samples_split": 2,
                "min_samples_leaf": 1,
                "max_features": "sqrt",
                "bootstrap": True,
                "class_weight": None,
                "random_state": 0,
                "n_jobs": 1,
            },
        },
        "stability_policy": {
            "seeds": [0, 7, 13],
            "metric": "precision_at_budget",
            "split": "validation",
            "max_allowed_range": 0.5,
            "require_identical_selected_ids": False,
        },
        "feature_importance_policy": {
            "methods": ["mdi", "permutation"],
            "permutation_split": "validation",
            "permutation_repeats": 5,
            "permutation_random_state": 0,
            "top_n": 8,
            "warnings": [
                "mdi_importance_is_train_impurity_based",
                "mdi_can_favor_high_cardinality_features",
                "permutation_on_tiny_validation_is_unstable",
            ],
        },
        "slice_policy": {
            "slices": ["platform", "country"],
            "split": "validation",
            "min_rows_for_reliable_slice": 3,
            "metrics": ["precision_at_budget", "recall_at_budget", "accuracy_at_0_5"],
        },
        "audit_policy": {
            "require_tree_diagnostic_handoff": True,
            "require_validation_only_selection": True,
            "forbid_test_selection": True,
            "require_random_state": True,
            "require_stability_report": True,
            "require_feature_importance_warning": True,
            "require_slice_metrics": True,
            "forbid_fit_on_validation_or_test": True,
        },
        "output": {
            "comparison_file": "ensemble_comparison.csv",
            "stability_file": "ensemble_stability_report.csv",
            "feature_importance_file": "ensemble_feature_importance.csv",
            "slice_metrics_file": "ensemble_slice_metrics.csv",
            "prediction_file": "ensemble_predictions.csv",
            "report_file": "ensemble_report.json",
            "serialized_spec_file": "ensemble_serialized_spec.json",
        },
    }


def cv_plan_spec() -> dict[str, object]:
    return {
        "cv_plan_id": "trial-churn-cv-plan-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "pipeline_id": "trial-churn-sklearn-pipeline-v0",
        "column_transformer_id": "trial-churn-column-transformer-v0",
        "linear_baseline_id": "trial-churn-linear-baseline-v0",
        "tree_diagnostic_id": "trial-churn-tree-diagnostic-v0",
        "tree_ensemble_id": "trial-churn-tree-ensemble-v0",
        "fold_manifest_file": "ml_cv_fold_manifest.csv",
        "model_selection_pool_splits": ["train", "validation"],
        "final_holdout_split": "test",
        "score_type": "churn_risk_probability",
        "cv_strategy": {
            "kind": "predeclared_time_ordered_group_folds",
            "n_splits": 2,
            "fold_id_column": "fold_id",
            "train_role": "cv_train",
            "validation_role": "cv_validation",
            "group_key": "user_id",
            "time_key": "prediction_time",
            "allow_same_prediction_time_within_fold": True,
            "forbid_future_train_rows": True,
        },
        "scoring": {
            "primary_metric": "precision_at_budget",
            "aligned_with": "tree_ensemble_spec.comparison.primary_metric",
            "budget_source": "problem_spec.decision_budget.max_actions",
            "requires_proba": True,
            "selected_ids_tie_breaker": "score_desc_snapshot_id_asc",
            "secondary_metrics": ["recall_at_budget", "average_precision", "log_loss"],
        },
        "candidate_source": {
            "spec": "tree_ensemble_spec.json",
            "model_id": "random_forest_depth2",
            "kind": "random_forest_classifier",
        },
        "audit_policy": {
            "require_ensemble_handoff": True,
            "require_fold_manifest": True,
            "require_group_isolation": True,
            "require_temporal_order": True,
            "require_class_coverage_per_fold": True,
            "require_scoring_alignment": True,
            "forbid_test_rows_in_cv": True,
            "forbid_fit_on_cv_validation": True,
            "forbid_default_integer_cv": True,
        },
        "output": {
            "fold_manifest_file": "cv_fold_manifest.csv",
            "score_file": "cv_score_report.csv",
            "prediction_file": "cv_predictions.csv",
            "audit_file": "cv_no_peeking_audit.csv",
            "report_file": "cv_report.json",
            "serialized_spec_file": "cv_serialized_spec.json",
        },
    }


def imbalance_policy_spec() -> dict[str, object]:
    return {
        "imbalance_policy_id": "trial-churn-imbalance-policy-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "pipeline_id": "trial-churn-sklearn-pipeline-v0",
        "column_transformer_id": "trial-churn-column-transformer-v0",
        "linear_baseline_id": "trial-churn-linear-baseline-v0",
        "tree_diagnostic_id": "trial-churn-tree-diagnostic-v0",
        "tree_ensemble_id": "trial-churn-tree-ensemble-v0",
        "cv_plan_id": "trial-churn-cv-plan-v0",
        "score_type": "churn_risk_probability",
        "fit_split": "train",
        "selection_split": "validation",
        "final_holdout_split": "test",
        "distribution": {
            "label_column": "churned_14d",
            "positive_class": True,
            "negative_class": False,
            "warn_if_positive_rate_below": 0.4,
            "report_by": ["split", "cv_role"],
        },
        "accuracy_trap": {
            "baseline_model_id": "always_negative",
            "strategy": "predict_negative_class",
            "evaluate_splits": ["validation", "test"],
            "accuracy_is_diagnostic_only": True,
            "blocking_if_primary_metric_accuracy": True,
            "must_report_positive_recall": True,
            "must_report_balanced_accuracy": True,
        },
        "class_weight_policy": {
            "candidate_model_id": "random_forest_depth2_class_weight_balanced",
            "source_model_id": "random_forest_depth2",
            "class_weight": "balanced",
            "compute_on": "fit_split_only",
            "formula": "n_samples / (n_classes * np.bincount(y))",
            "forbid_computing_weights_on_validation_or_test": True,
        },
        "resampling_policy": {
            "allowed": False,
            "reason": "tiny profile uses class_weight only; resampling is deferred",
            "if_enabled_fit_scope": "cv_train_or_train_only",
            "forbid_resampling_validation_or_test": True,
        },
        "threshold_policy": {
            "selection_data": "validation",
            "budget_source": "problem_spec.decision_budget.max_actions",
            "primary_decision_rule": "rank_top_k_within_scoring_batch",
            "fixed_threshold_role": "diagnostic_only_until_calibration",
            "candidate_thresholds": [0.3, 0.5, 0.6],
            "tie_breaker": "score_desc_snapshot_id_asc",
        },
        "comparison": {
            "primary_metric": "precision_at_budget",
            "forbidden_primary_metrics": ["accuracy", "accuracy_at_0_5"],
            "secondary_metrics": [
                "recall_at_budget",
                "balanced_accuracy_at_0_5",
                "average_precision",
                "log_loss",
                "error_cost_at_budget",
            ],
            "selection_data": "validation",
            "test_data_role": "final_once_only_evaluation",
        },
        "audit_policy": {
            "require_cv_handoff": True,
            "require_class_distribution_report": True,
            "require_accuracy_trap_report": True,
            "require_class_weight_fit_scope": True,
            "require_threshold_budget_report": True,
            "forbid_accuracy_as_primary_metric": True,
            "forbid_resampling_validation_or_test": True,
            "forbid_threshold_selection_on_test": True,
            "forbid_test_selection": True,
        },
        "output": {
            "distribution_file": "class_distribution.csv",
            "baseline_trap_file": "baseline_trap_report.csv",
            "threshold_file": "imbalance_threshold_report.csv",
            "prediction_file": "imbalance_predictions.csv",
            "audit_file": "imbalance_policy_audit.csv",
            "report_file": "imbalance_report.json",
            "serialized_spec_file": "imbalance_serialized_spec.json",
        },
    }


def calibration_policy_spec() -> dict[str, object]:
    return {
        "calibration_policy_id": "trial-churn-calibration-policy-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "pipeline_id": "trial-churn-sklearn-pipeline-v0",
        "column_transformer_id": "trial-churn-column-transformer-v0",
        "linear_baseline_id": "trial-churn-linear-baseline-v0",
        "tree_diagnostic_id": "trial-churn-tree-diagnostic-v0",
        "tree_ensemble_id": "trial-churn-tree-ensemble-v0",
        "cv_plan_id": "trial-churn-cv-plan-v0",
        "imbalance_policy_id": "trial-churn-imbalance-policy-v0",
        "source_model_id": "random_forest_depth2_class_weight_balanced",
        "score_type": "churn_risk_probability",
        "calibrated_score_type": "calibrated_churn_probability",
        "fit_split": "train",
        "calibration_split": "validation",
        "evaluation_split": "test",
        "calibration_method": {
            "kind": "validation_bin_map_with_laplace_smoothing",
            "bin_edges": [0.0, 0.5, 0.6, 1.0],
            "interval_policy": "lower_inclusive_upper_exclusive_except_last",
            "smoothing_alpha": 2.0,
            "prior_source": "calibration_split_positive_rate",
            "min_calibration_rows": 20,
            "min_rows_per_bin": 2,
            "warn_if_bin_has_single_class": True,
        },
        "metrics": {
            "proper_scoring_rules": ["brier_score", "log_loss"],
            "diagnostics": ["expected_calibration_error", "calibration_bins"],
            "compare_sources": ["uncalibrated", "calibrated"],
        },
        "threshold_policy": {
            "selection_data": "validation",
            "evaluation_data": "test",
            "budget_source": "problem_spec.decision_budget.max_actions",
            "primary_decision_rule": "rank_top_k_within_scoring_batch",
            "fixed_threshold_role": "calibration_impact_diagnostic",
            "candidate_thresholds": [0.3, 0.5, 0.6],
            "tie_breaker": "score_desc_snapshot_id_asc",
            "forbid_threshold_selection_on_test": True,
        },
        "audit_policy": {
            "require_imbalance_handoff": True,
            "require_independent_calibration_split": True,
            "require_calibration_bins": True,
            "require_brier_score": True,
            "require_log_loss": True,
            "require_threshold_impact_report": True,
            "forbid_fit_on_calibration_or_test": True,
            "forbid_calibration_on_test": True,
            "forbid_test_threshold_selection": True,
            "warn_small_calibration_sample": True,
        },
        "output": {
            "bin_file": "calibration_bins.csv",
            "metric_file": "calibration_metrics.csv",
            "prediction_file": "calibrated_predictions.csv",
            "threshold_file": "calibration_threshold_impact.csv",
            "audit_file": "calibration_policy_audit.csv",
            "report_file": "calibration_report.json",
            "serialized_spec_file": "calibration_serialized_spec.json",
        },
    }


def leakage_policy_spec() -> dict[str, object]:
    return {
        "leakage_policy_id": "trial-churn-leakage-policy-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "pipeline_id": "trial-churn-sklearn-pipeline-v0",
        "column_transformer_id": "trial-churn-column-transformer-v0",
        "linear_baseline_id": "trial-churn-linear-baseline-v0",
        "tree_diagnostic_id": "trial-churn-tree-diagnostic-v0",
        "tree_ensemble_id": "trial-churn-tree-ensemble-v0",
        "cv_plan_id": "trial-churn-cv-plan-v0",
        "imbalance_policy_id": "trial-churn-imbalance-policy-v0",
        "calibration_policy_id": "trial-churn-calibration-policy-v0",
        "source_model_id": "random_forest_depth2_class_weight_balanced",
        "fit_split": "train",
        "validation_split": "validation",
        "test_split": "test",
        "feature_availability_file": "ml_feature_availability.csv",
        "feature_selection_log_file": "ml_feature_selection_log.csv",
        "model_selection_log_file": "ml_model_selection_log.csv",
        "feature_availability_policy": {
            "prediction_time_column": "prediction_time",
            "allowed_timings": [
                "known_before_prediction_time",
                "lookback_before_prediction_time",
            ],
            "forbidden_timings": [
                "post_prediction_time",
                "intervention_after_prediction_time",
                "label_after_prediction_time",
                "full_sample_label_aggregation",
            ],
            "require_source_in_problem_allowed_sources": True,
            "forbid_label_or_post_prediction_features": True,
            "forbid_forbidden_source_usage_in_delivery_model": True,
        },
        "preprocessing_scope_policy": {
            "fit_scope": "train_only",
            "require_pipeline_preprocessing": True,
            "forbid_full_sample_fit": True,
            "forbid_fit_on_validation_or_test": True,
            "audited_specs": [
                "preprocessing_contract",
                "pipeline_spec",
                "column_transformer_spec",
                "calibration_policy_spec",
            ],
        },
        "feature_selection_policy": {
            "current_selector_id": "predeclared_feature_contract",
            "allowed_scopes": [
                "predeclared_business_contract",
                "inside_cv_pipeline",
            ],
            "forbidden_scopes": [
                "all_rows_before_split",
                "validation_before_cv",
                "test_or_holdout",
            ],
            "forbid_select_k_best_before_split": True,
            "require_selector_inside_cv_if_label_aware": True,
            "forbid_delivery_selector_using_validation_or_test_labels": True,
        },
        "model_selection_policy": {
            "selected_model_id": "random_forest_depth2_class_weight_balanced",
            "selection_split": "validation",
            "final_holdout_split": "test",
            "forbid_test_metric_in_selection": True,
            "forbid_validation_score_cherry_picking": True,
            "require_candidate_registry": True,
            "require_single_selected_delivery_model": True,
        },
        "audit_policy": {
            "require_calibration_handoff": True,
            "require_feature_availability_report": True,
            "require_forbidden_feature_report": True,
            "require_preprocessing_scope_audit": True,
            "require_feature_selection_scope_audit": True,
            "require_model_selection_audit": True,
            "forbid_post_outcome_features": True,
            "forbid_full_sample_preprocessing": True,
            "forbid_feature_selection_outside_cv": True,
            "forbid_test_selection_or_cherry_picking": True,
        },
        "output": {
            "feature_availability_file": "feature_availability_report.csv",
            "forbidden_feature_file": "forbidden_feature_report.csv",
            "preprocessing_scope_file": "preprocessing_scope_audit.csv",
            "feature_selection_file": "feature_selection_audit.csv",
            "model_selection_file": "model_selection_audit.csv",
            "audit_file": "leakage_policy_audit.csv",
            "report_file": "leakage_report.json",
            "serialized_spec_file": "leakage_serialized_spec.json",
        },
    }


def error_analysis_policy_spec() -> dict[str, object]:
    return {
        "error_analysis_policy_id": "trial-churn-error-analysis-policy-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "pipeline_id": "trial-churn-sklearn-pipeline-v0",
        "column_transformer_id": "trial-churn-column-transformer-v0",
        "linear_baseline_id": "trial-churn-linear-baseline-v0",
        "tree_diagnostic_id": "trial-churn-tree-diagnostic-v0",
        "tree_ensemble_id": "trial-churn-tree-ensemble-v0",
        "cv_plan_id": "trial-churn-cv-plan-v0",
        "imbalance_policy_id": "trial-churn-imbalance-policy-v0",
        "calibration_policy_id": "trial-churn-calibration-policy-v0",
        "leakage_policy_id": "trial-churn-leakage-policy-v0",
        "source_model_id": "random_forest_depth2_class_weight_balanced",
        "analysis_split": "test",
        "reference_split": "validation",
        "prediction_source": "calibrated",
        "score_column": "calibrated_score",
        "decision_column": "selected_at_budget_calibrated",
        "label_column": "actual_label",
        "positive_class": True,
        "negative_class": False,
        "slice_policy": {
            "required_dimensions": ["segment_id", "platform", "country"],
            "business_dimensions": ["plan_id", "acquisition_channel"],
            "derived_dimensions": ["business_cohort", "score_band"],
            "business_cohort_formula": "plan_id + ':' + country",
            "forbid_training_split_slice_claims": True,
            "forbid_dropping_small_slices": True,
        },
        "score_band_policy": {
            "source": "calibrated_score",
            "bands": [
                {"band_id": "low", "lower": 0.0, "upper": 0.3},
                {"band_id": "medium", "lower": 0.3, "upper": 0.5},
                {"band_id": "high", "lower": 0.5, "upper": 1.0},
            ],
            "interval_policy": "lower_inclusive_upper_exclusive_except_last",
        },
        "metric_policy": {
            "primary_decision_rule": "rank_top_k_within_scoring_batch",
            "metrics": [
                "precision",
                "recall",
                "false_positive_rate",
                "false_negative_rate",
                "error_rate",
                "selection_rate",
                "brier_score",
            ],
            "confusion_terms": ["tp", "fp", "tn", "fn"],
            "compare_to_overall": True,
        },
        "small_n_policy": {
            "min_rows_per_slice": 3,
            "min_positive_count_for_recall_claim": 2,
            "action": "warn_not_hide",
            "forbid_dropping_small_slices": True,
        },
        "hidden_failure_policy": {
            "min_rows_for_candidate": 2,
            "warn_if_error_rate_above_overall_by": 0.25,
            "warn_if_precision_below_overall_by": 0.5,
            "require_hidden_failure_table": True,
            "aggregate_claim_requires_no_hidden_failure": True,
        },
        "audit_policy": {
            "require_leakage_handoff": True,
            "require_calibrated_predictions": True,
            "require_confusion_rows": True,
            "require_slice_metrics": True,
            "require_small_n_warnings": True,
            "require_hidden_failure_table": True,
            "forbid_test_selection": True,
            "forbid_hiding_small_slices": True,
            "forbid_aggregate_only_readiness_claim": True,
        },
        "output": {
            "confusion_row_file": "confusion_rows.csv",
            "slice_metric_file": "slice_metrics.csv",
            "small_n_warning_file": "small_n_warnings.csv",
            "hidden_failure_file": "hidden_failure_slices.csv",
            "error_example_file": "error_examples.csv",
            "audit_file": "error_analysis_policy_audit.csv",
            "report_file": "error_analysis_report.json",
            "serialized_spec_file": "error_analysis_serialized_spec.json",
        },
    }


def ml_baseline_package_spec() -> dict[str, object]:
    return {
        "package_id": "trial-churn-ml-baseline-package-v0",
        "model_card_id": "trial-churn-risk-model-card-v0",
        "problem_id": "trial-churn-risk-7d-before-end",
        "source_model_id": "random_forest_depth2_class_weight_balanced",
        "error_analysis_policy_id": "trial-churn-error-analysis-policy-v0",
        "package_version": "0.1.0",
        "generated_for": "offline_baseline_review",
        "required_upstream_reports": [
            {
                "id": "problem_report",
                "lesson": "15/01",
                "expected_readiness": "ready_for_split_design",
            },
            {
                "id": "split_report",
                "lesson": "15/02",
                "expected_readiness": "ready_for_metric_policy",
            },
            {
                "id": "metric_report",
                "lesson": "15/03",
                "expected_readiness": "ready_for_preprocessing_and_baselines",
            },
            {
                "id": "preprocessing_report",
                "lesson": "15/04",
                "expected_readiness": "ready_for_pipeline_lesson",
            },
            {
                "id": "pipeline_report",
                "lesson": "15/05",
                "expected_readiness": "ready_for_column_transformer_lesson",
            },
            {
                "id": "column_transformer_report",
                "lesson": "15/06",
                "expected_readiness": "ready_for_linear_baseline_lesson",
            },
            {
                "id": "baseline_report",
                "lesson": "15/07",
                "expected_readiness": "ready_for_tree_diagnostics_lesson",
            },
            {
                "id": "tree_report",
                "lesson": "15/08",
                "expected_readiness": "ready_for_tree_ensemble_lesson",
            },
            {
                "id": "ensemble_report",
                "lesson": "15/09",
                "expected_readiness": "ready_for_cross_validation_lesson",
            },
            {
                "id": "cv_report",
                "lesson": "15/10",
                "expected_readiness": "ready_for_imbalance_lesson",
            },
            {
                "id": "imbalance_report",
                "lesson": "15/11",
                "expected_readiness": "ready_for_calibration_lesson",
            },
            {
                "id": "calibration_report",
                "lesson": "15/12",
                "expected_readiness": "ready_for_leakage_lesson",
            },
            {
                "id": "leakage_report",
                "lesson": "15/13",
                "expected_readiness": "ready_for_error_analysis_lesson",
            },
            {
                "id": "error_analysis_report",
                "lesson": "15/14",
                "expected_readiness": "ready_for_model_card_lesson",
            },
        ],
        "required_evidence_tables": [
            "column_transformer_feature_schema",
            "ensemble_feature_importance",
            "class_distribution",
            "imbalance_threshold_report",
            "calibration_metrics",
            "calibration_threshold_impact",
            "forbidden_feature_report",
            "model_selection_audit",
            "confusion_rows",
            "slice_metrics",
            "small_n_warnings",
            "hidden_failure_slices",
            "error_examples",
        ],
        "model_card_sections": [
            "model_details",
            "intended_use",
            "out_of_scope_uses",
            "training_data",
            "evaluation_data",
            "metrics",
            "calibration",
            "error_analysis",
            "limitations",
            "ethical_considerations",
            "decision",
            "maintenance",
        ],
        "model_card_policy": {
            "intended_use": "prioritize support review for eligible trial users",
            "primary_users": ["support_ops", "product_analytics", "ml_analytics"],
            "out_of_scope_uses": [
                "causal_effect_of_offer",
                "automatic_account_action",
                "production_deployment_without_monitoring",
                "segment_readiness_claim_from_overall_metric",
            ],
            "claim_boundary": (
                "The package documents a churn-risk baseline. It does not estimate the "
                "causal effect of a retention offer and does not approve automated actions."
            ),
        },
        "decision_policy": {
            "valid_with_warnings_status": "review_required_before_production",
            "allowed_package_claim": "baseline_package_ready_for_review",
            "forbidden_claims": [
                "production_ready",
                "causal_offer_effect",
                "segment_ready_from_overall_metric",
                "fully_automated_retention_decision",
            ],
            "allowed_actions": [
                "ship_baseline_package_for_review",
                "plan_offer_effect_experiment",
                "collect_larger_evaluation_sample",
                "prepare_phase_16_model_improvement",
            ],
            "blocked_actions": [
                "auto_deploy_model",
                "hide_small_n_slices",
                "drop_hidden_failure_slices",
                "choose_threshold_on_test",
            ],
            "production_requires": [
                "larger_test_sample",
                "monitoring_plan",
                "owner_signoff",
                "security_review_for_model_artifact",
                "experiment_or_causal_design_for_offer_effect",
            ],
        },
        "risk_policy": {
            "propagate_upstream_warnings": True,
            "hidden_failure_blocks_production_claim": True,
            "small_n_blocks_segment_claim": True,
            "require_no_test_selection": True,
            "require_no_causal_offer_claim": True,
            "pickle_security_notice_required": True,
            "hash_algorithm": "sha256",
        },
        "output": {
            "package_file": "ml_baseline_package.json",
            "report_file": "ml_baseline_package_report.json",
            "model_card_file": "model_card.md",
            "decision_report_file": "decision_report.md",
            "evidence_matrix_file": "evidence_matrix.csv",
            "risk_register_file": "risk_register.csv",
            "audit_file": "model_card_policy_audit.csv",
            "manifest_file": "ml_baseline_package_manifest.json",
        },
    }


def problem_spec() -> dict[str, object]:
    return {
        "problem_id": "trial-churn-risk-7d-before-end",
        "business_decision": (
            "Rank eligible trial users seven days before trial end so support can spend a "
            "limited retention-offer budget on users with high churn risk."
        ),
        "prediction_unit": {
            "entity": "user_trial_snapshot",
            "key": "snapshot_id",
            "one_row_per": "user_id + prediction_time",
            "available_at_column": "prediction_time",
        },
        "target_name": "churn_14d",
        "target_definition": {
            "label_table": "ml_labels",
            "label_key": "snapshot_id",
            "target_column": "churned_14d",
            "horizon_days": 14,
            "horizon_start": "prediction_time",
            "label_available_column": "label_observed_at",
            "complete_flag_column": "label_window_complete",
        },
        "positive_class": {
            "value": True,
            "meaning": "user churned within 14 days after prediction_time",
        },
        "negative_class": {
            "value": False,
            "meaning": "user did not churn within 14 days after prediction_time",
        },
        "prediction_time": {
            "column": "prediction_time",
            "relative_to_trial_end_days": 7,
            "timezone": "Europe/Moscow",
        },
        "label_window": {
            "start": "prediction_time",
            "duration_days": 14,
            "complete_flag_column": "label_window_complete",
        },
        "eligible_population": {
            "population_id": "eligible_trial_users_7d_before_trial_end",
            "criteria": [
                {"field": "eligible_for_offer", "operator": "==", "value": True},
                {"field": "days_until_trial_end", "operator": "==", "value": 7},
            ],
        },
        "decision_action": "send_one_retention_offer_or_no_offer",
        "decision_budget": {"unit": "offers_per_scoring_batch", "max_actions": 2},
        "business_costs": {
            "false_positive": "offer budget spent on a user who would not churn",
            "false_negative": "missed high-risk user who churns without intervention",
        },
        "allowed_feature_sources": [
            "user_profile",
            "subscription_snapshot",
            "events_lookback_14d",
            "orders_lookback_30d",
            "support_tickets_before_prediction",
            "calendar_trial_end",
        ],
        "forbidden_feature_sources": [
            "cancellation_events_after_prediction",
            "retention_offer_outcomes",
            "churn_label",
        ],
        "split_policy": {
            "split_type": "group_time_aware",
            "group_key": "user_id",
            "time_key": "prediction_time",
            "validation_role": "model_and_threshold_selection",
            "test_role": "final_once_only_evaluation",
        },
        "baseline_policy": {
            "required_baselines": ["dummy_majority", "logistic_regression"],
            "candidate_must_beat": "dummy_majority",
        },
        "metric_policy": {
            "primary_metric": "precision_at_offer_budget",
            "secondary_metrics": ["recall", "pr_auc", "roc_auc", "log_loss"],
            "accuracy_role": "diagnostic_only",
            "cost_weights": {
                "false_positive": 1.0,
                "false_negative": 5.0,
                "unit": "relative_error_cost",
            },
        },
        "threshold_policy": {
            "selection_data": "validation",
            "rule": "min_error_cost_under_offer_budget",
            "budget_key": "decision_budget.max_actions",
        },
        "calibration_policy": {
            "required": True,
            "checks": ["calibration_bins", "brier_score", "log_loss"],
        },
        "segment_policy": {
            "required_slices": ["segment_id", "platform", "country"],
            "small_n_action": "warn_not_hide",
        },
        "model_card_policy": {
            "intended_use": "prioritize support review for eligible trial users",
            "out_of_scope_uses": ["causal_effect_of_offer", "automatic_account_action"],
            "claim_boundary": (
                "The score estimates churn risk and does not estimate the causal effect of "
                "a retention offer."
            ),
        },
        "known_limitations": [
            "tiny profile is for contract validation, not production model selection",
            "offer effectiveness requires experiment or causal design",
        ],
        "rerun_instructions": (
            "Run outputs/ml_problem_spec_validator.py with problem_spec.json, snapshots, "
            "labels and feature_source_inventory.csv."
        ),
    }


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_profile(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    write_csv(
        output / "ml_scoring_snapshots.csv",
        SNAPSHOTS,
        [
            "snapshot_id",
            "user_id",
            "prediction_time",
            "trial_end_at",
            "segment_id",
            "plan_id",
            "country",
            "platform",
            "eligible_for_offer",
            "days_until_trial_end",
            "split_group",
        ],
    )
    write_csv(
        output / "ml_labels.csv",
        LABELS,
        [
            "snapshot_id",
            "target_name",
            "label_observed_at",
            "churned_14d",
            "label_window_complete",
        ],
    )
    write_csv(
        output / "feature_source_inventory.csv",
        FEATURE_SOURCES,
        [
            "source_id",
            "source_table",
            "timing",
            "available_at_policy",
            "max_observed_at",
            "allowed",
            "reason",
        ],
    )
    write_csv(
        output / "ml_feature_availability.csv",
        ML_FEATURE_AVAILABILITY,
        [
            "feature_name",
            "source_id",
            "source_table",
            "feature_role",
            "timing",
            "available_at_policy",
            "max_observed_at",
            "used_in_delivery_model",
            "risk_type",
            "notes",
        ],
    )
    write_csv(
        output / "ml_feature_selection_log.csv",
        ML_FEATURE_SELECTION_LOG,
        [
            "selector_id",
            "selector_kind",
            "scope",
            "fit_split",
            "uses_labels",
            "uses_validation_labels",
            "uses_test_labels",
            "inside_pipeline",
            "inside_cv",
            "selected_for_delivery",
            "status",
            "notes",
        ],
    )
    write_csv(
        output / "ml_model_selection_log.csv",
        ML_MODEL_SELECTION_LOG,
        [
            "candidate_id",
            "candidate_family",
            "selection_stage",
            "selection_split",
            "validation_precision_at_budget",
            "test_precision_at_budget",
            "test_metric_visible_to_selector",
            "selected_for_delivery",
            "selection_rank",
            "status",
            "notes",
        ],
    )
    write_csv(
        output / "ml_split_manifest.csv",
        SPLIT_MANIFEST,
        [
            "snapshot_id",
            "user_id",
            "prediction_time",
            "split",
            "split_order",
            "role",
            "assigned_by_policy",
        ],
    )
    write_csv(
        output / "ml_candidate_scores.csv",
        SCORES,
        [
            "snapshot_id",
            "model_id",
            "score",
            "score_type",
            "trained_on_split",
            "generated_at",
        ],
    )
    write_csv(
        output / "ml_cv_fold_manifest.csv",
        CV_FOLD_ROWS,
        [
            "fold_id",
            "fold_order",
            "snapshot_id",
            "user_id",
            "prediction_time",
            "original_split",
            "cv_role",
            "group_key",
            "label",
            "assigned_by_policy",
        ],
    )
    write_csv(
        output / "ml_raw_features.csv",
        RAW_FEATURES,
        [
            "snapshot_id",
            "sessions_14d",
            "active_days_14d",
            "support_tickets_14d",
            "revenue_30d",
            "days_since_signup",
            "had_support_ticket_14d",
            "plan_id",
            "platform",
            "country",
            "acquisition_channel",
        ],
    )
    (output / "problem_spec.json").write_text(
        json.dumps(problem_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "preprocessing_contract.json").write_text(
        json.dumps(preprocessing_contract(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "pipeline_spec.json").write_text(
        json.dumps(pipeline_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "column_transformer_spec.json").write_text(
        json.dumps(column_transformer_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "linear_baseline_spec.json").write_text(
        json.dumps(linear_baseline_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "tree_diagnostic_spec.json").write_text(
        json.dumps(tree_diagnostic_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "tree_ensemble_spec.json").write_text(
        json.dumps(tree_ensemble_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "cv_plan_spec.json").write_text(
        json.dumps(cv_plan_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "imbalance_policy_spec.json").write_text(
        json.dumps(imbalance_policy_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "calibration_policy_spec.json").write_text(
        json.dumps(calibration_policy_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "leakage_policy_spec.json").write_text(
        json.dumps(leakage_policy_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "error_analysis_policy_spec.json").write_text(
        json.dumps(error_analysis_policy_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "ml_baseline_package_spec.json").write_text(
        json.dumps(ml_baseline_package_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    files = {}
    for path in sorted(output.iterdir()):
        if path.name == "manifest.json" or not path.is_file():
            continue
        files[path.name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    manifest = {
        "profile": "tiny",
        "generated_at": "2026-07-01T00:00:00Z",
        "generator": "phases/15-applied-machine-learning/data/generate_data.py",
        "files": files,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def check_profile(output: Path) -> None:
    before = {
        path.name: path.read_bytes()
        for path in output.iterdir()
        if path.is_file() and path.name != "manifest.json"
    }
    write_profile(output)
    after = {
        path.name: path.read_bytes()
        for path in output.iterdir()
        if path.is_file() and path.name != "manifest.json"
    }
    if before != after:
        raise SystemExit("Generated tiny data differs from committed files.")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for filename, metadata in manifest["files"].items():
        digest = sha256(output / filename)
        if digest != metadata["sha256"]:
            raise SystemExit(f"Checksum mismatch for {filename}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate phase 15 deterministic ML data")
    parser.add_argument("--profile", choices=["tiny"], default="tiny")
    parser.add_argument("--output", type=Path, default=ROOT / "tiny")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check_profile(args.output)
        print("Phase 15 tiny data is reproducible.")
    else:
        write_profile(args.output)
        print(f"Generated {args.profile} data in {args.output}")


if __name__ == "__main__":
    main()
