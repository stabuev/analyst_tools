from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats
from statsmodels.stats.proportion import confint_proportions_2indep, proportions_ztest


OBSERVATION_FIELDS = [
    "experiment_id",
    "user_id",
    "variant_id",
    "metric_id",
    "role",
    "metric_type",
    "observation_unit",
    "window_start",
    "window_end",
    "numerator",
    "denominator",
    "value",
]

EFFECT_FIELDS = [
    "metric_id",
    "role",
    "metric_type",
    "method",
    "control_units",
    "treatment_units",
    "control_denominator",
    "treatment_denominator",
    "control_value",
    "treatment_value",
    "absolute_lift",
    "relative_lift",
    "ci_low",
    "ci_high",
    "p_value",
    "alpha",
    "statistically_significant",
    "expected_direction",
    "practical_threshold",
    "practical_status",
    "guardrail_status",
    "decision_role",
    "decision_status",
    "assumption_status",
]

BINARY_EVENT_BY_METRIC = {
    "activation_rate_7d": "feature_value_seen",
    "paywall_to_trial_conversion_7d": "trial_started",
}


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: csv_value(row.get(field, "")) for field in fieldnames})


def csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return value


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.strip().lower() == "true"


def parse_time(value: str) -> datetime:
    if value.strip() == "":
        raise ValueError("empty timestamp")
    return datetime.fromisoformat(value)


def parse_float(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value.strip() == "":
        raise ValueError("empty numeric value")
    return float(value)


def round_float(value: float, digits: int = 6) -> float | str:
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return round(float(value), digits)


def ratio_or_inf(numerator: float, denominator: float) -> float:
    if denominator == 0:
        if numerator > 0:
            return math.inf
        if numerator < 0:
            return -math.inf
        return 0.0
    return numerator / denominator


def ordered_variants(protocol: dict[str, Any]) -> tuple[str, str]:
    control = next(item["variant_id"] for item in protocol["variants"] if item.get("is_control") is True)
    treatment = next(item["variant_id"] for item in protocol["variants"] if item.get("is_control") is False)
    return control, treatment


def metrics_by_id(metric_specs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {metric["metric_id"]: metric for metric in metric_specs["metrics"]}


def declared_metric_ids(protocol: dict[str, Any]) -> list[str]:
    return [
        protocol["primary_metric"],
        *protocol["guardrail_metrics"],
        *protocol["secondary_metrics"],
    ]


def index_rows(rows: list[dict[str, str]], key: str) -> dict[str, dict[str, str]]:
    return {row[key]: row for row in rows}


def rows_by_user(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["user_id"], []).append(row)
    return grouped


def in_window(timestamp: str, start: datetime, days: int) -> bool:
    if timestamp.strip() == "":
        return False
    value = parse_time(timestamp)
    return start <= value <= start + timedelta(days=days)


def unique_by_key(rows: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for row in rows:
        seen.setdefault(row[key], row)
    return list(seen.values())


def eligible_exposed_units(
    protocol: dict[str, Any],
    assignments: list[dict[str, str]],
    exposures: list[dict[str, str]],
    users: list[dict[str, str]],
) -> list[dict[str, Any]]:
    experiment_id = protocol["experiment_id"]
    users_by_id = index_rows(users, "user_id")
    exposure_by_user = {
        row["user_id"]: row
        for row in unique_by_key(
            [row for row in exposures if row.get("experiment_id") == experiment_id],
            "exposure_id",
        )
    }
    units: list[dict[str, Any]] = []
    for assignment in assignments:
        if assignment.get("experiment_id") != experiment_id or not parse_bool(assignment.get("is_eligible", "false")):
            continue
        user = users_by_id.get(assignment["user_id"])
        exposure = exposure_by_user.get(assignment["user_id"])
        if user is None or exposure is None:
            continue
        if parse_bool(user.get("is_test_user", "false")):
            continue
        units.append(
            {
                "experiment_id": experiment_id,
                "user_id": assignment["user_id"],
                "variant_id": assignment["variant_id"],
                "exposed_at": exposure["exposed_at"],
                "assignment_variant_id": assignment["variant_id"],
                "exposure_variant_id": exposure["variant_id"],
            }
        )
    return sorted(units, key=lambda item: item["user_id"])


def binary_event_observation(
    unit: dict[str, Any],
    metric: dict[str, Any],
    events_by_user: dict[str, list[dict[str, str]]],
) -> tuple[float, float, float | None]:
    event_name = BINARY_EVENT_BY_METRIC[metric["metric_id"]]
    start = parse_time(unit["exposed_at"])
    numerator = any(
        row["event_name"] == event_name and in_window(row["occurred_at"], start, int(metric["window_days"]))
        for row in events_by_user.get(unit["user_id"], [])
    )
    return float(numerator), 1.0, float(numerator)


def support_observation(
    unit: dict[str, Any],
    metric: dict[str, Any],
    tickets_by_user: dict[str, list[dict[str, str]]],
) -> tuple[float, float, float | None]:
    start = parse_time(unit["exposed_at"])
    numerator = any(
        in_window(row["created_at"], start, int(metric["window_days"]))
        for row in tickets_by_user.get(unit["user_id"], [])
    )
    return float(numerator), 1.0, float(numerator)


def cancellation_observation(
    unit: dict[str, Any],
    metric: dict[str, Any],
    subscriptions_by_user: dict[str, list[dict[str, str]]],
) -> tuple[float, float, float | None]:
    start = parse_time(unit["exposed_at"])
    subscriptions = [
        row
        for row in subscriptions_by_user.get(unit["user_id"], [])
        if in_window(row["started_at"], start, int(metric["window_days"]))
    ]
    if not subscriptions:
        return 0.0, 0.0, None
    cancelled = any(
        row.get("status") == "cancelled" and in_window(row.get("cancelled_at", ""), start, int(metric["window_days"]))
        for row in subscriptions
    )
    return float(cancelled), 1.0, float(cancelled)


def refund_observation(
    unit: dict[str, Any],
    metric: dict[str, Any],
    orders_by_user: dict[str, list[dict[str, str]]],
) -> tuple[float, float, float | None]:
    start = parse_time(unit["exposed_at"])
    orders = [
        row
        for row in orders_by_user.get(unit["user_id"], [])
        if row["currency"] == "RUB"
        and row["status"] in {"paid", "refunded"}
        and in_window(row["created_at"], start, int(metric["window_days"]))
    ]
    if not orders:
        return 0.0, 0.0, None
    refunds = sum(1 for row in orders if row["status"] == "refunded" or parse_float(row["refund_amount_rub"]) > 0)
    return float(refunds), float(len(orders)), refunds / len(orders)


def revenue_observation(
    unit: dict[str, Any],
    metric: dict[str, Any],
    orders_by_user: dict[str, list[dict[str, str]]],
) -> tuple[float, float, float | None]:
    start = parse_time(unit["exposed_at"])
    realized = 0.0
    for row in orders_by_user.get(unit["user_id"], []):
        if row["currency"] != "RUB" or row["status"] not in {"paid", "refunded"}:
            continue
        if in_window(row["created_at"], start, int(metric["window_days"])):
            realized += parse_float(row["amount_rub"]) - parse_float(row["refund_amount_rub"])
    return realized, 1.0, realized


def metric_type(metric: dict[str, Any]) -> str:
    if metric["metric_id"] == "realized_revenue_per_user_7d":
        return "mean"
    if metric["metric_id"] == "refund_rate_7d":
        return "ratio"
    return "proportion"


def build_observations(
    protocol: dict[str, Any],
    metric_specs: dict[str, Any],
    assignments: list[dict[str, str]],
    exposures: list[dict[str, str]],
    users: list[dict[str, str]],
    events: list[dict[str, str]],
    orders: list[dict[str, str]],
    subscriptions: list[dict[str, str]],
    support_tickets: list[dict[str, str]],
) -> list[dict[str, Any]]:
    metrics = metrics_by_id(metric_specs)
    events_grouped = rows_by_user(unique_by_key(events, "event_id"))
    orders_grouped = rows_by_user(unique_by_key(orders, "order_id"))
    subscriptions_grouped = rows_by_user(unique_by_key(subscriptions, "subscription_id"))
    tickets_grouped = rows_by_user(unique_by_key(support_tickets, "ticket_id"))
    units = eligible_exposed_units(protocol, assignments, exposures, users)
    observations: list[dict[str, Any]] = []
    for unit in units:
        window_start = parse_time(unit["exposed_at"])
        for metric_id in declared_metric_ids(protocol):
            metric = metrics[metric_id]
            if metric_id in BINARY_EVENT_BY_METRIC:
                numerator, denominator, value = binary_event_observation(unit, metric, events_grouped)
            elif metric_id == "support_ticket_rate_7d":
                numerator, denominator, value = support_observation(unit, metric, tickets_grouped)
            elif metric_id == "subscription_cancel_rate_14d":
                numerator, denominator, value = cancellation_observation(unit, metric, subscriptions_grouped)
            elif metric_id == "refund_rate_7d":
                numerator, denominator, value = refund_observation(unit, metric, orders_grouped)
            elif metric_id == "realized_revenue_per_user_7d":
                numerator, denominator, value = revenue_observation(unit, metric, orders_grouped)
            else:
                raise ValueError(f"unsupported metric_id: {metric_id}")
            window_end = window_start + timedelta(days=int(metric["window_days"]))
            observations.append(
                {
                    "experiment_id": unit["experiment_id"],
                    "user_id": unit["user_id"],
                    "variant_id": unit["variant_id"],
                    "metric_id": metric_id,
                    "role": metric["role"],
                    "metric_type": metric_type(metric),
                    "observation_unit": "user_id",
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "numerator": round_float(numerator),
                    "denominator": round_float(denominator),
                    "value": None if value is None else round_float(value),
                }
            )
    return observations


def by_metric_and_variant(observations: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in observations:
        grouped.setdefault(row["metric_id"], {}).setdefault(row["variant_id"], []).append(row)
    return grouped


def numeric_values(rows: list[dict[str, Any]]) -> list[float]:
    return [parse_float(row["value"]) for row in rows if row["value"] not in (None, "")]


def numerator_denominator(rows: list[dict[str, Any]]) -> tuple[float, float, int]:
    eligible = [row for row in rows if parse_float(row["denominator"]) > 0]
    numerator = sum(parse_float(row["numerator"]) for row in eligible)
    denominator = sum(parse_float(row["denominator"]) for row in eligible)
    return numerator, denominator, len(eligible)


def proportion_interval(
    treatment_count: float,
    treatment_n: float,
    control_count: float,
    control_n: float,
    alpha: float,
    method: str,
) -> tuple[float, float]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        low, high = confint_proportions_2indep(
            int(treatment_count),
            int(treatment_n),
            int(control_count),
            int(control_n),
            method=method,
            compare="diff",
            alpha=alpha,
        )
    return float(low), float(high)


def proportion_p_value(
    treatment_count: float,
    treatment_n: float,
    control_count: float,
    control_n: float,
    alternative: str,
) -> float:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        _, p_value = proportions_ztest(
            [treatment_count, control_count],
            [treatment_n, control_n],
            alternative=alternative,
        )
    return float(p_value)


def welch_interval(treatment: list[float], control: list[float], alpha: float) -> tuple[float, float, float]:
    treatment_array = np.array(treatment, dtype=float)
    control_array = np.array(control, dtype=float)
    diff = float(treatment_array.mean() - control_array.mean())
    treatment_var = float(treatment_array.var(ddof=1)) if len(treatment_array) > 1 else 0.0
    control_var = float(control_array.var(ddof=1)) if len(control_array) > 1 else 0.0
    se_sq = treatment_var / len(treatment_array) + control_var / len(control_array)
    if se_sq <= 0:
        return diff, diff, math.inf
    df_num = se_sq**2
    df_den = 0.0
    if len(treatment_array) > 1 and treatment_var > 0:
        df_den += (treatment_var / len(treatment_array)) ** 2 / (len(treatment_array) - 1)
    if len(control_array) > 1 and control_var > 0:
        df_den += (control_var / len(control_array)) ** 2 / (len(control_array) - 1)
    df = df_num / df_den if df_den > 0 else math.inf
    critical = stats.t.ppf(1 - alpha / 2, df) if math.isfinite(df) else stats.norm.ppf(1 - alpha / 2)
    margin = float(critical * math.sqrt(se_sq))
    return diff - margin, diff + margin, df


def welch_p_value(treatment: list[float], control: list[float], alternative: str) -> float:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = stats.ttest_ind(treatment, control, equal_var=False, alternative=alternative)
    return float(result.pvalue)


def alternative_for_metric(metric: dict[str, Any]) -> str:
    if metric.get("expected_direction") in {"up", "up_is_bad"}:
        return "larger"
    if metric.get("expected_direction") in {"down", "down_is_bad"}:
        return "smaller"
    return "two-sided"


def scipy_alternative(alternative: str) -> str:
    if alternative == "larger":
        return "greater"
    if alternative == "smaller":
        return "less"
    return alternative


def metric_threshold(metric: dict[str, Any], protocol: dict[str, Any]) -> float | None:
    if metric["role"] == "primary":
        return parse_float(protocol["decision_rule"]["launch"]["minimum_absolute_lift"])
    if metric["role"] == "guardrail":
        return parse_float(metric["maximum_allowed_delta"])
    return None


def practical_status(
    metric: dict[str, Any],
    protocol: dict[str, Any],
    absolute_lift: float,
    ci_high: float,
    p_value: float,
) -> tuple[str, str, str]:
    alpha = parse_float(protocol["alpha"])
    threshold = metric_threshold(metric, protocol)
    if metric["role"] == "primary":
        if absolute_lift <= 0:
            return "missed_primary_direction", "", "not_launch_ready"
        if threshold is not None and absolute_lift < threshold:
            return "below_declared_mde", "", "not_launch_ready"
        if p_value > alpha:
            return "not_statistically_significant", "", "not_launch_ready"
        return "meets_primary_rule", "", "launch_rule_candidate"
    if metric["role"] == "guardrail":
        if threshold is not None and absolute_lift > threshold:
            return "guardrail_point_breached", "breached", "blocks_launch"
        if threshold is not None and ci_high > threshold:
            return "guardrail_not_ruled_out", "watch", "blocks_launch"
        return "guardrail_not_breached", "not_breached", "passes_guardrail_gate"
    if absolute_lift > 0 and p_value <= alpha:
        return "secondary_directional_signal", "", "diagnostic_only"
    if absolute_lift > 0:
        return "secondary_positive_but_uncertain", "", "diagnostic_only"
    return "secondary_no_positive_signal", "", "diagnostic_only"


def effect_row(
    metric: dict[str, Any],
    protocol: dict[str, Any],
    control_rows: list[dict[str, Any]],
    treatment_rows: list[dict[str, Any]],
    effect_spec: dict[str, Any],
) -> dict[str, Any]:
    alpha = parse_float(protocol["alpha"])
    metric_kind = metric_type(metric)
    alternative = alternative_for_metric(metric)
    if metric_kind == "mean":
        control_values = numeric_values(control_rows)
        treatment_values = numeric_values(treatment_rows)
        control_value = float(np.mean(control_values))
        treatment_value = float(np.mean(treatment_values))
        absolute_lift = treatment_value - control_value
        ci_low, ci_high, _ = welch_interval(treatment_values, control_values, alpha)
        p_value = welch_p_value(treatment_values, control_values, scipy_alternative(alternative))
        control_denominator = float(len(control_values))
        treatment_denominator = float(len(treatment_values))
        control_units = len(control_values)
        treatment_units = len(treatment_values)
        method = effect_spec["mean_test"]
    else:
        control_count, control_denominator, control_units = numerator_denominator(control_rows)
        treatment_count, treatment_denominator, treatment_units = numerator_denominator(treatment_rows)
        control_value = ratio_or_inf(control_count, control_denominator)
        treatment_value = ratio_or_inf(treatment_count, treatment_denominator)
        absolute_lift = treatment_value - control_value
        ci_low, ci_high = proportion_interval(
            treatment_count,
            treatment_denominator,
            control_count,
            control_denominator,
            alpha,
            effect_spec["proportion_ci_method"],
        )
        p_value = proportion_p_value(
            treatment_count,
            treatment_denominator,
            control_count,
            control_denominator,
            alternative,
        )
        method = effect_spec["proportion_test"] if metric_kind == "proportion" else effect_spec["ratio_test"]
    relative_lift = ratio_or_inf(absolute_lift, control_value)
    status, guardrail_status, decision_status = practical_status(metric, protocol, absolute_lift, ci_high, p_value)
    return {
        "metric_id": metric["metric_id"],
        "role": metric["role"],
        "metric_type": metric_kind,
        "method": method,
        "control_units": control_units,
        "treatment_units": treatment_units,
        "control_denominator": round_float(control_denominator),
        "treatment_denominator": round_float(treatment_denominator),
        "control_value": round_float(control_value),
        "treatment_value": round_float(treatment_value),
        "absolute_lift": round_float(absolute_lift),
        "relative_lift": round_float(relative_lift),
        "ci_low": round_float(ci_low),
        "ci_high": round_float(ci_high),
        "p_value": round_float(p_value),
        "alpha": alpha,
        "statistically_significant": p_value <= alpha,
        "expected_direction": metric["expected_direction"],
        "practical_threshold": "" if metric_threshold(metric, protocol) is None else metric_threshold(metric, protocol),
        "practical_status": status,
        "guardrail_status": guardrail_status,
        "decision_role": decision_role(metric),
        "decision_status": decision_status,
        "assumption_status": "checked_with_warnings",
    }


def decision_role(metric: dict[str, Any]) -> str:
    if metric["role"] == "primary":
        return "launch_gate"
    if metric["role"] == "guardrail":
        return "guardrail_gate"
    return "diagnostic_only"


def build_effects(
    protocol: dict[str, Any],
    metric_specs: dict[str, Any],
    observations: list[dict[str, Any]],
    effect_spec: dict[str, Any],
) -> list[dict[str, Any]]:
    control_id, treatment_id = ordered_variants(protocol)
    grouped = by_metric_and_variant(observations)
    metrics = metrics_by_id(metric_specs)
    rows: list[dict[str, Any]] = []
    for metric_id in declared_metric_ids(protocol):
        rows.append(
            effect_row(
                metrics[metric_id],
                protocol,
                grouped.get(metric_id, {}).get(control_id, []),
                grouped.get(metric_id, {}).get(treatment_id, []),
                effect_spec,
            )
        )
    return rows


def required_n_by_metric(power_plan: dict[str, Any]) -> dict[str, dict[str, int]]:
    required: dict[str, dict[str, int]] = {}
    for row in power_plan.get("metric_plans", []):
        required[row["metric_id"]] = {
            "control": int(row["required_n_control"]),
            "treatment": int(row["required_n_treatment"]),
        }
    return required


def check_sample_against_power(effect: dict[str, Any], requirements: dict[str, dict[str, int]]) -> dict[str, Any] | None:
    metric_id = effect["metric_id"]
    if metric_id not in requirements:
        return None
    required = requirements[metric_id]
    valid = effect["control_denominator"] >= required["control"] and effect["treatment_denominator"] >= required["treatment"]
    return {
        "id": f"{metric_id}:observed_sample_meets_power_plan",
        "metric_id": metric_id,
        "severity": "warning",
        "valid": bool(valid),
        "observed": {
            "control_denominator": effect["control_denominator"],
            "treatment_denominator": effect["treatment_denominator"],
        },
        "expected": required,
    }


def proportion_assumption_check(effect: dict[str, Any], observations: list[dict[str, Any]], effect_spec: dict[str, Any]) -> dict[str, Any]:
    metric_rows = [row for row in observations if row["metric_id"] == effect["metric_id"] and parse_float(row["denominator"]) > 0]
    by_variant: dict[str, list[dict[str, Any]]] = {}
    for row in metric_rows:
        by_variant.setdefault(row["variant_id"], []).append(row)
    min_cells: list[float] = []
    observed: dict[str, dict[str, float]] = {}
    for variant, rows in sorted(by_variant.items()):
        successes = sum(parse_float(row["numerator"]) for row in rows)
        denominator = sum(parse_float(row["denominator"]) for row in rows)
        failures = denominator - successes
        min_cells.extend([successes, failures])
        observed[variant] = {
            "successes": round_float(successes),
            "failures": round_float(failures),
            "denominator": round_float(denominator),
        }
    threshold = int(effect_spec["minimum_successes_and_failures_per_variant"])
    valid = bool(min_cells) and min(min_cells) >= threshold
    return {
        "id": f"{effect['metric_id']}:normal_approximation_cell_counts",
        "metric_id": effect["metric_id"],
        "severity": "warning",
        "valid": valid,
        "observed": observed,
        "expected": f"successes and failures per variant >= {threshold}",
    }


def mean_assumption_checks(effect: dict[str, Any], observations: list[dict[str, Any]], effect_spec: dict[str, Any]) -> list[dict[str, Any]]:
    metric_rows = [row for row in observations if row["metric_id"] == effect["metric_id"]]
    values_by_variant: dict[str, list[float]] = {}
    for row in metric_rows:
        if row["value"] not in (None, ""):
            values_by_variant.setdefault(row["variant_id"], []).append(parse_float(row["value"]))
    minimum_n = int(effect_spec["minimum_mean_n_per_variant"])
    n_observed = {variant: len(values) for variant, values in sorted(values_by_variant.items())}
    variances = {
        variant: round_float(float(np.var(values, ddof=1))) if len(values) > 1 else 0.0
        for variant, values in sorted(values_by_variant.items())
    }
    return [
        {
            "id": f"{effect['metric_id']}:mean_minimum_sample_size",
            "metric_id": effect["metric_id"],
            "severity": "warning",
            "valid": all(count >= minimum_n for count in n_observed.values()),
            "observed": n_observed,
            "expected": f"n per variant >= {minimum_n}",
        },
        {
            "id": f"{effect['metric_id']}:mean_variance_positive",
            "metric_id": effect["metric_id"],
            "severity": "warning",
            "valid": all(value > 0 for value in variances.values()),
            "observed": variances,
            "expected": "sample variance > 0 in every variant",
        },
    ]


def build_assumption_report(
    protocol: dict[str, Any],
    metric_specs: dict[str, Any],
    health_report: dict[str, Any],
    power_plan: dict[str, Any],
    observations: list[dict[str, Any]],
    effects: list[dict[str, Any]],
    effect_spec: dict[str, Any],
) -> dict[str, Any]:
    metrics = metrics_by_id(metric_specs)
    checks: list[dict[str, Any]] = [
        {
            "id": "upstream_randomization_health_ready",
            "severity": "error",
            "valid": health_report.get("ready_for_ab_analysis") is True,
            "observed": health_report.get("ready_for_ab_analysis"),
            "expected": True,
        },
        {
            "id": "upstream_power_plan_ready",
            "severity": "error",
            "valid": power_plan.get("valid") is True and power_plan.get("ready_for_sizing") is True,
            "observed": {
                "valid": power_plan.get("valid"),
                "ready_for_sizing": power_plan.get("ready_for_sizing"),
            },
            "expected": {"valid": True, "ready_for_sizing": True},
        },
        {
            "id": "metric_family_declared_in_protocol",
            "severity": "error",
            "valid": all(metric_id in metrics for metric_id in declared_metric_ids(protocol)),
            "observed": declared_metric_ids(protocol),
            "expected": "every primary, guardrail and secondary metric has a metric spec",
        },
    ]
    requirements = required_n_by_metric(power_plan)
    for effect in effects:
        denominator_valid = effect["control_denominator"] > 0 and effect["treatment_denominator"] > 0
        checks.append(
            {
                "id": f"{effect['metric_id']}:positive_denominators",
                "metric_id": effect["metric_id"],
                "severity": "error",
                "valid": bool(denominator_valid),
                "observed": {
                    "control_denominator": effect["control_denominator"],
                    "treatment_denominator": effect["treatment_denominator"],
                },
                "expected": "both variants have a positive analysis denominator",
            }
        )
        sample_check = check_sample_against_power(effect, requirements)
        if sample_check is not None:
            checks.append(sample_check)
        if effect["metric_type"] in {"proportion", "ratio"}:
            checks.append(proportion_assumption_check(effect, observations, effect_spec))
        else:
            checks.extend(mean_assumption_checks(effect, observations, effect_spec))
    blocking_failures = [check["id"] for check in checks if check["severity"] == "error" and not check["valid"]]
    warning_checks = [check["id"] for check in checks if check["severity"] == "warning" and not check["valid"]]
    primary = next(effect for effect in effects if effect["metric_id"] == protocol["primary_metric"])
    guardrails = {effect["metric_id"]: effect["guardrail_status"] for effect in effects if effect["role"] == "guardrail"}
    decision_blockers: list[str] = []
    if primary["decision_status"] != "launch_rule_candidate":
        decision_blockers.append(primary["practical_status"])
    if any(status in {"breached", "watch"} for status in guardrails.values()):
        decision_blockers.append("guardrails_not_cleared")
    if any(check["id"].endswith("observed_sample_meets_power_plan") and not check["valid"] for check in checks):
        decision_blockers.append("observed_sample_below_power_plan")
    if warning_checks:
        decision_blockers.append("assumption_warnings_present")
    return {
        "valid": not blocking_failures,
        "ready_for_decision": not blocking_failures and not decision_blockers,
        "summary": {
            "experiment_id": protocol["experiment_id"],
            "metrics_analyzed": len(effects),
            "primary_metric": protocol["primary_metric"],
            "primary_status": primary["practical_status"],
            "primary_p_value": primary["p_value"],
            "guardrail_statuses": guardrails,
            "blocking_failures": blocking_failures,
            "warning_checks": warning_checks,
            "decision_blockers": decision_blockers,
        },
        "checks": checks,
    }


def blocked_report(reason: str, health_report: dict[str, Any], power_plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    assumptions = {
        "valid": False,
        "ready_for_decision": False,
        "summary": {
            "experiment_id": power_plan.get("summary", {}).get("experiment_id", ""),
            "metrics_analyzed": 0,
            "blocking_failures": [reason],
            "warning_checks": [],
            "decision_blockers": [reason],
        },
        "checks": [
            {
                "id": reason,
                "severity": "error",
                "valid": False,
                "observed": {
                    "ready_for_ab_analysis": health_report.get("ready_for_ab_analysis"),
                    "power_plan_valid": power_plan.get("valid"),
                    "ready_for_sizing": power_plan.get("ready_for_sizing"),
                },
                "expected": "upstream health and power plan are ready",
            }
        ],
    }
    return [], [], assumptions


def build_analysis(
    protocol: dict[str, Any],
    metric_specs: dict[str, Any],
    effect_spec: dict[str, Any],
    health_report: dict[str, Any],
    power_plan: dict[str, Any],
    users: list[dict[str, str]],
    assignments: list[dict[str, str]],
    exposures: list[dict[str, str]],
    events: list[dict[str, str]],
    orders: list[dict[str, str]],
    subscriptions: list[dict[str, str]],
    support_tickets: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if health_report.get("ready_for_ab_analysis") is not True:
        return blocked_report("upstream_randomization_health_not_ready", health_report, power_plan)
    if power_plan.get("valid") is not True or power_plan.get("ready_for_sizing") is not True:
        return blocked_report("upstream_power_plan_not_ready", health_report, power_plan)
    observations = build_observations(
        protocol,
        metric_specs,
        assignments,
        exposures,
        users,
        events,
        orders,
        subscriptions,
        support_tickets,
    )
    effects = build_effects(protocol, metric_specs, observations, effect_spec)
    assumptions = build_assumption_report(protocol, metric_specs, health_report, power_plan, observations, effects, effect_spec)
    return observations, effects, assumptions


def run(
    protocol_path: Path,
    metric_specs_path: Path,
    effect_spec_path: Path,
    health_report_path: Path,
    power_plan_path: Path,
    users_path: Path,
    assignments_path: Path,
    exposures_path: Path,
    events_path: Path,
    orders_path: Path,
    subscriptions_path: Path,
    support_tickets_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    return build_analysis(
        read_json(protocol_path),
        read_json(metric_specs_path),
        read_json(effect_spec_path),
        read_json(health_report_path),
        read_json(power_plan_path),
        read_csv(users_path),
        read_csv(assignments_path),
        read_csv(exposures_path),
        read_csv(events_path),
        read_csv(orders_path),
        read_csv(subscriptions_path),
        read_csv(support_tickets_path),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calculate fixed-horizon experiment effects for declared metrics.")
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--metric-specs", type=Path, required=True)
    parser.add_argument("--effect-spec", type=Path, required=True)
    parser.add_argument("--health-report", type=Path, required=True)
    parser.add_argument("--power-plan", type=Path, required=True)
    parser.add_argument("--users", type=Path, required=True)
    parser.add_argument("--assignments", type=Path, required=True)
    parser.add_argument("--exposures", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--orders", type=Path, required=True)
    parser.add_argument("--subscriptions", type=Path, required=True)
    parser.add_argument("--support-tickets", type=Path, required=True)
    parser.add_argument("--output-observations", type=Path)
    parser.add_argument("--output-effects", type=Path)
    parser.add_argument("--output-assumptions", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    observations, effects, assumptions = run(
        args.protocol,
        args.metric_specs,
        args.effect_spec,
        args.health_report,
        args.power_plan,
        args.users,
        args.assignments,
        args.exposures,
        args.events,
        args.orders,
        args.subscriptions,
        args.support_tickets,
    )
    if args.output_observations is not None:
        write_csv(args.output_observations, observations, OBSERVATION_FIELDS)
    if args.output_effects is not None:
        write_csv(args.output_effects, effects, EFFECT_FIELDS)
    if args.output_assumptions is not None:
        write_json(args.output_assumptions, assumptions)
    print(json.dumps(assumptions, ensure_ascii=False, indent=2))
    return 0 if assumptions["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
