from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import warnings
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

SUPPORTED_METHODS = {"pearson", "spearman"}
SUPPORTED_VALUE_TYPES = {"boolean", "numeric", "count"}
CAUSAL_PATTERNS = re.compile(r"\b(cause|causes|caused|drives|impact|effect|increases|decreases|because of)\b", re.IGNORECASE)


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
        return float(row[column])
    if value_type == "count":
        number = float(row[column])
        if number < 0 or not number.is_integer():
            raise ValueError(f"expected non-negative count, got {row[column]!r}")
        return number
    raise ValueError(f"unsupported value_type: {value_type}")


def round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def observed_rows(rows: list[dict[str, str]], spec: dict[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    filter_spec = spec["observation_filter"]
    observed = [
        row
        for row in rows
        if parse_bool(row[filter_spec["outcome_observed_column"]])
        and int(row[filter_spec["observed_days_column"]]) >= int(filter_spec["required_observed_days"])
    ]
    return observed, [passed("observed_rows_selected", "error", len(observed), "complete observed rows")]


def spec_checks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    required = {
        "version",
        "question_id",
        "target_population",
        "sampling_unit",
        "seed",
        "n_shuffles",
        "observation_filter",
        "associations",
    }
    checks: list[dict[str, Any]] = []
    missing = sorted(required - set(spec))
    if missing:
        checks.append(failed("correlation_spec_required_fields", "error", sorted(spec), sorted(required), missing))
        return checks
    checks.append(passed("correlation_spec_required_fields", "error", sorted(required), sorted(required)))
    ids = [item.get("association_id") for item in spec["associations"] if isinstance(item, dict)]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        checks.append(failed("association_ids_unique", "error", duplicates, "unique association ids"))
    else:
        checks.append(passed("association_ids_unique", "error", len(ids), "unique association ids"))
    unsupported_methods = sorted(
        method
        for item in spec["associations"]
        if isinstance(item, dict)
        for method in item.get("methods", [])
        if method not in SUPPORTED_METHODS
    )
    if unsupported_methods:
        checks.append(failed("correlation_methods_supported", "error", unsupported_methods, sorted(SUPPORTED_METHODS)))
    else:
        checks.append(passed("correlation_methods_supported", "error", sorted(SUPPORTED_METHODS), sorted(SUPPORTED_METHODS)))
    return checks


def correlation(x: list[float], y: list[float], method: str) -> tuple[float | None, float | None, list[str]]:
    warnings_out: list[str] = []
    if len(x) < 2 or len(set(x)) < 2 or len(set(y)) < 2:
        return None, None, ["constant_or_too_small_input"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if method == "pearson":
            result = stats.pearsonr(x, y)
            statistic, pvalue = float(result.statistic), float(result.pvalue)
        elif method == "spearman":
            result = stats.spearmanr(x, y)
            statistic, pvalue = float(result.statistic), float(result.pvalue)
        else:
            raise ValueError(f"unsupported method: {method}")
    if not math.isfinite(statistic):
        warnings_out.append("correlation_not_finite")
        return None, None, warnings_out
    return statistic, pvalue, warnings_out


def shuffled_control(
    x: list[float],
    y: list[float],
    method: str,
    observed_statistic: float | None,
    n_shuffles: int,
    rng: np.random.Generator,
) -> dict[str, Any]:
    if observed_statistic is None:
        return {"n_shuffles": n_shuffles, "extreme_rate": None, "mean_abs_correlation": None}
    extreme = 0
    abs_values: list[float] = []
    y_array = np.asarray(y, dtype=float)
    for _ in range(n_shuffles):
        shuffled = rng.permutation(y_array)
        statistic, _, warnings_out = correlation(x, shuffled.tolist(), method)
        if statistic is None or warnings_out:
            continue
        abs_value = abs(statistic)
        abs_values.append(abs_value)
        if abs_value >= abs(observed_statistic):
            extreme += 1
    return {
        "n_shuffles": n_shuffles,
        "extreme_rate": round_float(extreme / len(abs_values)) if abs_values else None,
        "mean_abs_correlation": round_float(statistics.fmean(abs_values)) if abs_values else None,
    }


def analyze_association(
    rows: list[dict[str, str]],
    association: dict[str, Any],
    n_shuffles: int,
    rng: np.random.Generator,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    association_id = association["association_id"]
    checks: list[dict[str, Any]] = []
    columns = set(rows[0]) if rows else set()
    needed = [association["x_column"], association["y_column"]]
    if association.get("stratify_by"):
        needed.append(association["stratify_by"])
    missing = sorted(set(needed) - columns)
    if missing:
        checks.append(failed(f"{association_id}_columns_present", "error", missing, sorted(columns)))
        return {"association_id": association_id, "status": "blocked"}, checks
    checks.append(passed(f"{association_id}_columns_present", "error", needed, "present columns"))

    if len(rows) < int(association["minimum_n"]):
        checks.append(failed(f"{association_id}_minimum_n", "error", len(rows), f">= {association['minimum_n']}"))
        return {"association_id": association_id, "status": "blocked"}, checks
    checks.append(passed(f"{association_id}_minimum_n", "error", len(rows), f">= {association['minimum_n']}"))

    claim = association.get("candidate_claim", "")
    if not association.get("causal_claim_allowed", False) and CAUSAL_PATTERNS.search(claim):
        checks.append(failed(f"{association_id}_causal_wording_forbidden", "error", claim, "association-only wording"))
    else:
        checks.append(passed(f"{association_id}_causal_wording_forbidden", "error", claim, "association-only wording"))

    x = [parse_value(row, association["x_column"], association["x_value_type"]) for row in rows]
    y = [parse_value(row, association["y_column"], association["y_value_type"]) for row in rows]
    aggregate: dict[str, Any] = {}
    diagnostic_warning_ids: list[str] = []
    for method in association["methods"]:
        statistic, pvalue, warning_ids = correlation(x, y, method)
        diagnostic_warning_ids.extend(warning_ids)
        aggregate[method] = {
            "statistic": round_float(statistic),
            "pvalue": round_float(pvalue),
            "shuffled_control": shuffled_control(x, y, method, statistic, n_shuffles, rng),
        }

    strata: list[dict[str, Any]] = []
    sign_reversal = False
    stratify_by = association.get("stratify_by")
    if stratify_by:
        aggregate_sign = math.copysign(1, aggregate["pearson"]["statistic"]) if aggregate.get("pearson", {}).get("statistic") not in (None, 0) else 0
        for level in sorted({row[stratify_by] for row in rows}):
            group = [row for row in rows if row[stratify_by] == level]
            group_x = [parse_value(row, association["x_column"], association["x_value_type"]) for row in group]
            group_y = [parse_value(row, association["y_column"], association["y_value_type"]) for row in group]
            statistic, pvalue, warning_ids = correlation(group_x, group_y, "pearson")
            if warning_ids:
                diagnostic_warning_ids.extend([f"{level}:{warning}" for warning in warning_ids])
            if statistic is not None and aggregate_sign and math.copysign(1, statistic) != aggregate_sign:
                sign_reversal = True
            strata.append(
                {
                    "level": level,
                    "n": len(group),
                    "pearson": round_float(statistic),
                    "pvalue": round_float(pvalue),
                    "warning_ids": warning_ids,
                }
            )
    if sign_reversal:
        diagnostic_warning_ids.append("stratified_sign_reversal")
        checks.append(failed(f"{association_id}_stratified_sign_reversal", "warning", True, False))
    elif stratify_by:
        checks.append(passed(f"{association_id}_stratified_sign_reversal", "warning", False, False))

    status = "warning" if diagnostic_warning_ids else "ok"
    return {
        "association_id": association_id,
        "x_column": association["x_column"],
        "y_column": association["y_column"],
        "stratify_by": stratify_by,
        "n": len(rows),
        "aggregate": aggregate,
        "strata": strata,
        "diagnostic_warning_ids": sorted(set(diagnostic_warning_ids)),
        "claim": claim,
        "allowed_claim_type": "association_only",
        "status": status,
    }, checks


def run(sample_path: Path, spec_path: Path) -> dict[str, Any]:
    sample = read_csv(sample_path)
    spec = read_json(spec_path)
    checks = spec_checks(spec)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return {"valid": False, "summary": {"associations": 0, "error_count": 1, "warning_count": 0}, "associations": [], "checks": checks}
    rows, row_checks = observed_rows(sample, spec)
    checks.extend(row_checks)
    rng = np.random.default_rng(int(spec["seed"]))
    associations: list[dict[str, Any]] = []
    for association in spec["associations"]:
        result, association_checks = analyze_association(rows, association, int(spec["n_shuffles"]), rng)
        checks.extend(association_checks)
        associations.append(result)
    error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
    warning_count = sum(1 for check in checks if check["severity"] == "warning" and not check["valid"])
    return {
        "valid": error_count == 0,
        "summary": {
            "associations": len(associations),
            "ok_associations": sum(1 for item in associations if item.get("status") == "ok"),
            "warning_associations": sum(1 for item in associations if item.get("status") == "warning"),
            "error_count": error_count,
            "warning_count": warning_count,
            "n_shuffles": int(spec["n_shuffles"]),
            "seed": int(spec["seed"]),
        },
        "associations": associations,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit observational correlations without causal claims")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.sample, args.spec)
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "associations": report["summary"]["associations"],
                "warning_count": report["summary"]["warning_count"],
                "error_count": report["summary"]["error_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
