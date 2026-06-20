from __future__ import annotations

import argparse
import csv
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import statsmodels.api as sm

CAUSAL_PATTERNS = re.compile(r"\b(cause|causes|caused|drives|impact|effect|increases|decreases|because of)\b", re.IGNORECASE)
CSV_COLUMNS = [
    "term",
    "coefficient",
    "manual_coefficient",
    "standard_error",
    "t_value",
    "p_value",
    "ci_lower",
    "ci_upper",
    "covariance_type",
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
        return float(row[column])
    raise ValueError(f"unsupported value_type: {value_type}")


def round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)


def observed_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if parse_bool(row["outcome_observed"]) and int(row["observed_days"]) >= 7
    ]


def spec_checks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    required = {
        "version",
        "model_id",
        "question_id",
        "target_population",
        "sampling_unit",
        "outcome",
        "terms",
        "confidence_level",
        "covariance_type",
        "minimum_residual_df",
        "candidate_claim",
        "causal_claim_allowed",
        "known_limitations",
    }
    checks: list[dict[str, Any]] = []
    missing = sorted(required - set(spec))
    if missing:
        checks.append(failed("model_spec_required_fields", "error", sorted(spec), sorted(required), missing))
        return checks
    checks.append(passed("model_spec_required_fields", "error", sorted(required), sorted(required)))
    terms = [term.get("name") for term in spec["terms"] if isinstance(term, dict)]
    duplicates = sorted({term for term in terms if terms.count(term) > 1})
    if duplicates:
        checks.append(failed("model_terms_unique", "error", duplicates, "unique term names"))
    else:
        checks.append(passed("model_terms_unique", "error", terms, "unique term names"))
    if spec["covariance_type"] != "nonrobust":
        checks.append(failed("covariance_type_supported", "error", spec["covariance_type"], "nonrobust"))
    else:
        checks.append(passed("covariance_type_supported", "error", "nonrobust", "nonrobust"))
    claim = spec["candidate_claim"]
    if not spec.get("causal_claim_allowed", False) and CAUSAL_PATTERNS.search(claim):
        checks.append(failed("causal_wording_forbidden", "error", claim, "association/inference wording"))
    else:
        checks.append(passed("causal_wording_forbidden", "error", claim, "association/inference wording"))
    return checks


def term_value(row: dict[str, str], term: dict[str, Any]) -> float:
    term_type = term["type"]
    if term_type == "intercept":
        return 1.0
    if term_type == "numeric":
        value = float(row[term["column"]])
        return (value - float(term.get("center", 0.0))) / float(term.get("scale", 1.0))
    if term_type == "boolean":
        return 1.0 if parse_bool(row[term["column"]]) else 0.0
    raise ValueError(f"unsupported term type: {term_type}")


def design_matrix(rows: list[dict[str, str]], spec: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, list[str], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    columns = set(rows[0]) if rows else set()
    needed = [spec["outcome"]["column"]]
    needed.extend(term["column"] for term in spec["terms"] if term["type"] != "intercept")
    missing = sorted(set(needed) - columns)
    if missing:
        checks.append(failed("model_columns_present", "error", missing, sorted(columns)))
        return np.empty((0, 0)), np.empty((0,)), [], checks
    checks.append(passed("model_columns_present", "error", needed, "present columns"))
    names = [term["name"] for term in spec["terms"]]
    x = np.array([[term_value(row, term) for term in spec["terms"]] for row in rows], dtype=float)
    y = np.array([parse_value(row, spec["outcome"]["column"], spec["outcome"]["value_type"]) for row in rows], dtype=float)
    residual_df = len(rows) - len(names)
    if residual_df < int(spec["minimum_residual_df"]):
        checks.append(failed("minimum_residual_df", "error", residual_df, f">= {spec['minimum_residual_df']}"))
    else:
        checks.append(passed("minimum_residual_df", "error", residual_df, f">= {spec['minimum_residual_df']}"))
    rank = int(np.linalg.matrix_rank(x))
    if rank < len(names):
        checks.append(failed("design_matrix_full_rank", "error", rank, len(names)))
    else:
        checks.append(passed("design_matrix_full_rank", "error", rank, len(names)))
    return x, y, names, checks


def manual_ols(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    coefficients, *_ = np.linalg.lstsq(x, y, rcond=None)
    return coefficients


def fit_model(sample_path: Path, spec_path: Path) -> dict[str, Any]:
    rows = observed_rows(read_csv(sample_path))
    spec = read_json(spec_path)
    checks = spec_checks(spec)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return {"valid": False, "summary": {"terms": 0, "error_count": 1, "warning_count": 0}, "coefficients": [], "checks": checks}
    x, y, names, matrix_checks = design_matrix(rows, spec)
    checks.extend(matrix_checks)
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
        return {"valid": False, "summary": {"terms": 0, "error_count": error_count, "warning_count": 0}, "coefficients": [], "checks": checks}

    manual = manual_ols(x, y)
    model = sm.OLS(y, x, hasconst=True)
    result = model.fit()
    ci = result.conf_int(alpha=1.0 - float(spec["confidence_level"]))
    coefficients: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        coefficients.append(
            {
                "term": name,
                "coefficient": round_float(result.params[index]),
                "manual_coefficient": round_float(manual[index]),
                "standard_error": round_float(result.bse[index]),
                "t_value": round_float(result.tvalues[index]),
                "p_value": round_float(result.pvalues[index]),
                "ci_lower": round_float(ci[index, 0]),
                "ci_upper": round_float(ci[index, 1]),
                "covariance_type": spec["covariance_type"],
            }
        )
    max_abs_delta = max(abs(result.params[index] - manual[index]) for index in range(len(names)))
    checks.append(passed("manual_and_statsmodels_coefficients_match", "error", round_float(max_abs_delta, 12), "<= 1e-9"))
    error_count = sum(1 for check in checks if check["severity"] == "error" and not check["valid"])
    warning_count = sum(1 for check in checks if check["severity"] == "warning" and not check["valid"])
    return {
        "valid": error_count == 0,
        "summary": {
            "model_id": spec["model_id"],
            "rows": len(rows),
            "terms": len(names),
            "residual_df": int(result.df_resid),
            "r_squared": round_float(result.rsquared),
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "design_matrix": {
            "columns": names,
            "rows": [[round_float(value) for value in row] for row in x.tolist()],
            "outcome": [round_float(value) for value in y.tolist()],
        },
        "coefficients": coefficients,
        "claim": {
            "candidate": spec["candidate_claim"],
            "allowed_claim_type": "conditional_association_not_causality",
        },
        "limitations": spec["known_limitations"],
        "checks": checks,
    }


def write_coefficients_csv(path: Path, coefficients: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in coefficients:
            writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit OLS model and emit inference-oriented coefficient table")
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-coefficients", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args(argv)
    report = fit_model(args.sample, args.spec)
    write_coefficients_csv(args.output_coefficients, report["coefficients"])
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "terms": report["summary"]["terms"],
                "residual_df": report["summary"].get("residual_df"),
                "error_count": report["summary"]["error_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
