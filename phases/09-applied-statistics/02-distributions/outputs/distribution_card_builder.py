from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

from scipy import stats

SUPPORTED_MODELS = {"bernoulli", "lognormal_positive", "poisson_count"}
REQUIRED_SPEC_FIELDS = {
    "version",
    "question_id",
    "target_population",
    "sampling_unit",
    "observation_filter",
    "minimum_observations",
    "small_sample_threshold",
    "metrics",
}


def passed(check_id: str, severity: str, observed: Any, expected: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": True,
        "observed": observed,
        "expected": expected,
        "sample": [],
    }


def failed(
    check_id: str,
    severity: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "severity": severity,
        "valid": False,
        "observed": observed,
        "expected": expected,
        "sample": sample or [],
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError("distribution spec must be a JSON object")
    return value


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"expected boolean string, got {value!r}")


def parse_float(value: str) -> float:
    if value == "":
        raise ValueError("empty numeric value")
    return float(value)


def parse_int_like(value: str) -> int:
    number = parse_float(value)
    if number < 0 or not number.is_integer():
        raise ValueError(f"expected non-negative integer count, got {value!r}")
    return int(number)


def round_float(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def spec_checks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        checks.append(
            failed(
                "distribution_spec_required_fields",
                "error",
                sorted(spec),
                sorted(REQUIRED_SPEC_FIELDS),
                missing,
            )
        )
    else:
        checks.append(
            passed(
                "distribution_spec_required_fields",
                "error",
                sorted(REQUIRED_SPEC_FIELDS),
                sorted(REQUIRED_SPEC_FIELDS),
            )
        )

    metrics = spec.get("metrics", [])
    if not isinstance(metrics, list) or not metrics:
        checks.append(failed("distribution_metrics_declared", "error", metrics, "non-empty list"))
        return checks

    duplicate_ids = sorted(
        metric_id
        for metric_id in {metric.get("metric_id") for metric in metrics if isinstance(metric, dict)}
        if sum(1 for metric in metrics if isinstance(metric, dict) and metric.get("metric_id") == metric_id)
        > 1
    )
    if duplicate_ids:
        checks.append(
            failed("distribution_metric_ids_unique", "error", duplicate_ids, "unique metric_id")
        )
    else:
        checks.append(passed("distribution_metric_ids_unique", "error", len(metrics), "unique metric_id"))

    unsupported = sorted(
        metric.get("model")
        for metric in metrics
        if isinstance(metric, dict) and metric.get("model") not in SUPPORTED_MODELS
    )
    if unsupported:
        checks.append(
            failed("distribution_models_supported", "error", unsupported, sorted(SUPPORTED_MODELS))
        )
    else:
        checks.append(
            passed("distribution_models_supported", "error", sorted(SUPPORTED_MODELS), sorted(SUPPORTED_MODELS))
        )
    return checks


def observed_rows(sample: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    filter_spec = spec["observation_filter"]
    outcome_column = filter_spec["outcome_observed_column"]
    days_column = filter_spec["observed_days_column"]
    required_days = int(filter_spec["required_observed_days"])
    minimum = int(spec["minimum_observations"])
    rows: list[dict[str, str]] = []
    checks: list[dict[str, Any]] = []
    invalid_flags: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []

    for row in sample:
        try:
            observed = parse_bool(row[outcome_column])
        except (KeyError, ValueError):
            invalid_flags.append({"user_id": row.get("user_id"), "value": row.get(outcome_column)})
            continue
        if not observed:
            continue
        try:
            observed_days = int(row[days_column])
        except (KeyError, ValueError):
            incomplete.append({"user_id": row.get("user_id"), "observed_days": row.get(days_column)})
            continue
        if observed_days < required_days:
            incomplete.append({"user_id": row.get("user_id"), "observed_days": observed_days})
            continue
        rows.append(row)

    if invalid_flags:
        checks.append(
            failed(
                "outcome_observed_parseable",
                "error",
                len(invalid_flags),
                "true or false",
                invalid_flags,
            )
        )
    else:
        checks.append(passed("outcome_observed_parseable", "error", len(sample), "true or false"))

    if incomplete:
        checks.append(
            failed(
                "respondent_windows_complete",
                "error",
                len(incomplete),
                f">= {required_days} days",
                incomplete,
            )
        )
    else:
        checks.append(passed("respondent_windows_complete", "error", len(rows), f">= {required_days} days"))

    if len(rows) < minimum:
        checks.append(
            failed("respondent_rows_available", "error", len(rows), f">= {minimum} observed rows")
        )
    else:
        checks.append(passed("respondent_rows_available", "error", len(rows), f">= {minimum} observed rows"))
    return rows, checks


def values_for_column(
    rows: list[dict[str, str]],
    metric: dict[str, Any],
    columns: set[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    metric_id = metric["metric_id"]
    column = metric["column"]
    if column not in columns:
        return [], [failed(f"{metric_id}_column_present", "error", column, sorted(columns))]
    return [row[column] for row in rows], [passed(f"{metric_id}_column_present", "error", column, column)]


def small_sample_check(metric_id: str, n: int, threshold: int) -> dict[str, Any]:
    if n < threshold:
        return failed(
            f"{metric_id}_small_sample_model_check",
            "warning",
            n,
            f">= {threshold} for stable distribution diagnostics",
        )
    return passed(
        f"{metric_id}_small_sample_model_check",
        "warning",
        n,
        f">= {threshold} for stable distribution diagnostics",
    )


def bernoulli_card(metric: dict[str, Any], values: list[str], spec: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    metric_id = metric["metric_id"]
    checks: list[dict[str, Any]] = []
    parsed: list[int] = []
    invalid: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        try:
            parsed.append(1 if parse_bool(value) else 0)
        except ValueError:
            invalid.append({"row": index, "value": value})
    if invalid:
        checks.append(failed(f"{metric_id}_boolean_support", "error", len(invalid), "true or false", invalid))
        return None, checks
    checks.append(passed(f"{metric_id}_boolean_support", "error", sorted(set(parsed)), [0, 1]))

    n = len(parsed)
    successes = sum(parsed)
    p_hat = successes / n
    if not 0 <= p_hat <= 1:
        checks.append(failed(f"{metric_id}_parameter_domain", "error", p_hat, "[0, 1]"))
        return None, checks
    checks.append(passed(f"{metric_id}_parameter_domain", "error", round_float(p_hat), "[0, 1]"))
    checks.append(small_sample_check(metric_id, n, int(spec["small_sample_threshold"])))
    binom_mean = stats.binom.mean(n, p_hat)
    card = {
        "metric_id": metric_id,
        "column": metric["column"],
        "distribution": {
            "family": "bernoulli",
            "scipy": "scipy.stats.bernoulli",
            "sampling_distribution": "scipy.stats.binom",
            "support": metric["support"],
        },
        "n_observed": n,
        "parameters": {
            "p_hat": round_float(p_hat),
            "successes": successes,
            "failures": n - successes,
        },
        "empirical": {
            "mean": round_float(statistics.fmean(parsed)),
            "variance_population": round_float(statistics.pvariance(parsed)),
        },
        "scipy_summary": {
            "bernoulli_mean": round_float(stats.bernoulli.mean(p_hat)),
            "bernoulli_variance": round_float(stats.bernoulli.var(p_hat)),
            "binomial_mean_for_n": round_float(binom_mean),
            "probability_of_observed_or_more_successes": round_float(
                stats.binom.sf(successes - 1, n, p_hat)
            ),
        },
        "assumptions": metric["assumptions"],
        "failure_modes": metric["failure_modes"],
        "limitations": [
            "This is a user-level distribution model for observed respondents, not proof that the sample represents the target population.",
            "Confidence intervals and estimator choices are handled in later lessons.",
        ],
    }
    return card, checks


def lognormal_card(metric: dict[str, Any], values: list[str], spec: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    metric_id = metric["metric_id"]
    checks: list[dict[str, Any]] = []
    numeric: list[float] = []
    invalid_numeric: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        try:
            number = parse_float(value)
        except ValueError:
            invalid_numeric.append({"row": index, "value": value})
            continue
        numeric.append(number)

    if invalid_numeric:
        checks.append(
            failed(f"{metric_id}_numeric_support", "error", len(invalid_numeric), "numeric", invalid_numeric)
        )
        return None, checks
    checks.append(passed(f"{metric_id}_numeric_support", "error", len(numeric), "numeric"))

    negative = [{"row": index, "value": value} for index, value in enumerate(numeric) if value < 0]
    if negative:
        checks.append(failed(f"{metric_id}_nonnegative_support", "error", len(negative), ">= 0", negative))
        return None, checks
    checks.append(passed(f"{metric_id}_nonnegative_support", "error", len(numeric), ">= 0"))

    zeros = sum(1 for value in numeric if value == 0)
    if zeros and not metric.get("zero_handling"):
        checks.append(
            failed(
                f"{metric_id}_positive_support",
                "error",
                zeros,
                "x > 0",
                [
                    {"row": index, "value": value}
                    for index, value in enumerate(numeric)
                    if value == 0
                ],
            )
        )
        return None, checks
    checks.append(passed(f"{metric_id}_positive_support", "error", len(numeric) - zeros, "x > 0"))

    positive = [value for value in numeric if value > 0]
    if len(positive) < 2:
        checks.append(
            failed(
                f"{metric_id}_positive_observations_available",
                "error",
                len(positive),
                ">= 2 positive values for lognormal fit",
            )
        )
        return None, checks
    checks.append(
        passed(
            f"{metric_id}_positive_observations_available",
            "error",
            len(positive),
            ">= 2 positive values for lognormal fit",
        )
    )

    if zeros:
        checks.append(
            failed(
                f"{metric_id}_zero_mass_documented",
                "warning",
                zeros,
                "zeros handled outside the lognormal positive fit",
            )
        )
    else:
        checks.append(passed(f"{metric_id}_zero_mass_documented", "warning", 0, "no zero mass"))

    shape, loc, scale = stats.lognorm.fit(positive, floc=0)
    ks = stats.kstest(positive, "lognorm", args=(shape, loc, scale))
    median = statistics.median(positive)
    p90 = percentile(positive, 0.90)
    ratio = p90 / median if median else math.inf
    threshold = float(metric.get("tail_ratio_warning_threshold", 2.0))
    if ratio >= threshold:
        checks.append(
            failed(
                f"{metric_id}_right_tail_diagnostic",
                "warning",
                round_float(ratio),
                f"< {threshold}",
                [{"p90": round_float(p90), "median": round_float(median)}],
            )
        )
    else:
        checks.append(
            passed(f"{metric_id}_right_tail_diagnostic", "warning", round_float(ratio), f"< {threshold}")
        )
    checks.append(small_sample_check(metric_id, len(positive), int(spec["small_sample_threshold"])))

    card = {
        "metric_id": metric_id,
        "column": metric["column"],
        "distribution": {
            "family": "lognormal_positive",
            "scipy": "scipy.stats.lognorm",
            "support": metric["support"],
        },
        "n_observed": len(numeric),
        "n_positive": len(positive),
        "zero_count": zeros,
        "parameters": {
            "shape_sigma": round_float(shape),
            "loc": round_float(loc),
            "scale_exp_mu": round_float(scale),
        },
        "empirical": {
            "mean_all_observed": round_float(statistics.fmean(numeric)),
            "mean_positive": round_float(statistics.fmean(positive)),
            "median_positive": round_float(median),
            "p90_positive": round_float(p90),
            "p90_to_median_ratio": round_float(ratio),
        },
        "scipy_summary": {
            "model_mean_positive": round_float(stats.lognorm.mean(shape, loc=loc, scale=scale)),
            "model_median_positive": round_float(stats.lognorm.median(shape, loc=loc, scale=scale)),
            "ks_statistic_diagnostic": round_float(ks.statistic),
            "ks_pvalue_diagnostic": round_float(ks.pvalue),
        },
        "assumptions": metric["assumptions"],
        "failure_modes": metric["failure_modes"],
        "limitations": [
            "The lognormal model is fit on the same small sample it diagnoses.",
            "A K-S diagnostic after fitting parameters is descriptive and should not be read as a formal goodness-of-fit proof.",
        ],
    }
    if metric.get("zero_handling"):
        card["zero_handling"] = metric["zero_handling"]
    return card, checks


def poisson_card(metric: dict[str, Any], values: list[str], spec: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    metric_id = metric["metric_id"]
    checks: list[dict[str, Any]] = []
    counts: list[int] = []
    invalid: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        try:
            counts.append(parse_int_like(value))
        except ValueError:
            invalid.append({"row": index, "value": value})
    if invalid:
        checks.append(
            failed(f"{metric_id}_count_support", "error", len(invalid), "non-negative integers", invalid)
        )
        return None, checks
    checks.append(passed(f"{metric_id}_count_support", "error", sorted(set(counts)), "non-negative integers"))

    n = len(counts)
    mean = statistics.fmean(counts)
    variance = statistics.pvariance(counts)
    dispersion = variance / mean if mean else 0.0
    if mean > 0 and not 0.5 <= dispersion <= 2.0:
        checks.append(
            failed(
                f"{metric_id}_poisson_dispersion",
                "warning",
                round_float(dispersion),
                "variance / mean between 0.5 and 2.0",
            )
        )
    else:
        checks.append(
            passed(
                f"{metric_id}_poisson_dispersion",
                "warning",
                round_float(dispersion),
                "variance / mean between 0.5 and 2.0",
            )
        )
    checks.append(small_sample_check(metric_id, n, int(spec["small_sample_threshold"])))

    card = {
        "metric_id": metric_id,
        "column": metric["column"],
        "distribution": {
            "family": "poisson",
            "scipy": "scipy.stats.poisson",
            "support": metric["support"],
        },
        "n_observed": n,
        "parameters": {
            "lambda_hat": round_float(mean),
        },
        "empirical": {
            "mean": round_float(mean),
            "variance_population": round_float(variance),
            "zero_rate": round_float(sum(1 for value in counts if value == 0) / n),
            "max": max(counts),
        },
        "scipy_summary": {
            "poisson_mean": round_float(stats.poisson.mean(mean)),
            "poisson_variance": round_float(stats.poisson.var(mean)),
            "model_zero_probability": round_float(stats.poisson.pmf(0, mean)),
            "probability_of_at_least_one_ticket": round_float(stats.poisson.sf(0, mean)),
        },
        "assumptions": metric["assumptions"],
        "failure_modes": metric["failure_modes"],
        "limitations": [
            "A Poisson card checks the count support and mean-variance shape; it does not explain why tickets happened.",
            "Overdispersion and excess-zero checks become more meaningful on larger samples.",
        ],
    }
    return card, checks


def build_metric_card(
    metric: dict[str, Any],
    rows: list[dict[str, str]],
    columns: set[str],
    spec: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    values, checks = values_for_column(rows, metric, columns)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return None, checks
    model = metric["model"]
    if model == "bernoulli":
        card, model_checks = bernoulli_card(metric, values, spec)
    elif model == "lognormal_positive":
        card, model_checks = lognormal_card(metric, values, spec)
    elif model == "poisson_count":
        card, model_checks = poisson_card(metric, values, spec)
    else:
        card, model_checks = None, [
            failed(f"{metric['metric_id']}_model_supported", "error", model, sorted(SUPPORTED_MODELS))
        ]
    return card, checks + model_checks


def run(sample_path: Path, spec_path: Path) -> dict[str, Any]:
    sample = read_csv(sample_path)
    spec = read_json(spec_path)
    checks = spec_checks(spec)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return {
            "valid": False,
            "summary": {"cards": 0, "error_count": sum(not c["valid"] for c in checks), "warning_count": 0},
            "cards": [],
            "checks": checks,
        }

    rows, row_checks = observed_rows(sample, spec)
    checks.extend(row_checks)
    columns = set(sample[0]) if sample else set()
    cards: list[dict[str, Any]] = []
    for metric in spec["metrics"]:
        card, metric_checks = build_metric_card(metric, rows, columns, spec)
        checks.extend(metric_checks)
        if card is not None:
            cards.append(card)

    error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
    warning_count = sum(1 for check in checks if check["severity"] == "warning" and not check["valid"])
    return {
        "valid": error_count == 0,
        "summary": {
            "source_rows": len(sample),
            "respondent_rows": len(rows),
            "cards": len(cards),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "cards": cards,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build distribution cards for phase 09 metrics")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = run(args.sample, args.spec)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
