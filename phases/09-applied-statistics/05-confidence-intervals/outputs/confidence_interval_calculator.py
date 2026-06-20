from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

SUPPORTED_METHODS = {"normal_proportion", "t_mean", "normal_mean"}
SUPPORTED_VALUE_TYPES = {"boolean", "numeric", "count"}
CSV_COLUMNS = [
    "interval_id",
    "parameter_id",
    "method",
    "confidence_level",
    "alpha",
    "estimate",
    "standard_error",
    "lower",
    "upper",
    "n",
    "status",
    "coverage_rate",
    "assumption_warning_ids",
    "limitations",
]


def passed(check_id: str, severity: str, observed: Any, expected: Any) -> dict[str, Any]:
    return {"id": check_id, "severity": severity, "valid": True, "observed": observed, "expected": expected, "sample": []}


def failed(
    check_id: str,
    severity: str,
    observed: Any,
    expected: Any,
    sample: list[Any] | None = None,
) -> dict[str, Any]:
    return {"id": check_id, "severity": severity, "valid": False, "observed": observed, "expected": expected, "sample": sample or []}


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


def parse_value(row: dict[str, str], column: str, value_type: str) -> float:
    if value_type == "boolean":
        return 1.0 if parse_bool(row[column]) else 0.0
    if value_type == "numeric":
        if row[column] == "":
            raise ValueError("empty numeric value")
        return float(row[column])
    if value_type == "count":
        number = float(row[column])
        if number < 0 or not number.is_integer():
            raise ValueError(f"expected non-negative count, got {row[column]!r}")
        return number
    raise ValueError(f"unsupported value_type: {value_type}")


def round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def observed_rows(sample: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    filter_spec = spec["observation_filter"]
    outcome_column = filter_spec["outcome_observed_column"]
    days_column = filter_spec["observed_days_column"]
    required_days = int(filter_spec["required_observed_days"])
    rows: list[dict[str, str]] = []
    invalid: list[dict[str, Any]] = []
    for row in sample:
        try:
            observed = parse_bool(row[outcome_column])
            observed_days = int(row[days_column])
        except (KeyError, ValueError):
            invalid.append({"user_id": row.get("user_id")})
            continue
        if observed and observed_days >= required_days:
            rows.append(row)
    checks = [passed("observed_rows_selected", "error", len(rows), "complete observed rows")]
    if invalid:
        checks.append(failed("observation_filter_parseable", "error", len(invalid), "parseable observed flag and days", invalid))
    else:
        checks.append(passed("observation_filter_parseable", "error", len(sample), "parseable observed flag and days"))
    return rows, checks


def eligible_population(population: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in population
        if parse_bool(row["eligible_for_analysis"])
        and not parse_bool(row["is_test_user"])
        and int(row["true_observed_days"]) >= 7
    ]


def spec_checks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    required = {
        "version",
        "question_id",
        "target_population",
        "sampling_unit",
        "observation_filter",
        "coverage_simulation",
        "intervals",
    }
    checks: list[dict[str, Any]] = []
    missing = sorted(required - set(spec))
    if missing:
        checks.append(failed("confidence_interval_spec_required_fields", "error", sorted(spec), sorted(required), missing))
        return checks
    checks.append(passed("confidence_interval_spec_required_fields", "error", sorted(required), sorted(required)))

    interval_ids = [item.get("interval_id") for item in spec["intervals"] if isinstance(item, dict)]
    duplicates = sorted({interval_id for interval_id in interval_ids if interval_ids.count(interval_id) > 1})
    if duplicates:
        checks.append(failed("interval_ids_unique", "error", duplicates, "unique interval ids"))
    else:
        checks.append(passed("interval_ids_unique", "error", len(interval_ids), "unique interval ids"))

    unsupported_methods = sorted(
        item.get("method")
        for item in spec["intervals"]
        if isinstance(item, dict) and item.get("method") not in SUPPORTED_METHODS
    )
    if unsupported_methods:
        checks.append(failed("interval_methods_supported", "error", unsupported_methods, sorted(SUPPORTED_METHODS)))
    else:
        checks.append(passed("interval_methods_supported", "error", sorted(SUPPORTED_METHODS), sorted(SUPPORTED_METHODS)))

    unsupported_types = sorted(
        item.get("value_type")
        for item in spec["intervals"]
        if isinstance(item, dict) and item.get("value_type") not in SUPPORTED_VALUE_TYPES
    )
    if unsupported_types:
        checks.append(failed("interval_value_types_supported", "error", unsupported_types, sorted(SUPPORTED_VALUE_TYPES)))
    else:
        checks.append(passed("interval_value_types_supported", "error", sorted(SUPPORTED_VALUE_TYPES), sorted(SUPPORTED_VALUE_TYPES)))
    return checks


def distribution_card_ids(distribution_cards: dict[str, Any]) -> tuple[set[str], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    if distribution_cards.get("valid") is not True:
        checks.append(failed("distribution_cards_have_no_blocking_errors", "error", distribution_cards.get("valid"), True))
    else:
        checks.append(passed("distribution_cards_have_no_blocking_errors", "error", True, True))
    ids = {
        card["metric_id"]
        for card in distribution_cards.get("cards", [])
        if isinstance(card, dict) and "metric_id" in card
    }
    checks.append(passed("distribution_card_ids_loaded", "error", sorted(ids), "metric ids"))
    return ids, checks


def confidence_interval(values: list[float], interval: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    interval_id = interval["interval_id"]
    checks: list[dict[str, Any]] = []
    n = len(values)
    confidence_level = float(interval["confidence_level"])
    alpha = 1.0 - confidence_level
    estimate = statistics.fmean(values)
    limitations = list(interval.get("known_limitations", []))
    warning_ids: list[str] = []

    if n < int(interval["minimum_n"]):
        checks.append(failed(f"{interval_id}_minimum_n", "warning", n, f">= {interval['minimum_n']}"))
        return {
            "interval_id": interval_id,
            "parameter_id": interval["parameter_id"],
            "method": interval["method"],
            "confidence_level": confidence_level,
            "alpha": alpha,
            "estimate": round_float(estimate),
            "standard_error": None,
            "lower": None,
            "upper": None,
            "n": n,
            "status": "blocked",
            "coverage_rate": None,
            "assumption_warning_ids": [],
            "limitations": limitations,
        }, checks
    checks.append(passed(f"{interval_id}_minimum_n", "error", n, f">= {interval['minimum_n']}"))

    method = interval["method"]
    if method == "normal_proportion":
        successes = int(sum(values))
        failures = n - successes
        if successes < int(interval["minimum_successes"]):
            warning_ids.append("few_successes_for_normal_proportion")
            checks.append(failed(f"{interval_id}_minimum_successes", "warning", successes, f">= {interval['minimum_successes']}"))
        else:
            checks.append(passed(f"{interval_id}_minimum_successes", "warning", successes, f">= {interval['minimum_successes']}"))
        if failures < int(interval["minimum_failures"]):
            warning_ids.append("few_failures_for_normal_proportion")
            checks.append(failed(f"{interval_id}_minimum_failures", "warning", failures, f">= {interval['minimum_failures']}"))
        else:
            checks.append(passed(f"{interval_id}_minimum_failures", "warning", failures, f">= {interval['minimum_failures']}"))
        se = math.sqrt(estimate * (1.0 - estimate) / n)
        critical = stats.norm.ppf(1.0 - alpha / 2.0)
        lower = max(0.0, estimate - critical * se)
        upper = min(1.0, estimate + critical * se)
    elif method in {"t_mean", "normal_mean"}:
        if n < 2:
            checks.append(failed(f"{interval_id}_sample_variance_available", "error", n, ">= 2"))
            return {
                "interval_id": interval_id,
                "parameter_id": interval["parameter_id"],
                "method": method,
                "confidence_level": confidence_level,
                "alpha": alpha,
                "estimate": round_float(estimate),
                "standard_error": None,
                "lower": None,
                "upper": None,
                "n": n,
                "status": "blocked",
                "coverage_rate": None,
                "assumption_warning_ids": warning_ids,
                "limitations": limitations,
            }, checks
        se = statistics.stdev(values) / math.sqrt(n)
        critical = stats.t.ppf(1.0 - alpha / 2.0, df=n - 1) if method == "t_mean" else stats.norm.ppf(1.0 - alpha / 2.0)
        lower = estimate - critical * se
        upper = estimate + critical * se
        checks.append(passed(f"{interval_id}_sample_variance_available", "error", n, ">= 2"))
    else:
        raise ValueError(f"unsupported interval method: {method}")

    status = "warning" if warning_ids else "ok"
    return {
        "interval_id": interval_id,
        "parameter_id": interval["parameter_id"],
        "method": method,
        "confidence_level": confidence_level,
        "alpha": alpha,
        "estimate": round_float(estimate),
        "standard_error": round_float(se),
        "lower": round_float(lower),
        "upper": round_float(upper),
        "n": n,
        "status": status,
        "coverage_rate": None,
        "assumption_warning_ids": warning_ids,
        "limitations": limitations,
    }, checks


def coverage_rate(
    rng: np.random.Generator,
    population_rows: list[dict[str, str]],
    interval: dict[str, Any],
    true_parameter: float,
    n_simulations: int,
    sample_size: int,
) -> float | None:
    if len(population_rows) == 0:
        return None
    covered = 0
    attempted = 0
    for _ in range(n_simulations):
        indices = rng.choice(len(population_rows), size=sample_size, replace=True)
        rows = [population_rows[int(index)] for index in indices]
        values = [parse_value(row, interval["population_metric_column"], interval["value_type"]) for row in rows]
        result, checks = confidence_interval(values, interval)
        if any((not check["valid"]) and check["severity"] == "error" for check in checks):
            continue
        attempted += 1
        if result["lower"] <= true_parameter <= result["upper"]:
            covered += 1
    return covered / attempted if attempted else None


def run(
    sample_path: Path,
    population_path: Path,
    spec_path: Path,
    distribution_cards_path: Path,
) -> dict[str, Any]:
    sample = read_csv(sample_path)
    population = read_csv(population_path)
    spec = read_json(spec_path)
    distribution_cards = read_json(distribution_cards_path)

    checks = spec_checks(spec)
    card_ids, card_checks = distribution_card_ids(distribution_cards)
    checks.extend(card_checks)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return {
            "valid": False,
            "summary": {"intervals": 0, "error_count": sum(not check["valid"] for check in checks), "warning_count": 0},
            "intervals": [],
            "checks": checks,
        }

    rows, row_checks = observed_rows(sample, spec)
    checks.extend(row_checks)
    population_rows = eligible_population(population)
    rng = np.random.default_rng(int(spec["coverage_simulation"]["seed"]))
    intervals: list[dict[str, Any]] = []

    for interval_spec in spec["intervals"]:
        interval_id = interval_spec["interval_id"]
        sample_column = interval_spec["sample_metric_column"]
        population_column = interval_spec["population_metric_column"]
        if interval_spec["distribution_card_metric_id"] not in card_ids:
            checks.append(failed(f"{interval_id}_distribution_card_resolves", "error", interval_spec["distribution_card_metric_id"], sorted(card_ids)))
            continue
        checks.append(passed(f"{interval_id}_distribution_card_resolves", "error", interval_spec["distribution_card_metric_id"], sorted(card_ids)))
        if sample_column not in (set(rows[0]) if rows else set()):
            checks.append(failed(f"{interval_id}_sample_metric_column_present", "error", sample_column, "sample columns"))
            continue
        if population_column not in (set(population_rows[0]) if population_rows else set()):
            checks.append(failed(f"{interval_id}_population_metric_column_present", "error", population_column, "population columns"))
            continue
        values = [parse_value(row, sample_column, interval_spec["value_type"]) for row in rows]
        interval, interval_checks = confidence_interval(values, interval_spec)
        checks.extend(interval_checks)
        true_values = [
            parse_value(row, population_column, interval_spec["value_type"])
            for row in population_rows
        ]
        true_parameter = statistics.fmean(true_values)
        interval["true_parameter"] = round_float(true_parameter)
        if interval["status"] != "blocked":
            interval["coverage_rate"] = round_float(
                coverage_rate(
                    rng,
                    population_rows,
                    interval_spec,
                    true_parameter,
                    int(spec["coverage_simulation"]["n_simulations"]),
                    int(spec["coverage_simulation"]["sample_size"]),
                )
            )
        intervals.append(interval)

    error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
    warning_count = sum(1 for check in checks if check["severity"] == "warning" and not check["valid"])
    return {
        "valid": error_count == 0,
        "summary": {
            "intervals": len(intervals),
            "ok_intervals": sum(1 for item in intervals if item["status"] == "ok"),
            "warning_intervals": sum(1 for item in intervals if item["status"] == "warning"),
            "blocked_intervals": sum(1 for item in intervals if item["status"] == "blocked"),
            "coverage_simulations": int(spec["coverage_simulation"]["n_simulations"]),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "intervals": intervals,
        "checks": checks,
    }


def write_intervals_csv(path: Path, intervals: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for interval in intervals:
            row = {column: interval.get(column) for column in CSV_COLUMNS}
            row["assumption_warning_ids"] = "|".join(interval["assumption_warning_ids"])
            row["limitations"] = "|".join(interval["limitations"])
            for key, value in list(row.items()):
                if value is None:
                    row[key] = ""
            writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build formula confidence intervals with assumption checks")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--distribution-cards", type=Path, required=True)
    parser.add_argument("--output-intervals", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args(argv)

    report = run(args.sample, args.population, args.spec, args.distribution_cards)
    write_intervals_csv(args.output_intervals, report["intervals"])
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "intervals": report["summary"]["intervals"],
                "blocked_intervals": report["summary"]["blocked_intervals"],
                "warning_count": report["summary"]["warning_count"],
                "error_count": report["summary"]["error_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
