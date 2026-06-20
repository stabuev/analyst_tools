from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

SUPPORTED_STATISTICS = {"mean", "median"}
SUPPORTED_METHODS = {"percentile", "basic", "bca"}
SUPPORTED_VALUE_TYPES = {"boolean", "numeric", "count"}


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
    import csv

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
    if not np.isfinite(value):
        return None
    return round(float(value), digits)


def observed_rows(sample: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    filter_spec = spec["observation_filter"]
    rows: list[dict[str, str]] = []
    for row in sample:
        if (
            parse_bool(row[filter_spec["outcome_observed_column"]])
            and int(row[filter_spec["observed_days_column"]]) >= int(filter_spec["required_observed_days"])
        ):
            rows.append(row)
    return rows, [passed("resampling_rows_selected", "error", len(rows), "complete observed rows")]


def spec_checks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    required = {
        "version",
        "question_id",
        "target_population",
        "sampling_unit",
        "resampling_unit",
        "paired",
        "seed",
        "n_resamples",
        "confidence_level",
        "observation_filter",
        "statistics",
    }
    checks: list[dict[str, Any]] = []
    missing = sorted(required - set(spec))
    if missing:
        checks.append(failed("bootstrap_spec_required_fields", "error", sorted(spec), sorted(required), missing))
        return checks
    checks.append(passed("bootstrap_spec_required_fields", "error", sorted(required), sorted(required)))
    if spec["resampling_unit"] != spec["sampling_unit"]:
        checks.append(failed("resampling_unit_matches_sampling_unit", "error", spec["resampling_unit"], spec["sampling_unit"]))
    else:
        checks.append(passed("resampling_unit_matches_sampling_unit", "error", spec["resampling_unit"], spec["sampling_unit"]))
    ids = [item.get("statistic_id") for item in spec["statistics"] if isinstance(item, dict)]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        checks.append(failed("bootstrap_statistic_ids_unique", "error", duplicates, "unique statistic ids"))
    else:
        checks.append(passed("bootstrap_statistic_ids_unique", "error", len(ids), "unique statistic ids"))
    unsupported_methods = sorted(
        item.get("method")
        for item in spec["statistics"]
        if isinstance(item, dict) and item.get("method") not in SUPPORTED_METHODS
    )
    if unsupported_methods:
        checks.append(failed("bootstrap_methods_supported", "error", unsupported_methods, sorted(SUPPORTED_METHODS)))
    else:
        checks.append(passed("bootstrap_methods_supported", "error", sorted(SUPPORTED_METHODS), sorted(SUPPORTED_METHODS)))
    unsupported_statistics = sorted(
        item.get("statistic")
        for item in spec["statistics"]
        if isinstance(item, dict) and item.get("statistic") not in SUPPORTED_STATISTICS
    )
    if unsupported_statistics:
        checks.append(failed("bootstrap_statistics_supported", "error", unsupported_statistics, sorted(SUPPORTED_STATISTICS)))
    else:
        checks.append(passed("bootstrap_statistics_supported", "error", sorted(SUPPORTED_STATISTICS), sorted(SUPPORTED_STATISTICS)))
    return checks


def distribution_card_ids(distribution_cards: dict[str, Any]) -> tuple[set[str], list[dict[str, Any]]]:
    if distribution_cards.get("valid") is not True:
        return set(), [failed("distribution_cards_have_no_blocking_errors", "error", distribution_cards.get("valid"), True)]
    ids = {
        card["metric_id"]
        for card in distribution_cards.get("cards", [])
        if isinstance(card, dict) and "metric_id" in card
    }
    return ids, [
        passed("distribution_cards_have_no_blocking_errors", "error", True, True),
        passed("distribution_card_ids_loaded", "error", sorted(ids), "metric ids"),
    ]


def statistic_value(values: list[float] | np.ndarray, statistic_name: str) -> float:
    array = np.asarray(values, dtype=float)
    if statistic_name == "mean":
        return float(np.mean(array))
    if statistic_name == "median":
        return float(np.median(array))
    raise ValueError(f"unsupported statistic: {statistic_name}")


def bootstrap_distribution(
    values: list[float],
    statistic_name: str,
    n_resamples: int,
    rng: np.random.Generator,
) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    indices = rng.integers(0, len(array), size=(n_resamples, len(array)))
    samples = array[indices]
    if statistic_name == "mean":
        return np.mean(samples, axis=1)
    if statistic_name == "median":
        return np.median(samples, axis=1)
    raise ValueError(f"unsupported statistic: {statistic_name}")


def percentile_interval(distribution: np.ndarray, confidence_level: float) -> tuple[float, float]:
    alpha = 1.0 - confidence_level
    lower, upper = np.quantile(distribution, [alpha / 2.0, 1.0 - alpha / 2.0])
    return float(lower), float(upper)


def bca_interval(values: list[float], statistic_name: str, confidence_level: float, n_resamples: int, seed: int) -> tuple[float, float]:
    array = np.asarray(values, dtype=float)

    def statistic(sample: np.ndarray, axis: int = 0) -> float:
        if statistic_name == "mean":
            return np.mean(sample, axis=axis)
        if statistic_name == "median":
            return np.median(sample, axis=axis)
        raise ValueError(f"unsupported statistic: {statistic_name}")

    result = stats.bootstrap(
        (array,),
        statistic,
        n_resamples=n_resamples,
        confidence_level=confidence_level,
        method="BCa",
        paired=True,
        rng=np.random.default_rng(seed),
    )
    return float(result.confidence_interval.low), float(result.confidence_interval.high)


def build_interval(
    rows: list[dict[str, str]],
    statistic_spec: dict[str, Any],
    confidence_level: float,
    n_resamples: int,
    seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    statistic_id = statistic_spec["statistic_id"]
    values = [parse_value(row, statistic_spec["metric_column"], statistic_spec["value_type"]) for row in rows]
    checks: list[dict[str, Any]] = [passed(f"{statistic_id}_values_parseable", "error", len(values), statistic_spec["value_type"])]
    observed = statistic_value(values, statistic_spec["statistic"])
    distribution = bootstrap_distribution(values, statistic_spec["statistic"], n_resamples, np.random.default_rng(seed))
    unique_values = np.unique(distribution)
    warnings: list[str] = []
    if len(unique_values) == 1:
        warnings.append("degenerate_bootstrap_distribution")
        checks.append(failed(f"{statistic_id}_bootstrap_distribution_non_degenerate", "warning", 1, "> 1 unique values"))
    else:
        checks.append(passed(f"{statistic_id}_bootstrap_distribution_non_degenerate", "warning", len(unique_values), "> 1 unique values"))

    method = statistic_spec["method"]
    if method == "percentile":
        lower, upper = percentile_interval(distribution, confidence_level)
    elif method == "basic":
        pct_lower, pct_upper = percentile_interval(distribution, confidence_level)
        lower = 2 * observed - pct_upper
        upper = 2 * observed - pct_lower
    elif method == "bca":
        if len(unique_values) == 1:
            lower = upper = observed
        else:
            lower, upper = bca_interval(values, statistic_spec["statistic"], confidence_level, n_resamples, seed + 17)
    else:
        raise ValueError(f"unsupported method: {method}")

    status = "warning" if warnings else "ok"
    return {
        "statistic_id": statistic_id,
        "parameter_id": statistic_spec["parameter_id"],
        "metric_column": statistic_spec["metric_column"],
        "statistic": statistic_spec["statistic"],
        "method": method,
        "confidence_level": confidence_level,
        "observed_statistic": round_float(observed),
        "lower": round_float(lower),
        "upper": round_float(upper),
        "n": len(values),
        "n_resamples": n_resamples,
        "standard_error": round_float(float(np.std(distribution, ddof=1))),
        "distribution_summary": {
            "min": round_float(float(np.min(distribution))),
            "p25": round_float(float(np.quantile(distribution, 0.25))),
            "median": round_float(float(np.median(distribution))),
            "p75": round_float(float(np.quantile(distribution, 0.75))),
            "max": round_float(float(np.max(distribution))),
            "unique_values": int(len(unique_values)),
        },
        "diagnostic_warning_ids": warnings,
        "status": status,
        "limitations": list(statistic_spec.get("known_limitations", [])),
    }, checks


def run(sample_path: Path, spec_path: Path, distribution_cards_path: Path) -> dict[str, Any]:
    sample = read_csv(sample_path)
    spec = read_json(spec_path)
    distribution_cards = read_json(distribution_cards_path)
    checks = spec_checks(spec)
    card_ids, card_checks = distribution_card_ids(distribution_cards)
    checks.extend(card_checks)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return {
            "valid": False,
            "summary": {"intervals": 0, "error_count": sum(1 for check in checks if not check["valid"]), "warning_count": 0},
            "resampling_manifest": {},
            "intervals": [],
            "checks": checks,
        }
    rows, row_checks = observed_rows(sample, spec)
    checks.extend(row_checks)
    intervals: list[dict[str, Any]] = []
    for index, statistic_spec in enumerate(spec["statistics"]):
        statistic_id = statistic_spec["statistic_id"]
        if statistic_spec["distribution_card_metric_id"] not in card_ids:
            checks.append(failed(f"{statistic_id}_distribution_card_resolves", "error", statistic_spec["distribution_card_metric_id"], sorted(card_ids)))
            continue
        checks.append(passed(f"{statistic_id}_distribution_card_resolves", "error", statistic_spec["distribution_card_metric_id"], sorted(card_ids)))
        if statistic_spec["metric_column"] not in (set(rows[0]) if rows else set()):
            checks.append(failed(f"{statistic_id}_metric_column_present", "error", statistic_spec["metric_column"], "sample columns"))
            continue
        checks.append(passed(f"{statistic_id}_metric_column_present", "error", statistic_spec["metric_column"], "sample columns"))
        interval, interval_checks = build_interval(
            rows,
            statistic_spec,
            float(spec["confidence_level"]),
            int(spec["n_resamples"]),
            int(spec["seed"]) + index * 101,
        )
        checks.extend(interval_checks)
        intervals.append(interval)

    error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
    warning_count = sum(1 for check in checks if check["severity"] == "warning" and not check["valid"])
    return {
        "valid": error_count == 0,
        "summary": {
            "intervals": len(intervals),
            "ok_intervals": sum(1 for item in intervals if item["status"] == "ok"),
            "warning_intervals": sum(1 for item in intervals if item["status"] == "warning"),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "resampling_manifest": {
            "sampling_unit": spec["sampling_unit"],
            "resampling_unit": spec["resampling_unit"],
            "paired": bool(spec["paired"]),
            "seed": int(spec["seed"]),
            "n_resamples": int(spec["n_resamples"]),
            "confidence_level": float(spec["confidence_level"]),
            "rows": len(rows),
        },
        "intervals": intervals,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build bootstrap intervals with resampling diagnostics")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--distribution-cards", type=Path, required=True)
    parser.add_argument("--output-intervals", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.sample, args.spec, args.distribution_cards)
    args.output_intervals.parent.mkdir(parents=True, exist_ok=True)
    args.output_intervals.write_text(json.dumps({"intervals": report["intervals"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "intervals": report["summary"]["intervals"],
                "warning_count": report["summary"]["warning_count"],
                "error_count": report["summary"]["error_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
