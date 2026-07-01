from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
BUSINESS_TZ = ZoneInfo("Europe/Moscow")
START = date(2026, 3, 2)
END = date(2026, 3, 17)
COMPLETE_THROUGH = date(2026, 3, 16)
FORECAST_ORIGIN = "2026-03-18T09:00:00+03:00"
BACKTEST_START = date(2026, 2, 2)
BACKTEST_END = COMPLETE_THROUGH
OPENING_BALANCES = {"all": 980, "android": 310}


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def period_start_at(day: date) -> str:
    local_midnight = datetime(day.year, day.month, day.day, tzinfo=BUSINESS_TZ)
    return local_midnight.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def subscription_event_at(day: date) -> str:
    local_time = datetime(day.year, day.month, day.day, 0, 30, tzinfo=BUSINESS_TZ)
    return local_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def available_at(day: date, segment_id: str) -> str:
    minute = 10 if segment_id == "all" else 20
    return datetime(day.year, day.month, day.day, 9, minute, tzinfo=BUSINESS_TZ).isoformat()


def metric_value(day: date, index: int, segment_id: str) -> int:
    if segment_id == "all":
        weekday_bump = 18 if day.weekday() in {0, 1, 2, 3, 4} else -22
        campaign_bump = 12 if date(2026, 3, 9) <= day <= date(2026, 3, 13) else 0
        return 980 + 9 * index + weekday_bump + campaign_bump
    if segment_id == "android":
        weekday_bump = 8 if day.weekday() in {0, 1, 2, 3, 4} else -9
        return 310 + 4 * index + weekday_bump
    raise ValueError(f"unknown segment: {segment_id}")


def metric_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, day in enumerate(daterange(START, END)):
        for metric_id, segment_id, value, denominator in (
            ("active_subscriptions", "all", metric_value(day, index, "all"), 1200 + 8 * index),
            ("active_subscriptions", "android", metric_value(day, index, "android"), 420 + 3 * index),
        ):
            published_at = datetime(
                day.year,
                day.month,
                day.day,
                9,
                15 if segment_id == "all" else 35,
                tzinfo=BUSINESS_TZ,
            ).isoformat()
            rows.append(
                {
                    "metric_id": metric_id,
                    "segment_id": segment_id,
                    "observed_date": day.isoformat(),
                    "period_start_at": period_start_at(day),
                    "published_at": published_at,
                    "value": value,
                    "denominator": denominator,
                    "is_complete_period": str(day <= COMPLETE_THROUGH).lower(),
                    "revision_number": 1,
                    "source_status": "partial" if day > COMPLETE_THROUGH else "ok",
                }
            )
    return rows


def backtest_observation_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for day in daterange(BACKTEST_START, BACKTEST_END):
        index = (day - START).days
        for segment_id in ("all", "android"):
            rows.append(
                {
                    "metric_id": "active_subscriptions",
                    "segment_id": segment_id,
                    "observed_date": day.isoformat(),
                    "frequency": "D",
                    "value": metric_value(day, index, segment_id),
                    "is_complete_period": "true",
                    "include_in_backtest": "true",
                }
            )
    return rows


def subscription_event_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    previous = dict(OPENING_BALANCES)
    for index, day in enumerate(daterange(START, END)):
        for segment_id in ("all", "android"):
            current = metric_value(day, index, segment_id)
            delta = current - previous[segment_id]
            previous[segment_id] = current
            rows.append(
                {
                    "event_id": f"sub-delta-{segment_id}-{day.isoformat()}",
                    "segment_id": segment_id,
                    "occurred_at": subscription_event_at(day),
                    "available_at": available_at(day, segment_id),
                    "event_type": "active_subscription_delta",
                    "delta_active": delta,
                    "source_system": "subscription_ledger",
                    "ingestion_status": "partial" if day > COMPLETE_THROUGH else "ok",
                }
            )
    return rows


def calendar_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for day in daterange(date(2026, 3, 2), date(2026, 4, 14)):
        campaign_active = date(2026, 3, 20) <= day <= date(2026, 3, 27)
        release_active = date(2026, 3, 10) <= day <= date(2026, 3, 12)
        week_start = day - timedelta(days=day.weekday())
        rows.append(
            {
                "date": day.isoformat(),
                "week_start": week_start.isoformat(),
                "day_of_week": day.strftime("%A"),
                "is_weekend": str(day.weekday() >= 5).lower(),
                "is_holiday": str(day == date(2026, 3, 8)).lower(),
                "holiday_name": "spring_promo_day" if day == date(2026, 3, 8) else "",
                "campaign_active": str(campaign_active).lower(),
                "release_active": str(release_active).lower(),
                "payday_week": str(day.isocalendar().week in {10, 14}).lower(),
                "support_capacity": 44 if release_active else 38,
                "known_before_date": (day - timedelta(days=14)).isoformat(),
            }
        )
    return rows


def release_rows() -> list[dict[str, object]]:
    return [
        {
            "release_id": "android-2026-03-support-ui",
            "platform": "android",
            "start_date": "2026-03-10",
            "end_date": "2026-03-12",
            "known_before_date": "2026-02-24",
            "expected_metric_impact": "support_tickets_up",
        }
    ]


def campaign_rows() -> list[dict[str, object]]:
    return [
        {
            "campaign_id": "spring-marketplace-push",
            "start_date": "2026-03-20",
            "end_date": "2026-03-27",
            "known_before_date": "2026-03-01",
            "target_segment": "all",
        }
    ]


def revision_rows() -> list[dict[str, object]]:
    return [
        {
            "metric_id": "active_subscriptions",
            "segment_id": "all",
            "observed_date": "2026-03-12",
            "revision_number": 2,
            "previous_value": 1100,
            "revised_value": 1097,
            "first_published_at": "2026-03-12T09:15:00+03:00",
            "revised_at": "2026-03-18T08:30:00Z",
            "revision_reason": "late_refund_reconciliation",
        }
    ]


def forecast_scenario() -> dict[str, object]:
    return {
        "forecast_id": "active-subscriptions-4w-capacity",
        "business_decision": "Decide support capacity and rollout guardrails for the spring campaign.",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "time_column": "observed_date",
        "timestamp_column": "period_start_at",
        "timezone": "Europe/Moscow",
        "frequency": "D",
        "expected_start": START.isoformat(),
        "complete_through": COMPLETE_THROUGH.isoformat(),
        "forecast_origin": FORECAST_ORIGIN,
        "horizon_days": 28,
        "calendar_start": "2026-03-02",
        "calendar_end": "2026-04-14",
        "revision_policy": "warn_after_origin",
        "quality_gates": [
            "unique_metric_segment_date",
            "complete_daily_calendar",
            "timezone_bucket_matches_observed_date",
            "no_missing_complete_dates",
        ],
    }


def resampling_spec() -> dict[str, object]:
    return {
        "resampling_id": "active-subscriptions-daily-weekly",
        "source_table": "subscription_events",
        "source_time_column": "occurred_at",
        "availability_column": "available_at",
        "segment_column": "segment_id",
        "value_column": "delta_active",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "timezone": "Europe/Moscow",
        "expected_start": START.isoformat(),
        "complete_through": COMPLETE_THROUGH.isoformat(),
        "forecast_origin": FORECAST_ORIGIN,
        "daily_frequency": "D",
        "week_start_day": "Monday",
        "weekly_label": "left",
        "weekly_closed": "left",
        "stock_aggregation": "opening_balance_plus_cumulative_delta",
        "weekly_stock_policy": "last_complete_observation",
        "opening_balances": OPENING_BALANCES,
        "complete_period_policy": "exclude_after_complete_through",
        "partial_period_policy": "warn_and_exclude_from_training",
        "reconciliation_tolerance": 0,
        "quality_gates": [
            "event_id_unique",
            "timezone_normalized_business_date",
            "weekly_label_closed_left",
            "published_series_reconciles",
            "partial_periods_excluded",
        ],
    }


def window_feature_spec() -> dict[str, object]:
    return {
        "feature_set_id": "active-subscriptions-rolling-features",
        "source_table": "daily_resampled",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "time_column": "observed_date",
        "value_column": "value",
        "delta_column": "delta_active",
        "complete_flag_column": "include_in_training",
        "timezone": "Europe/Moscow",
        "frequency": "D",
        "expected_start": START.isoformat(),
        "complete_through": COMPLETE_THROUGH.isoformat(),
        "forecast_origin": FORECAST_ORIGIN,
        "feature_date_policy": "features_use_strictly_past_observations",
        "warmup_policy": "emit_rows_but_exclude_from_training",
        "partial_period_policy": "emit_rows_but_exclude_from_training",
        "rules": [
            {
                "name": "value_lag_1",
                "kind": "lag",
                "input_column": "value",
                "lag": 1,
                "required": True,
            },
            {
                "name": "delta_lag_1",
                "kind": "lag",
                "input_column": "delta_active",
                "lag": 1,
                "required": True,
            },
            {
                "name": "rolling_3_mean_lag1",
                "kind": "rolling_mean",
                "input_column": "value",
                "window": 3,
                "lag": 1,
                "min_periods": 3,
                "center": False,
                "required": True,
            },
            {
                "name": "rolling_7_mean_lag1",
                "kind": "rolling_mean",
                "input_column": "value",
                "window": 7,
                "lag": 1,
                "min_periods": 7,
                "center": False,
                "required": True,
            },
            {
                "name": "expanding_mean_lag1",
                "kind": "expanding_mean",
                "input_column": "value",
                "lag": 1,
                "min_periods": 3,
                "required": True,
            },
        ],
        "quality_gates": [
            "source_segment_date_unique",
            "complete_history_has_no_missing_dates",
            "feature_rules_are_past_only",
            "feature_source_dates_precede_feature_date",
            "warmup_rows_excluded",
            "partial_source_rows_excluded",
        ],
    }


def seasonality_profile_spec() -> dict[str, object]:
    return {
        "profile_id": "active-subscriptions-seasonality-profile",
        "source_table": "daily_resampled",
        "calendar_table": "calendar",
        "campaign_table": "campaign_calendar",
        "release_table": "release_calendar",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "time_column": "observed_date",
        "value_column": "value",
        "delta_column": "delta_active",
        "complete_flag_column": "include_in_training",
        "calendar_date_column": "date",
        "timezone": "Europe/Moscow",
        "frequency": "D",
        "expected_start": START.isoformat(),
        "complete_through": COMPLETE_THROUGH.isoformat(),
        "forecast_origin": FORECAST_ORIGIN,
        "seasonal_period_days": 7,
        "trend_policy": "fit_linear_trend_on_complete_training_rows",
        "seasonality_policy": "profile_complete_history_by_calendar_keys",
        "calendar_effect_policy": "known_before_forecast_origin_only",
        "minimum_observations_per_weekday": 2,
        "minimum_month_cycles": 2,
        "profile_dimensions": ["day_of_week", "month"],
        "calendar_effect_columns": ["is_holiday", "campaign_active", "release_active"],
        "quality_gates": [
            "source_segment_date_unique",
            "calendar_date_unique",
            "calendar_covers_history_and_horizon",
            "complete_history_has_no_missing_dates",
            "calendar_effects_known_before_origin",
            "calendar_flags_cover_declared_events",
            "partial_rows_excluded",
            "monthly_profile_needs_multiple_cycles",
        ],
    }


def temporal_leakage_spec() -> dict[str, object]:
    return {
        "leakage_audit_id": "active-subscriptions-temporal-leakage",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "timezone": "Europe/Moscow",
        "frequency": "D",
        "expected_start": START.isoformat(),
        "complete_through": COMPLETE_THROUGH.isoformat(),
        "forecast_origin": FORECAST_ORIGIN,
        "horizon_days": 28,
        "split_plan": {
            "split_id": "origin-2026-03-18",
            "split_type": "time_ordered_cutoff",
            "training_start": START.isoformat(),
            "training_end": COMPLETE_THROUGH.isoformat(),
            "first_forecast_date": "2026-03-18",
            "embargo_dates": ["2026-03-17"],
            "horizon_end": "2026-04-14",
        },
        "revision_policy": "exclude_revisions_after_forecast_origin",
        "known_future_feature_policy": "require_known_before_forecast_origin",
        "forbidden_availability_types": [
            "target_at_feature_date",
            "future_target",
            "centered_window",
            "full_sample_statistic",
            "random_split",
            "backfilled_revision_after_origin",
            "post_cutoff_observation",
        ],
        "candidate_features": [
            {
                "name": "value_lag_1",
                "source": "window_features",
                "availability_type": "past_observation",
                "selected": True,
                "required_evidence": "leakage_audit",
            },
            {
                "name": "rolling_7_mean_lag1",
                "source": "window_features",
                "availability_type": "past_observation",
                "selected": True,
                "required_evidence": "leakage_audit",
            },
            {
                "name": "day_of_week",
                "source": "calendar",
                "availability_type": "known_future_calendar",
                "selected": True,
                "required_evidence": "known_before_date",
            },
            {
                "name": "campaign_active",
                "source": "calendar",
                "availability_type": "known_future_calendar",
                "selected": True,
                "required_evidence": "known_before_date",
            },
            {
                "name": "current_value",
                "source": "daily_resampled.value",
                "availability_type": "target_at_feature_date",
                "selected": False,
                "required_evidence": "forbidden_target",
            },
            {
                "name": "future_value_t_plus_1",
                "source": "daily_resampled.value",
                "availability_type": "future_target",
                "selected": False,
                "required_evidence": "forbidden_future_target",
            },
            {
                "name": "centered_rolling_7_mean",
                "source": "derived_window",
                "availability_type": "centered_window",
                "selected": False,
                "required_evidence": "forbidden_centered_window",
            },
            {
                "name": "full_sample_zscore",
                "source": "full_sample_transform",
                "availability_type": "full_sample_statistic",
                "selected": False,
                "required_evidence": "forbidden_full_sample_statistic",
            },
            {
                "name": "random_split_fold",
                "source": "model_selection",
                "availability_type": "random_split",
                "selected": False,
                "required_evidence": "forbidden_random_split",
            },
            {
                "name": "revised_value_after_origin",
                "source": "data_revisions",
                "availability_type": "backfilled_revision_after_origin",
                "selected": False,
                "required_evidence": "forbidden_backfill",
            },
        ],
        "quality_gates": [
            "scenario_and_leakage_spec_align",
            "split_plan_is_time_ordered",
            "training_rows_end_at_complete_through",
            "embargo_dates_are_not_training_rows",
            "selected_features_are_available_at_cutoff",
            "selected_features_do_not_use_forbidden_availability",
            "known_future_features_known_before_origin",
            "window_features_have_past_only_audit",
            "revisions_after_origin_are_excluded",
        ],
    }


def baseline_forecast_spec() -> dict[str, object]:
    return {
        "baseline_id": "active-subscriptions-baselines",
        "forecast_id": "active-subscriptions-4w-capacity",
        "source_table": "daily_resampled",
        "cutoff_contract_id": "active-subscriptions-temporal-leakage",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "time_column": "observed_date",
        "value_column": "value",
        "training_start": START.isoformat(),
        "training_end": COMPLETE_THROUGH.isoformat(),
        "first_forecast_date": "2026-03-18",
        "horizon_end": "2026-04-14",
        "horizon_days": 28,
        "timezone": "Europe/Moscow",
        "frequency": "D",
        "seasonal_period_days": 7,
        "embargo_dates": ["2026-03-17"],
        "primary_baseline_model": "seasonal_naive_7",
        "baseline_policy": {
            "candidate_model_must_beat": "seasonal_naive_7",
            "comparison_scope": "same_cutoffs_segments_horizon_and_metric",
            "selection_metric": "MASE",
            "simple_baselines_do_not_apply_calendar_uplift": True,
            "require_forecast_trace": True,
        },
        "models": [
            {
                "model_id": "naive",
                "kind": "naive",
                "description": "Repeat the last complete training value for every horizon date.",
                "minimum_training_points": 1,
                "anchor_policy": "last_complete_training_observation",
            },
            {
                "model_id": "seasonal_naive_7",
                "kind": "seasonal_naive",
                "description": "Repeat the most recent complete observation with the same weekday.",
                "minimum_training_points": 7,
                "seasonal_period_days": 7,
                "anchor_policy": "last_complete_same_weekday_observation",
            },
            {
                "model_id": "drift",
                "kind": "drift",
                "description": "Extend the first-to-last complete training slope by calendar days after training_end.",
                "minimum_training_points": 2,
                "anchor_policy": "first_and_last_complete_training_observations",
            },
            {
                "model_id": "moving_average_7",
                "kind": "moving_average",
                "description": "Repeat the mean of the last seven complete training values.",
                "minimum_training_points": 7,
                "window_days": 7,
                "anchor_policy": "last_7_complete_training_observations",
            },
        ],
        "quality_gates": [
            "scenario_cutoff_and_baseline_spec_align",
            "cutoff_contract_is_time_ordered",
            "training_rows_match_cutoff",
            "forecast_horizon_matches_contract",
            "baseline_models_declared",
            "seasonal_period_is_precommitted",
            "enough_history_for_declared_models",
            "no_embargo_or_future_rows_used_as_anchors",
            "forecast_trace_anchors_are_training_rows",
            "forecast_table_has_full_horizon",
            "one_forecast_per_segment_model_date",
            "primary_baseline_declared",
        ],
    }


def decomposition_spec() -> dict[str, object]:
    return {
        "decomposition_id": "active-subscriptions-stl-decomposition",
        "forecast_id": "active-subscriptions-4w-capacity",
        "source_table": "daily_resampled",
        "cutoff_contract_id": "active-subscriptions-temporal-leakage",
        "baseline_id": "active-subscriptions-baselines",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "time_column": "observed_date",
        "value_column": "value",
        "complete_flag_column": "include_in_training",
        "training_start": START.isoformat(),
        "training_end": COMPLETE_THROUGH.isoformat(),
        "forecast_origin": FORECAST_ORIGIN,
        "timezone": "Europe/Moscow",
        "frequency": "D",
        "seasonal_period_days": 7,
        "component_model": "additive",
        "method": "STL",
        "robust": True,
        "minimum_training_points": 15,
        "minimum_cycles_for_decision": 3,
        "residual_diagnostics": {
            "mean_abs_tolerance": 1.0,
            "lag1_autocorrelation_abs_limit": 0.8,
            "reconstruction_abs_tolerance": 0.000001,
        },
        "interpretation_policy": {
            "additive_when_seasonal_amplitude_is_stable": True,
            "multiplicative_requires_positive_values_and_stable_relative_amplitude": True,
            "decomposition_is_diagnostic_not_forecast_evidence": True,
            "candidate_models_still_must_beat_baseline": "seasonal_naive_7",
        },
        "quality_gates": [
            "scenario_cutoff_baseline_and_decomposition_spec_align",
            "source_segment_date_unique",
            "training_rows_match_cutoff",
            "decomposition_uses_training_window_only",
            "seasonal_period_is_precommitted",
            "enough_history_for_stl",
            "component_table_reconstructs_observed",
            "one_component_row_per_segment_date",
            "residual_diagnostics_emitted",
            "short_history_blocks_accuracy_claim",
        ],
    }


def statsmodels_model_spec() -> dict[str, object]:
    return {
        "model_run_id": "active-subscriptions-statsmodels-candidates",
        "forecast_id": "active-subscriptions-4w-capacity",
        "source_table": "daily_resampled",
        "cutoff_contract_id": "active-subscriptions-temporal-leakage",
        "baseline_id": "active-subscriptions-baselines",
        "decomposition_id": "active-subscriptions-stl-decomposition",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "time_column": "observed_date",
        "value_column": "value",
        "complete_flag_column": "include_in_training",
        "training_start": START.isoformat(),
        "training_end": COMPLETE_THROUGH.isoformat(),
        "forecast_origin": FORECAST_ORIGIN,
        "first_forecast_date": "2026-03-18",
        "horizon_end": "2026-04-14",
        "horizon_days": 28,
        "timezone": "Europe/Moscow",
        "frequency": "D",
        "seasonal_period_days": 7,
        "embargo_dates": ["2026-03-17"],
        "primary_baseline_model": "seasonal_naive_7",
        "uses_exogenous_calendar_features": False,
        "minimum_cycles_for_model_selection": 3,
        "selection_policy": {
            "no_auto_model_search": True,
            "candidate_models_declared_before_evaluation": True,
            "do_not_select_on_in_sample_fit": True,
            "candidate_model_must_beat": "seasonal_naive_7",
            "comparison_scope": "same_cutoffs_segments_horizon_and_metric",
            "quality_metric_deferred_to": "14-time-series/10-forecast-metrics",
        },
        "candidate_models": [
            {
                "model_id": "ets_additive_trend_seasonal_7",
                "family": "ETS",
                "statsmodels_class": "ExponentialSmoothing",
                "trend": "add",
                "seasonal": "add",
                "seasonal_periods": 7,
                "damped_trend": False,
                "initialization_method": "estimated",
                "minimum_training_points": 15,
                "minimum_training_cycles": 2,
            },
            {
                "model_id": "arima_1_1_0",
                "family": "ARIMA",
                "statsmodels_class": "ARIMA",
                "order": [1, 1, 0],
                "seasonal_order": [0, 0, 0, 0],
                "trend": "n",
                "enforce_stationarity": False,
                "enforce_invertibility": False,
                "minimum_training_points": 10,
                "minimum_training_cycles": 2,
            },
        ],
        "residual_diagnostics": {
            "residual_mean_abs_warn": 80.0,
            "lag1_autocorrelation_abs_warn": 0.8,
        },
        "quality_gates": [
            "scenario_cutoff_baseline_decomposition_and_model_spec_align",
            "baseline_and_decomposition_reports_are_valid",
            "source_segment_date_unique",
            "training_rows_match_cutoff",
            "model_uses_training_window_only",
            "candidate_models_declared",
            "ets_and_arima_families_present",
            "no_auto_model_search",
            "orders_and_initialization_are_explicit",
            "enough_history_for_declared_candidates",
            "short_history_blocks_model_selection_claim",
            "statsmodels_warnings_propagated",
            "model_diagnostics_emitted",
            "forecast_table_has_full_horizon",
            "one_forecast_per_segment_model_date",
            "library_forecasts_match_baseline_shape",
        ],
    }


def backtesting_spec() -> dict[str, object]:
    return {
        "backtest_id": "active-subscriptions-rolling-origin-backtest",
        "forecast_id": "active-subscriptions-4w-capacity",
        "source_table": "backtest_observations",
        "upstream_model_run_id": "active-subscriptions-statsmodels-candidates",
        "baseline_id": "active-subscriptions-baselines",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "time_column": "observed_date",
        "value_column": "value",
        "timezone": "Europe/Moscow",
        "frequency": "D",
        "seasonal_period_days": 7,
        "primary_baseline_model": "seasonal_naive_7",
        "candidate_model_ids": ["ets_additive_trend_seasonal_7", "arima_1_1_0"],
        "baseline_model_ids": ["seasonal_naive_7"],
        "final_forecast_horizon_days": 28,
        "backtest_horizon_days": 3,
        "gap_days": 1,
        "minimum_origins_for_model_selection": 5,
        "retraining_policy": {
            "refit_each_origin": True,
            "reuse_final_forecast_fit": False,
            "model_selection_deferred_to": "14-time-series/10-forecast-metrics",
        },
        "split_plan": [
            {
                "split_id": "bt-expanding-2026-02-24",
                "window_type": "expanding",
                "forecast_origin": "2026-02-24T09:00:00+03:00",
                "training_start": "2026-02-02",
                "training_end": "2026-02-22",
                "embargo_dates": ["2026-02-23"],
                "first_forecast_date": "2026-02-24",
                "horizon_end": "2026-02-26",
            },
            {
                "split_id": "bt-expanding-2026-03-03",
                "window_type": "expanding",
                "forecast_origin": "2026-03-03T09:00:00+03:00",
                "training_start": "2026-02-02",
                "training_end": "2026-03-01",
                "embargo_dates": ["2026-03-02"],
                "first_forecast_date": "2026-03-03",
                "horizon_end": "2026-03-05",
            },
            {
                "split_id": "bt-rolling-2026-03-10",
                "window_type": "rolling",
                "forecast_origin": "2026-03-10T09:00:00+03:00",
                "training_start": "2026-02-16",
                "training_end": "2026-03-08",
                "embargo_dates": ["2026-03-09"],
                "first_forecast_date": "2026-03-10",
                "horizon_end": "2026-03-12",
            },
            {
                "split_id": "bt-rolling-2026-03-14",
                "window_type": "rolling",
                "forecast_origin": "2026-03-14T09:00:00+03:00",
                "training_start": "2026-02-20",
                "training_end": "2026-03-12",
                "embargo_dates": ["2026-03-13"],
                "first_forecast_date": "2026-03-14",
                "horizon_end": "2026-03-16",
            },
        ],
        "quality_gates": [
            "scenario_model_and_backtest_spec_align",
            "source_segment_date_unique",
            "split_ids_unique",
            "origins_are_time_ordered",
            "no_random_splits",
            "training_windows_precede_origins",
            "embargo_gap_is_respected",
            "forecast_horizon_is_fixed",
            "actuals_available_for_every_origin_horizon",
            "models_refit_each_origin",
            "forecast_table_has_full_horizon",
            "one_forecast_per_origin_segment_model_date",
            "small_origin_count_blocks_model_selection_claim",
        ],
    }


def forecast_metric_spec() -> dict[str, object]:
    return {
        "metric_evaluation_id": "active-subscriptions-forecast-metrics",
        "forecast_id": "active-subscriptions-4w-capacity",
        "backtest_id": "active-subscriptions-rolling-origin-backtest",
        "source_table": "backtest_errors",
        "backtest_report": "backtest_report",
        "history_table": "backtest_observations",
        "split_manifest": "split_manifest",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "primary_baseline_model": "seasonal_naive_7",
        "candidate_model_ids": ["ets_additive_trend_seasonal_7", "arima_1_1_0"],
        "required_metrics": ["mae", "rmse", "mape", "smape", "wape", "mase"],
        "primary_metric": "weighted_mase",
        "seasonal_period_days": 7,
        "segment_weights": {
            "all": 0.7,
            "android": 0.3,
        },
        "horizon_weighting": {
            "mode": "equal",
            "required_horizon_steps": [1, 2, 3],
        },
        "percentage_metric_policy": {
            "mape_decision_role": "diagnostic_only",
            "smape_decision_role": "diagnostic_only",
            "minimum_abs_actual_for_mape": 1.0,
            "minimum_abs_actual_plus_forecast_for_smape": 1.0,
            "zero_or_small_denominator_action": "mark_metric_blocked_not_package_invalid",
        },
        "leaderboard_policy": {
            "rank_by": "weighted_mase",
            "lower_is_better": True,
            "candidate_must_beat_baseline_by_relative": 0.05,
            "baseline_model_id": "seasonal_naive_7",
            "selection_requires_no_backtest_warnings": True,
            "selection_requires_all_segments_clear_baseline": True,
            "tiny_profile_decision_status": "diagnostic_leaderboard_not_production_selection",
        },
        "quality_gates": [
            "forecast_metric_spec_required_fields",
            "backtest_report_is_valid",
            "metric_spec_and_backtest_align",
            "backtest_errors_required_columns",
            "backtest_error_grain_unique",
            "segment_weights_cover_targets_and_sum_to_one",
            "horizon_steps_match_policy",
            "mase_denominator_positive",
            "percentage_metrics_not_primary_decision_metric",
            "percentage_denominators_are_safe_or_blocked",
            "metric_table_contains_overall_segment_and_horizon_rows",
            "leaderboard_uses_primary_metric_and_baseline",
            "leaderboard_policy_blocks_selection_when_backtest_warnings_exist",
        ],
    }


def prediction_interval_spec() -> dict[str, object]:
    return {
        "interval_calibration_id": "active-subscriptions-prediction-intervals",
        "forecast_id": "active-subscriptions-4w-capacity",
        "backtest_id": "active-subscriptions-rolling-origin-backtest",
        "metric_evaluation_id": "active-subscriptions-forecast-metrics",
        "model_run_id": "active-subscriptions-statsmodels-candidates",
        "baseline_id": "active-subscriptions-baselines",
        "source_errors_table": "backtest_errors",
        "final_baseline_forecasts": "baseline_forecasts",
        "final_candidate_forecasts": "candidate_forecasts",
        "backtest_report": "backtest_report",
        "metric_report": "metric_report",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "interval_model_ids": ["seasonal_naive_7", "ets_additive_trend_seasonal_7", "arima_1_1_0"],
        "primary_interval_method": "residual_quantile",
        "coverage_target": 0.9,
        "alpha": 0.1,
        "minimum_backtest_rows_per_group": 4,
        "minimum_origins_for_coverage_claim": 5,
        "calibration_grain": ["model_id", "segment_id", "horizon_step"],
        "horizon_policy": {
            "calibrated_horizon_steps": [1, 2, 3],
            "final_forecast_horizon_days": 28,
            "beyond_calibrated_horizon": "reuse_last_calibrated_step_and_warn",
        },
        "methods": [
            {
                "method_id": "residual_quantile",
                "family": "residual",
                "decision_role": "primary",
                "interval_type": "symmetric_absolute_residual_quantile",
                "absolute_error_quantile": 0.9,
            },
            {
                "method_id": "residual_bootstrap",
                "family": "bootstrap",
                "decision_role": "comparison",
                "interval_type": "signed_residual_percentile",
                "lower_quantile": 0.05,
                "upper_quantile": 0.95,
            },
            {
                "method_id": "model_based_normal",
                "family": "model_based",
                "decision_role": "diagnostic_only",
                "interval_type": "normal_residual_stddev",
                "scale": "sample_stddev_of_backtest_residuals",
            },
        ],
        "interval_policy": {
            "prediction_interval_not_confidence_interval": True,
            "point_forecast_requires_uncertainty_statement": True,
            "lower_bound_floor": 0.0,
            "coverage_below_target_action": "warn_for_diagnostic_methods_error_for_primary_method",
            "tiny_profile_decision_status": "diagnostic_intervals_not_production_sla",
        },
        "quality_gates": [
            "prediction_interval_spec_required_fields",
            "backtest_report_is_valid",
            "metric_report_is_valid",
            "interval_spec_and_reports_align",
            "backtest_errors_required_columns",
            "backtest_error_grain_unique",
            "final_forecasts_required_columns",
            "final_forecast_table_has_full_horizon",
            "interval_methods_declared",
            "calibration_groups_have_minimum_rows",
            "prediction_interval_not_confidence_interval",
            "primary_interval_coverage_meets_target",
            "diagnostic_model_based_undercoverage_is_warned",
            "point_forecasts_have_uncertainty_statement",
            "interval_horizon_shorter_than_final_forecast",
        ],
    }


def forecast_package_spec() -> dict[str, object]:
    return {
        "package_id": "active-subscriptions-forecast-package",
        "forecast_id": "active-subscriptions-4w-capacity",
        "target_metric": "active_subscriptions",
        "target_segments": ["all", "android"],
        "forecast_origin": FORECAST_ORIGIN,
        "horizon_days": 28,
        "primary_model_id": "ets_additive_trend_seasonal_7",
        "primary_interval_method": "residual_quantile",
        "required_reports": [
            "time_index_audit",
            "resampling_report",
            "window_feature_report",
            "seasonality_report",
            "temporal_leakage_report",
            "baseline_report",
            "model_report",
            "backtest_report",
            "metric_report",
            "interval_report",
        ],
        "required_tables": [
            "metric_observations",
            "calendar",
            "data_revisions",
            "interval_forecasts",
            "interval_coverage",
            "metric_leaderboard",
        ],
        "package_sections": [
            "scenario",
            "data",
            "features",
            "baselines",
            "models",
            "backtesting",
            "metrics",
            "intervals",
            "anomalies",
            "decision",
            "manifest",
        ],
        "anomaly_policy": {
            "labels": [
                "data_quality",
                "calendar_expected",
                "model_misspecification",
                "product_signal_candidate",
                "inconclusive",
            ],
            "gate_order": [
                "data_quality",
                "calendar_context",
                "interval_breach",
                "model_diagnostics",
                "business_review",
            ],
            "data_quality_statuses": ["partial", "late", "backfilled", "quality_hold"],
            "calendar_context_columns": ["is_holiday", "campaign_active", "release_active"],
            "product_signal_requires": [
                "actual_outside_primary_interval",
                "data_quality_clear",
                "no_known_calendar_context",
                "primary_interval_coverage_meets_target",
                "business_owner_review",
            ],
            "no_causal_claim_without_experiment": True,
        },
        "decision_policy": {
            "tiny_profile_status": "diagnostic_forecast_package_not_production_release",
            "warnings_block_production_release": True,
            "must_ship_checksum_manifest": True,
            "must_ship_decision_report": True,
            "point_forecast_requires_prediction_interval": True,
            "anomaly_detection_threshold_must_be_precommitted": True,
        },
        "quality_gates": [
            "forecast_package_spec_required_fields",
            "required_upstream_files_exist",
            "upstream_reports_are_valid",
            "forecast_ids_align",
            "primary_model_matches_metric_leaderboard",
            "primary_interval_method_matches_interval_report",
            "primary_interval_forecasts_exist",
            "data_quality_cases_not_product_signals",
            "calendar_context_cases_not_product_signals",
            "model_based_undercoverage_flagged_as_model_misspecification",
            "anomaly_policy_contains_all_labels",
            "decision_report_has_no_causal_claim",
            "checksum_manifest_covers_inputs_and_outputs",
        ],
    }


def write_profile(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    write_csv(
        output / "metric_observations.csv",
        metric_rows(),
        [
            "metric_id",
            "segment_id",
            "observed_date",
            "period_start_at",
            "published_at",
            "value",
            "denominator",
            "is_complete_period",
            "revision_number",
            "source_status",
        ],
    )
    write_csv(
        output / "backtest_observations.csv",
        backtest_observation_rows(),
        [
            "metric_id",
            "segment_id",
            "observed_date",
            "frequency",
            "value",
            "is_complete_period",
            "include_in_backtest",
        ],
    )
    write_csv(
        output / "subscription_events.csv",
        subscription_event_rows(),
        [
            "event_id",
            "segment_id",
            "occurred_at",
            "available_at",
            "event_type",
            "delta_active",
            "source_system",
            "ingestion_status",
        ],
    )
    write_csv(
        output / "calendar.csv",
        calendar_rows(),
        [
            "date",
            "week_start",
            "day_of_week",
            "is_weekend",
            "is_holiday",
            "holiday_name",
            "campaign_active",
            "release_active",
            "payday_week",
            "support_capacity",
            "known_before_date",
        ],
    )
    write_csv(
        output / "release_calendar.csv",
        release_rows(),
        [
            "release_id",
            "platform",
            "start_date",
            "end_date",
            "known_before_date",
            "expected_metric_impact",
        ],
    )
    write_csv(
        output / "campaign_calendar.csv",
        campaign_rows(),
        ["campaign_id", "start_date", "end_date", "known_before_date", "target_segment"],
    )
    write_csv(
        output / "data_revisions.csv",
        revision_rows(),
        [
            "metric_id",
            "segment_id",
            "observed_date",
            "revision_number",
            "previous_value",
            "revised_value",
            "first_published_at",
            "revised_at",
            "revision_reason",
        ],
    )
    (output / "forecast_scenario.json").write_text(
        json.dumps(forecast_scenario(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "resampling_spec.json").write_text(
        json.dumps(resampling_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "window_feature_spec.json").write_text(
        json.dumps(window_feature_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "seasonality_profile_spec.json").write_text(
        json.dumps(seasonality_profile_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "temporal_leakage_spec.json").write_text(
        json.dumps(temporal_leakage_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "baseline_forecast_spec.json").write_text(
        json.dumps(baseline_forecast_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "decomposition_spec.json").write_text(
        json.dumps(decomposition_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "statsmodels_model_spec.json").write_text(
        json.dumps(statsmodels_model_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "backtesting_spec.json").write_text(
        json.dumps(backtesting_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "forecast_metric_spec.json").write_text(
        json.dumps(forecast_metric_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "prediction_interval_spec.json").write_text(
        json.dumps(prediction_interval_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "forecast_package_spec.json").write_text(
        json.dumps(forecast_package_spec(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    files = {}
    for path in sorted(output.iterdir()):
        if path.name == "manifest.json" or not path.is_file():
            continue
        files[path.name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    manifest = {
        "profile": "tiny",
        "generated_at": "2026-06-30T00:00:00Z",
        "generator": "phases/14-time-series/data/generate_data.py",
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
    parser = argparse.ArgumentParser(description="Generate phase 14 deterministic data")
    parser.add_argument("--profile", choices=["tiny"], default="tiny")
    parser.add_argument("--output", type=Path, default=ROOT / "tiny")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        check_profile(args.output)
        print("Phase 14 tiny data is reproducible.")
    else:
        write_profile(args.output)
        print(f"Generated {args.profile} data in {args.output}")


if __name__ == "__main__":
    main()
