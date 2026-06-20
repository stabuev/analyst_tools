from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

REQUIRED_SPEC_FIELDS = {
    "version",
    "question_id",
    "target_population",
    "sampling_unit",
    "observation_filter",
    "minimum_observations",
    "upstream_inputs",
    "estimators",
}
REQUIRED_ESTIMATOR_FIELDS = {
    "estimator_id",
    "parameter",
    "statistic",
    "estimator",
    "metric_column",
    "value_type",
    "weights",
    "distribution_card_metric_id",
    "standard_error_method",
    "known_limitations",
}
SUPPORTED_ESTIMATORS = {
    "sample_mean",
    "sample_proportion",
    "sample_quantile",
    "inverse_probability_weighted_mean",
    "inverse_probability_weighted_proportion",
    "inverse_probability_weighted_rate",
}
SUPPORTED_VALUE_TYPES = {"boolean", "numeric", "count"}
CSV_COLUMNS = [
    "estimator_id",
    "parameter",
    "statistic",
    "estimator",
    "metric_column",
    "estimate",
    "standard_error",
    "standard_error_method",
    "n",
    "sum_weights",
    "effective_n",
    "distribution_card_metric_id",
    "upstream_warning_ids",
    "limitations",
]


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
        raise ValueError(f"{path} must contain a JSON object")
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


def parse_count(value: str) -> int:
    number = parse_float(value)
    if number < 0 or not number.is_integer():
        raise ValueError(f"expected non-negative integer count, got {value!r}")
    return int(number)


def round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def spec_checks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing:
        checks.append(
            failed("estimator_spec_required_fields", "error", sorted(spec), sorted(REQUIRED_SPEC_FIELDS), missing)
        )
    else:
        checks.append(
            passed("estimator_spec_required_fields", "error", sorted(REQUIRED_SPEC_FIELDS), sorted(REQUIRED_SPEC_FIELDS))
        )

    estimators = spec.get("estimators", [])
    if not isinstance(estimators, list) or not estimators:
        checks.append(failed("estimator_specs_declared", "error", estimators, "non-empty list"))
        return checks

    ids = [estimator.get("estimator_id") for estimator in estimators if isinstance(estimator, dict)]
    duplicates = sorted({estimator_id for estimator_id in ids if ids.count(estimator_id) > 1})
    if duplicates:
        checks.append(failed("estimator_ids_unique", "error", duplicates, "unique estimator_id"))
    else:
        checks.append(passed("estimator_ids_unique", "error", len(ids), "unique estimator_id"))

    unsupported = sorted(
        estimator.get("estimator")
        for estimator in estimators
        if isinstance(estimator, dict) and estimator.get("estimator") not in SUPPORTED_ESTIMATORS
    )
    if unsupported:
        checks.append(failed("estimators_supported", "error", unsupported, sorted(SUPPORTED_ESTIMATORS)))
    else:
        checks.append(passed("estimators_supported", "error", sorted(SUPPORTED_ESTIMATORS), sorted(SUPPORTED_ESTIMATORS)))
    return checks


def upstream_checks(
    sampling_audit: dict[str, Any],
    distribution_cards: dict[str, Any],
) -> tuple[set[str], list[str], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    if sampling_audit.get("valid") is not True:
        checks.append(
            failed("sampling_audit_has_no_blocking_errors", "error", sampling_audit.get("valid"), True)
        )
    else:
        checks.append(passed("sampling_audit_has_no_blocking_errors", "error", True, True))

    sampling_warnings = sorted(
        check["id"]
        for check in sampling_audit.get("checks", [])
        if check.get("severity") == "warning" and not check.get("valid")
    )
    if sampling_warnings:
        checks.append(
            failed(
                "sampling_audit_warnings_carried",
                "warning",
                sampling_warnings,
                "carry warning ids into estimate limitations",
            )
        )
    else:
        checks.append(passed("sampling_audit_warnings_carried", "warning", [], "no warnings"))

    if distribution_cards.get("valid") is not True:
        checks.append(
            failed("distribution_cards_have_no_blocking_errors", "error", distribution_cards.get("valid"), True)
        )
    else:
        checks.append(passed("distribution_cards_have_no_blocking_errors", "error", True, True))

    card_ids = {
        card["metric_id"]
        for card in distribution_cards.get("cards", [])
        if isinstance(card, dict) and "metric_id" in card
    }
    checks.append(passed("distribution_card_ids_loaded", "error", sorted(card_ids), "metric ids"))
    return card_ids, sampling_warnings, checks


def observed_rows(sample: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    filter_spec = spec["observation_filter"]
    outcome_column = filter_spec["outcome_observed_column"]
    days_column = filter_spec["observed_days_column"]
    required_days = int(filter_spec["required_observed_days"])
    minimum = int(spec["minimum_observations"])
    rows: list[dict[str, str]] = []
    invalid: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    for row in sample:
        try:
            observed = parse_bool(row[outcome_column])
        except (KeyError, ValueError):
            invalid.append({"user_id": row.get("user_id"), "value": row.get(outcome_column)})
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

    checks: list[dict[str, Any]] = []
    if invalid:
        checks.append(failed("outcome_observed_parseable", "error", len(invalid), "true or false", invalid))
    else:
        checks.append(passed("outcome_observed_parseable", "error", len(sample), "true or false"))
    if incomplete:
        checks.append(failed("respondent_windows_complete", "error", len(incomplete), f">= {required_days}", incomplete))
    else:
        checks.append(passed("respondent_windows_complete", "error", len(rows), f">= {required_days}"))
    if len(rows) < minimum:
        checks.append(failed("respondent_rows_available", "error", len(rows), f">= {minimum}"))
    else:
        checks.append(passed("respondent_rows_available", "error", len(rows), f">= {minimum}"))
    return rows, checks


def validate_estimator_metadata(estimator: dict[str, Any]) -> list[dict[str, Any]]:
    estimator_id = estimator.get("estimator_id", "unknown_estimator")
    checks: list[dict[str, Any]] = []
    missing = sorted(REQUIRED_ESTIMATOR_FIELDS - set(estimator))
    if missing:
        checks.append(
            failed(f"{estimator_id}_required_fields", "error", sorted(estimator), sorted(REQUIRED_ESTIMATOR_FIELDS), missing)
        )
        return checks
    checks.append(passed(f"{estimator_id}_required_fields", "error", sorted(REQUIRED_ESTIMATOR_FIELDS), sorted(REQUIRED_ESTIMATOR_FIELDS)))

    empty_semantics = [
        field
        for field in ("parameter", "statistic", "estimator")
        if not isinstance(estimator.get(field), str) or not estimator[field].strip()
    ]
    if empty_semantics:
        checks.append(
            failed(f"{estimator_id}_parameter_statistic_estimator_present", "error", empty_semantics, "non-empty strings")
        )
    else:
        checks.append(
            passed(f"{estimator_id}_parameter_statistic_estimator_present", "error", "present", "non-empty strings")
        )

    if estimator.get("value_type") not in SUPPORTED_VALUE_TYPES:
        checks.append(
            failed(f"{estimator_id}_value_type_supported", "error", estimator.get("value_type"), sorted(SUPPORTED_VALUE_TYPES))
        )
    else:
        checks.append(passed(f"{estimator_id}_value_type_supported", "error", estimator["value_type"], sorted(SUPPORTED_VALUE_TYPES)))
    return checks


def parse_values(rows: list[dict[str, str]], estimator: dict[str, Any]) -> tuple[list[float], list[dict[str, Any]]]:
    estimator_id = estimator["estimator_id"]
    column = estimator["metric_column"]
    value_type = estimator["value_type"]
    values: list[float] = []
    invalid: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        try:
            raw = row[column]
        except KeyError:
            invalid.append({"row": index, "user_id": row.get("user_id"), "value": None})
            continue
        try:
            if value_type == "boolean":
                values.append(1.0 if parse_bool(raw) else 0.0)
            elif value_type == "numeric":
                values.append(parse_float(raw))
            elif value_type == "count":
                values.append(float(parse_count(raw)))
            else:
                invalid.append({"row": index, "user_id": row.get("user_id"), "value_type": value_type})
        except ValueError:
            invalid.append({"row": index, "user_id": row.get("user_id"), "value": raw})

    if invalid:
        return values, [
            failed(f"{estimator_id}_metric_values_parseable", "error", len(invalid), value_type, invalid)
        ]
    return values, [passed(f"{estimator_id}_metric_values_parseable", "error", len(values), value_type)]


def parse_weights(rows: list[dict[str, str]], estimator: dict[str, Any]) -> tuple[list[float] | None, list[dict[str, Any]]]:
    estimator_id = estimator["estimator_id"]
    weight_spec = estimator.get("weights")
    if weight_spec is None:
        return None, [passed(f"{estimator_id}_weights_declared", "error", None, "unweighted estimator")]
    column = weight_spec["column"]
    weights: list[float] = []
    invalid: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        try:
            weight = parse_float(row[column])
        except (KeyError, ValueError):
            invalid.append({"row": index, "user_id": row.get("user_id"), "weight": row.get(column)})
            continue
        if weight <= 0:
            invalid.append({"row": index, "user_id": row.get("user_id"), "weight": weight})
        weights.append(weight)
    if invalid:
        return weights, [
            failed(f"{estimator_id}_weights_positive", "error", len(invalid), "> 0 numeric weights", invalid)
        ]
    return weights, [passed(f"{estimator_id}_weights_positive", "error", len(weights), "> 0 numeric weights")]


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def weighted_mean(values: list[float], weights: list[float]) -> float:
    return float(np.average(np.array(values, dtype=float), weights=np.array(weights, dtype=float)))


def effective_sample_size(weights: list[float] | None, n: int) -> float:
    if weights is None:
        return float(n)
    total = sum(weights)
    squared = sum(weight * weight for weight in weights)
    return total * total / squared if squared else 0.0


def standard_error(
    values: list[float],
    estimate: float,
    method: str,
    weights: list[float] | None,
) -> float | None:
    n = len(values)
    if method == "not_computed_until_bootstrap":
        return None
    if n < 2:
        return None
    if method == "binomial_plugin":
        return math.sqrt(estimate * (1 - estimate) / n)
    if method == "sample_sd_over_sqrt_n":
        return float(stats.sem(values))
    if method == "weighted_plugin":
        n_eff = effective_sample_size(weights, n)
        if weights is None:
            variance = statistics.pvariance(values)
        else:
            total_weight = sum(weights)
            variance = sum(weight * (value - estimate) ** 2 for value, weight in zip(values, weights, strict=True)) / total_weight
        return math.sqrt(variance / n_eff) if n_eff > 0 else None
    raise ValueError(f"unsupported standard error method: {method}")


def compute_estimate(
    estimator: dict[str, Any],
    rows: list[dict[str, str]],
    card_ids: set[str],
    sampling_warning_ids: list[str],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    estimator_id = estimator.get("estimator_id", "unknown_estimator")
    checks = validate_estimator_metadata(estimator)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return None, checks

    columns = set(rows[0]) if rows else set()
    if estimator["metric_column"] not in columns:
        checks.append(
            failed(f"{estimator_id}_metric_column_present", "error", estimator["metric_column"], sorted(columns))
        )
        return None, checks
    checks.append(passed(f"{estimator_id}_metric_column_present", "error", estimator["metric_column"], estimator["metric_column"]))

    card_id = estimator["distribution_card_metric_id"]
    if card_id not in card_ids:
        checks.append(failed(f"{estimator_id}_distribution_card_resolves", "error", card_id, sorted(card_ids)))
        return None, checks
    checks.append(passed(f"{estimator_id}_distribution_card_resolves", "error", card_id, sorted(card_ids)))

    values, value_checks = parse_values(rows, estimator)
    checks.extend(value_checks)
    weights, weight_checks = parse_weights(rows, estimator)
    checks.extend(weight_checks)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return None, checks

    estimator_name = estimator["estimator"]
    if estimator_name in {"sample_mean", "sample_proportion"}:
        estimate = statistics.fmean(values)
    elif estimator_name == "sample_quantile":
        estimate = quantile(values, float(estimator.get("quantile", 0.5)))
    elif estimator_name in {
        "inverse_probability_weighted_mean",
        "inverse_probability_weighted_proportion",
        "inverse_probability_weighted_rate",
    }:
        if weights is None:
            checks.append(failed(f"{estimator_id}_weights_declared", "error", None, "weights required"))
            return None, checks
        estimate = weighted_mean(values, weights)
    else:
        checks.append(failed(f"{estimator_id}_estimator_supported", "error", estimator_name, sorted(SUPPORTED_ESTIMATORS)))
        return None, checks

    try:
        se = standard_error(values, estimate, estimator["standard_error_method"], weights)
    except ValueError as error:
        checks.append(failed(f"{estimator_id}_standard_error_method_supported", "error", str(error), "supported method"))
        return None, checks
    checks.append(passed(f"{estimator_id}_estimate_computed", "error", round_float(estimate), "numeric estimate"))

    limitations = list(estimator["known_limitations"])
    if sampling_warning_ids:
        limitations.append("Sampling audit warnings: " + ", ".join(sampling_warning_ids))
    result = {
        "estimator_id": estimator_id,
        "parameter": estimator["parameter"],
        "statistic": estimator["statistic"],
        "estimator": estimator_name,
        "metric_column": estimator["metric_column"],
        "estimate": round_float(estimate),
        "standard_error": round_float(se),
        "standard_error_method": estimator["standard_error_method"],
        "n": len(values),
        "sum_weights": round_float(sum(weights)) if weights is not None else None,
        "effective_n": round_float(effective_sample_size(weights, len(values))),
        "distribution_card_metric_id": card_id,
        "upstream_warning_ids": sampling_warning_ids,
        "limitations": limitations,
    }
    return result, checks


def write_estimates_csv(path: Path, estimates: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for estimate in estimates:
            row = dict(estimate)
            row["upstream_warning_ids"] = "|".join(estimate["upstream_warning_ids"])
            row["limitations"] = "|".join(estimate["limitations"])
            for key, value in list(row.items()):
                if value is None:
                    row[key] = ""
            writer.writerow(row)


def run(
    sample_path: Path,
    spec_path: Path,
    sampling_audit_path: Path,
    distribution_cards_path: Path,
) -> dict[str, Any]:
    sample = read_csv(sample_path)
    spec = read_json(spec_path)
    sampling_audit = read_json(sampling_audit_path)
    distribution_cards = read_json(distribution_cards_path)

    checks = spec_checks(spec)
    card_ids, sampling_warning_ids, upstream = upstream_checks(sampling_audit, distribution_cards)
    checks.extend(upstream)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
        warning_count = sum(1 for check in checks if check["severity"] == "warning" and not check["valid"])
        return {
            "valid": False,
            "summary": {"estimates": 0, "error_count": error_count, "warning_count": warning_count},
            "estimates": [],
            "checks": checks,
        }

    rows, row_checks = observed_rows(sample, spec)
    checks.extend(row_checks)

    estimates: list[dict[str, Any]] = []
    for estimator in spec["estimators"]:
        estimate, estimate_checks = compute_estimate(estimator, rows, card_ids, sampling_warning_ids)
        checks.extend(estimate_checks)
        if estimate is not None:
            estimates.append(estimate)

    error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
    warning_count = sum(1 for check in checks if check["severity"] == "warning" and not check["valid"])
    return {
        "valid": error_count == 0,
        "summary": {
            "source_rows": len(sample),
            "respondent_rows": len(rows),
            "estimates": len(estimates),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "estimates": estimates,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build point estimates from estimator specs")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--sampling-audit", type=Path, required=True)
    parser.add_argument("--distribution-cards", type=Path, required=True)
    parser.add_argument("--output-estimates", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args()

    report = run(args.sample, args.spec, args.sampling_audit, args.distribution_cards)
    write_estimates_csv(args.output_estimates, report["estimates"])
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
