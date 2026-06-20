from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REQUIRED_SPEC_FIELDS = {
    "question_id",
    "target_population",
    "sampling_unit",
    "sampling_frame",
    "inclusion_mechanism",
    "response_mechanism",
    "key_column",
    "eligible_column",
    "test_user_column",
    "outcome_observed_column",
    "observed_days_column",
    "required_observed_days",
    "inclusion_probability_column",
    "response_probability_column",
    "weight_column",
    "segment_columns",
    "minimum_frame_coverage_rate",
    "minimum_response_rate",
}
SUPPORTED_UNITS = {"user_id"}


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
        raise ValueError("sampling spec must be a JSON object")
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


def duplicate_values(rows: list[dict[str, str]], column: str) -> list[str]:
    counts = Counter(row.get(column, "") for row in rows)
    return sorted(value for value, count in counts.items() if value and count > 1)


def require_columns(
    rows: list[dict[str, str]],
    required: set[str],
    label: str,
) -> dict[str, Any]:
    columns = set(rows[0]) if rows else set()
    missing = sorted(required - columns)
    if missing:
        return failed(f"{label}_columns_present", "error", sorted(columns), sorted(required), missing)
    return passed(f"{label}_columns_present", "error", sorted(required), sorted(required))


def eligible_population(
    population: list[dict[str, str]],
    spec: dict[str, Any],
) -> list[dict[str, str]]:
    eligible_column = spec["eligible_column"]
    test_column = spec["test_user_column"]
    result: list[dict[str, str]] = []
    for row in population:
        if parse_bool(row[eligible_column]) and not parse_bool(row[test_column]):
            result.append(row)
    return result


def row_ids(rows: list[dict[str, str]], key: str) -> set[str]:
    return {row[key] for row in rows}


def probability_domain_check(
    rows: list[dict[str, str]],
    columns: list[str],
    label: str,
) -> dict[str, Any]:
    invalid: list[dict[str, Any]] = []
    for row in rows:
        for column in columns:
            try:
                value = parse_float(row[column])
            except ValueError:
                invalid.append({"user_id": row.get("user_id"), "column": column, "value": row.get(column)})
                continue
            if not 0 < value <= 1:
                invalid.append({"user_id": row.get("user_id"), "column": column, "value": value})
    if invalid:
        return failed(f"{label}_probabilities_in_domain", "error", len(invalid), "(0, 1]", invalid)
    return passed(f"{label}_probabilities_in_domain", "error", len(rows), "(0, 1]")


def weights_match_check(rows: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    probability_column = spec["inclusion_probability_column"]
    weight_column = spec["weight_column"]
    tolerance = float(spec.get("weight_tolerance", 0.00001))
    invalid: list[dict[str, Any]] = []
    for row in rows:
        try:
            probability = parse_float(row[probability_column])
            weight = parse_float(row[weight_column])
        except ValueError:
            invalid.append({"user_id": row.get("user_id"), "reason": "non-numeric"})
            continue
        expected = 1 / probability
        if weight <= 0 or abs(weight - expected) > tolerance:
            invalid.append(
                {
                    "user_id": row.get("user_id"),
                    "observed_weight": weight,
                    "expected_weight": round(expected, 6),
                }
            )
    if invalid:
        return failed("sample_weights_match_inclusion_probability", "error", len(invalid), "weight ~= 1 / inclusion_probability", invalid)
    return passed("sample_weights_match_inclusion_probability", "error", len(rows), "weight ~= 1 / inclusion_probability")


def complete_window_check(sample: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    column = spec["observed_days_column"]
    required_days = int(spec["required_observed_days"])
    incomplete: list[dict[str, Any]] = []
    for row in sample:
        try:
            observed_days = int(row[column])
        except ValueError:
            incomplete.append({"user_id": row.get("user_id"), "observed_days": row.get(column)})
            continue
        if observed_days < required_days:
            incomplete.append({"user_id": row.get("user_id"), "observed_days": observed_days})
    if incomplete:
        return failed("sample_complete_observation_windows", "error", len(incomplete), f">= {required_days} days", incomplete)
    return passed("sample_complete_observation_windows", "error", len(sample), f">= {required_days} days")


def group_counts(rows: list[dict[str, str]], dimension: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row[dimension]] += 1
    return dict(counts)


def coverage_check(
    eligible: list[dict[str, str]],
    frame: list[dict[str, str]],
    spec: dict[str, Any],
) -> dict[str, Any]:
    key = spec["key_column"]
    threshold = float(spec["minimum_frame_coverage_rate"])
    frame_ids = row_ids(frame, key)
    segment_rows: list[dict[str, Any]] = []
    for dimension in spec["segment_columns"]:
        population_counts = group_counts(eligible, dimension)
        framed_counts = group_counts([row for row in eligible if row[key] in frame_ids], dimension)
        for level, population_count in sorted(population_counts.items()):
            frame_count = framed_counts.get(level, 0)
            rate = frame_count / population_count if population_count else 0.0
            if rate < threshold:
                segment_rows.append(
                    {
                        "dimension": dimension,
                        "level": level,
                        "eligible_users": population_count,
                        "frame_users": frame_count,
                        "coverage_rate": round(rate, 6),
                    }
                )
    if segment_rows:
        return failed("frame_segment_coverage", "warning", len(segment_rows), f">= {threshold}", segment_rows)
    return passed("frame_segment_coverage", "warning", "all segments", f">= {threshold}")


def response_check(sample: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    response_column = spec["outcome_observed_column"]
    threshold = float(spec["minimum_response_rate"])
    segment_rows: list[dict[str, Any]] = []
    for dimension in spec["segment_columns"]:
        buckets: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in sample:
            buckets[row[dimension]].append(row)
        for level, rows in sorted(buckets.items()):
            respondents = sum(1 for row in rows if parse_bool(row[response_column]))
            rate = respondents / len(rows) if rows else 0.0
            if rate < threshold:
                segment_rows.append(
                    {
                        "dimension": dimension,
                        "level": level,
                        "sampled_users": len(rows),
                        "respondents": respondents,
                        "response_rate": round(rate, 6),
                    }
                )
    if segment_rows:
        return failed("sample_segment_response", "warning", len(segment_rows), f">= {threshold}", segment_rows)
    return passed("sample_segment_response", "warning", "all segments", f">= {threshold}")


def unequal_probability_check(frame: list[dict[str, str]], spec: dict[str, Any]) -> dict[str, Any]:
    column = spec["inclusion_probability_column"]
    probabilities = sorted({parse_float(row[column]) for row in frame})
    if len(probabilities) <= 1:
        return passed("unequal_inclusion_probabilities_declared", "warning", probabilities, "variation visible when weights are required")
    return failed(
        "unequal_inclusion_probabilities_declared",
        "warning",
        probabilities,
        "document weights before estimating population parameters",
        [{"min": probabilities[0], "max": probabilities[-1], "distinct_values": len(probabilities)}],
    )


def validate_sampling(
    population: list[dict[str, str]],
    frame: list[dict[str, str]],
    sample: list[dict[str, str]],
    segment_reference: list[dict[str, str]],
    spec: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    missing_spec = sorted(REQUIRED_SPEC_FIELDS - set(spec))
    if missing_spec:
        checks.append(failed("sampling_spec_required_fields", "error", len(missing_spec), "all required fields", missing_spec))
        return {"valid": False, "checks": checks, "summary": {}}
    checks.append(passed("sampling_spec_required_fields", "error", len(spec), "all required fields"))

    if spec["sampling_unit"] not in SUPPORTED_UNITS:
        checks.append(failed("sampling_unit_supported", "error", spec["sampling_unit"], sorted(SUPPORTED_UNITS)))
    else:
        checks.append(passed("sampling_unit_supported", "error", spec["sampling_unit"], sorted(SUPPORTED_UNITS)))

    key = spec["key_column"]
    population_required = {
        key,
        spec["eligible_column"],
        spec["test_user_column"],
        *spec["segment_columns"],
    }
    frame_required = {
        key,
        spec["inclusion_probability_column"],
        spec["response_probability_column"],
        spec["weight_column"],
    }
    sample_required = {
        key,
        spec["inclusion_probability_column"],
        spec["response_probability_column"],
        spec["weight_column"],
        spec["outcome_observed_column"],
        spec["observed_days_column"],
        *spec["segment_columns"],
    }
    segment_required = {"segment_id", "dimension", "level"}
    checks.extend(
        [
            require_columns(population, population_required, "population"),
            require_columns(frame, frame_required, "frame"),
            require_columns(sample, sample_required, "sample"),
            require_columns(segment_reference, segment_required, "segment_reference"),
        ]
    )
    if any(not check["valid"] and check["severity"] == "error" for check in checks):
        return {"valid": False, "checks": checks, "summary": {}}

    for label, rows in (
        ("population", population),
        ("frame", frame),
        ("sample", sample),
        ("segment_reference", segment_reference),
    ):
        column = key if label != "segment_reference" else "segment_id"
        duplicates = duplicate_values(rows, column)
        if duplicates:
            checks.append(failed(f"{label}_key_unique", "error", len(duplicates), "0 duplicates", duplicates))
        else:
            checks.append(passed(f"{label}_key_unique", "error", len(rows), "unique key values"))

    population_ids = row_ids(population, key)
    frame_ids = row_ids(frame, key)
    sample_ids = row_ids(sample, key)
    unknown_frame_users = sorted(frame_ids - population_ids)
    unknown_sample_users = sorted(sample_ids - frame_ids)
    if unknown_frame_users:
        checks.append(failed("frame_users_exist_in_population", "error", len(unknown_frame_users), "all frame users in population", unknown_frame_users))
    else:
        checks.append(passed("frame_users_exist_in_population", "error", len(frame_ids), "all frame users in population"))
    if unknown_sample_users:
        checks.append(failed("sample_users_exist_in_frame", "error", len(unknown_sample_users), "all sample users in frame", unknown_sample_users))
    else:
        checks.append(passed("sample_users_exist_in_frame", "error", len(sample_ids), "all sample users in frame"))

    checks.append(
        probability_domain_check(
            frame,
            [spec["inclusion_probability_column"], spec["response_probability_column"]],
            "frame",
        )
    )
    checks.append(
        probability_domain_check(
            sample,
            [spec["inclusion_probability_column"], spec["response_probability_column"]],
            "sample",
        )
    )
    checks.append(weights_match_check(sample, spec))
    checks.append(complete_window_check(sample, spec))

    eligible = eligible_population(population, spec)
    checks.append(coverage_check(eligible, frame, spec))
    checks.append(response_check(sample, spec))
    checks.append(unequal_probability_check(frame, spec))

    errors = [check for check in checks if check["severity"] == "error" and not check["valid"]]
    warnings = [check for check in checks if check["severity"] == "warning" and not check["valid"]]
    respondents = sum(1 for row in sample if parse_bool(row[spec["outcome_observed_column"]]))
    frame_eligible_count = len(row_ids(frame, key) & {row[key] for row in eligible})
    summary = {
        "question_id": spec["question_id"],
        "target_population": spec["target_population"],
        "sampling_unit": spec["sampling_unit"],
        "eligible_population_users": len(eligible),
        "frame_users": len(frame_ids),
        "sample_rows": len(sample),
        "respondent_rows": respondents,
        "overall_frame_coverage_rate": round(frame_eligible_count / len(eligible), 6) if eligible else None,
        "overall_response_rate": round(respondents / len(sample), 6) if sample else None,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "estimation_risks": [check["id"] for check in warnings],
    }
    return {"valid": not errors, "checks": checks, "summary": summary}


def run(
    population_path: Path,
    frame_path: Path,
    sample_path: Path,
    segment_reference_path: Path,
    spec_path: Path,
) -> dict[str, Any]:
    return validate_sampling(
        population=read_csv(population_path),
        frame=read_csv(frame_path),
        sample=read_csv(sample_path),
        segment_reference=read_csv(segment_reference_path),
        spec=read_json(spec_path),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a sampling frame and sampled user observations")
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--frame", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--segments", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run(args.population, args.frame, args.sample, args.segments, args.spec)
    except (OSError, csv.Error, json.JSONDecodeError, ValueError, KeyError) as error:
        print(str(error), file=sys.stderr)
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if report["valid"] or args.allow_failures:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
